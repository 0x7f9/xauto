#!/usr/bin/env python3

from xauto.utils.logging import debug_logger, monitor_details
from xauto.utils.config import Config
from xauto.utils.setup import debug
from xauto.utils.validation import is_connection_error
from xauto.internal.memory import acquire_driver_with_pressure_check

import time
import threading
import traceback
import queue

class Worker(threading.Thread):
    __slots__ = (
        'task_queue', 'driver_pool', 'per_task_fn', 'daemon', 
        'driver', 'name', 'task_count', 'successful_tasks', 'failed_tasks',
        '_start_time', '_total_task_time', '_last_log_time', 'log_interval', 
        '_exit_reason', '_stats_lock', '_circuit_breaker_failures', 
        '_circuit_breaker_last_failure', '_circuit_breaker_threshold', '_max_task_retries',
        'manager'
    )
    
    def __init__(self, task_queue, driver_pool, per_task_fn, name=None, manager=None, *args, **kwargs):
        try:
            kwargs.pop('name', None)
            super().__init__(name=name, *args, **kwargs)
        except Exception as e:
            debug_logger.error(f"Worker constructor error: {e}. args={args}, kwargs={kwargs}", exc_info=True)
            raise
        
        self.task_queue = task_queue
        self.driver_pool = driver_pool
        self.per_task_fn = per_task_fn
        self.daemon = True
        self.driver = None
        self.name = name or f"Worker-{id(self)}"
        self.task_count = 0
        self.successful_tasks = 0
        self.failed_tasks = 0
        self._total_task_time = 0.0
        self._last_log_time = 0.0
        self._stats_lock = threading.Lock()
        self._circuit_breaker_failures = 0
        self._circuit_breaker_last_failure = 0.0
        self._circuit_breaker_threshold = 3
        self.log_interval = 30
        self._exit_reason = "normal"
        self._max_task_retries = Config.get("misc.timeouts.max_task_retries")
        self._start_time = time.monotonic()
        self.manager = manager
    
    def run(self):
        fn = self.per_task_fn

        while True:
            try:
                task = self.task_queue.get(timeout=0.5)
            except queue.Empty:
                time.sleep(1)
                continue
            
            if task is None:
                debug_logger.info(f"{self.name}: Exiting worker, got stop().")
                self.task_queue.task_done()
                self.return_driver()
                break

            try:
                if not self.driver:
                    # worker will block inside here waiting for a driver if under high load
                    self.driver = acquire_driver_with_pressure_check(self.driver_pool, context=self.name)

                fn(task.task, self.driver)

                self._should_destroy_driver_for_pressure()
              
            except Exception as e:
                self._handle_driver_failure(e)
                
                task.retry_count += 1
                if task.retry_count <= self._max_task_retries:
                    self.task_queue.put(task)
            finally:
                self.task_queue.task_done()

    def _handle_driver_failure(self, error: Exception) -> None:
        error_str = str(error).lower()

        if is_connection_error(error_str):
            debug_logger.warning(f"{self.name}: Driver connection error on task #{self.task_count}: {error}")
        else:
            debug_logger.error(f"{self.name}: Driver error on task #{self.task_count}: {error}, replacing driver")
            debug_logger.error(f"{self.name}: Traceback: {traceback.format_exc()}")
    
        if self.driver:
            try:
                self.driver_pool._destroy(self.driver)
            except Exception as e:
                debug_logger.error(f"Destroying {self.name} failed: {e}")
            self.driver = None
        
        delay = Config.get("misc.timeouts.recreate_max_delay")
        if debug:
            debug_logger.warning(f"{self.name} waiting {delay}s before recreating")
        time.sleep(delay)

    def return_driver(self) -> None:
        if not self.driver:
            return
        try:
            self.driver_pool.return_driver(self.driver)
        except Exception as e:
            debug_logger.error(f"Returning {self.name}: {e}")
        self.driver = None

    def stop(self) -> None:
        self.task_queue.put(None)

    def get_stats(self) -> dict:
        with self._stats_lock:
            return {
                'task_count': self.task_count,
                'successful_tasks': self.successful_tasks,
                'failed_tasks': self.failed_tasks,
                'exit_reason': self._exit_reason
            }
    
    def _should_destroy_driver_for_pressure(self):
        if not self.driver or not self.driver_pool:
            return

        if not self.driver_pool.should_close_driver_for_pressure():
            if self.manager:
                with self.manager._stats_lock:
                    self.manager._scale_downs_this_cycle = 0
            return

        if not self.manager:
            self.driver_pool.mark_driver_closed_for_pressure()
            try:
                self.driver_pool._destroy(self.driver)
            except Exception as e:
                debug_logger.error(f"Destroying {self.name} under pressure: {e}")
            finally:
                self.driver = None
            return

        now = time.monotonic()
        with self.manager._stats_lock:
            if now - self.manager.last_scale_down_time < self.manager.scale_down_cooldown:
                return
            if self.manager._scale_downs_this_cycle >= self.manager.scale_down_step:
                return

        self.manager._scale_downs_this_cycle += 1
        self.manager.last_scale_down_time = now

        monitor_details.info(
            f"[DESTROY_DRIVER] {self.name} under pressure "
            f"(cycle {self.manager._scale_downs_this_cycle}/{self.manager.scale_down_step})"
        )

        try:
            self.driver_pool._destroy(self.driver)
        except Exception as e:
            debug_logger.error(f"Destroying {self.name} under pressure: {e}")
        finally:
            self.driver = None

