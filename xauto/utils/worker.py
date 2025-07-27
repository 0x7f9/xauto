#!/usr/bin/env python3

from xauto.utils.logging import debug_logger
from xauto.utils.config import Config
from xauto.utils.setup import debug, is_connection_error
from xauto.internal.memory import acquire_driver_with_pressure_check

import time
import threading
import traceback

class TaskWrapper:
    __slots__ = ('task', 'retry_count')
    
    def __init__(self, task):
        self.task = task
        self.retry_count = 0


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
        get = self.task_queue.get
        put = self.task_queue.put
        done = self.task_queue.task_done
        monotonic = time.monotonic
        should_return = self._should_return_driver_for_pressure
        acquire = self.acquire_driver
        handle_fail = self._handle_driver_failure
        task_fn = self.per_task_fn
        cleanup = self.cleanup_driver

        while True:
            task = get()
            if task is None:
                done()
                break
            
            self.task_count += 1
            start = monotonic()
            try:
                if self.driver is None and not acquire():
                    self._exit_reason = "driver_acquisition_failed"
                    return

                actual = task.task
                task_fn(actual, self.driver)
                self.successful_tasks += 1

                if should_return():
                    if self.driver is not None:
                        cleanup()
            except Exception as e:
                self.failed_tasks += 1
                handle_fail(e)
                
                task.retry_count += 1
                if task.retry_count <= self._max_task_retries:
                    put(task)
            finally:
                done()

            duration = monotonic() - start
            self._total_task_time += duration
            if debug and self.task_count % 10 == 0 and monotonic() - self._last_log_time >= self.log_interval:
                self._last_log_time = monotonic()
                avg = self._total_task_time / self.task_count
                success_rate = self.successful_tasks / max(1, self.task_count)
                debug_logger.info(f"{self.name}: {self.task_count} tasks, avg {avg:.2f}s, success rate: {success_rate:.1%}")

        cleanup()
        runtime = monotonic() - self._start_time
        debug_logger.info(f"{self.name}: exiting after {runtime:.1f}s, {self.task_count} tasks "
                        f"({self.successful_tasks} OK, {self.failed_tasks} FAIL)")

    def _handle_driver_failure(self, error):
        current_time = time.monotonic()
        debug_mode = debug
        error = str(error).lower()

        # if debug_mode:
        #     if is_connection_error(error):
        #         debug_logger.warning(f"{self.name}: Driver connection error on task #{self.task_count}: {error}")
        #     else:
        #         debug_logger.error(f"{self.name}: Driver error on task #{self.task_count}: {error}, replacing driver")
        #     debug_logger.debug(f"{self.name}: Exception traceback: {traceback.format_exc()}")

        if is_connection_error(error):
            debug_logger.warning(f"{self.name}: Driver connection error on task #{self.task_count}: {error}")
        else:
            debug_logger.error(f"{self.name}: Driver error on task #{self.task_count}: {error}, replacing driver")
            debug_logger.debug(f"{self.name}: Exception traceback: {traceback.format_exc()}")
    
        if current_time - self._circuit_breaker_last_failure < Config.get("misc.timeouts.circuit_breaker_window"):
            self._circuit_breaker_failures += 1
        else:
            self._circuit_breaker_failures = 1
        self._circuit_breaker_last_failure = current_time
        
        if self.driver:
            try:
                self.driver_pool._destroy(self.driver)
            except Exception as e:
                debug_logger.error(f"{self.name}: Error destroying failed driver: {e}")
            self.driver = None
        
        if self._circuit_breaker_failures >= self._circuit_breaker_threshold:
            delay = min(Config.get("misc.timeouts.circuit_breaker_max_delay"), 2 ** (self._circuit_breaker_failures - self._circuit_breaker_threshold))
            if debug_mode:
                debug_logger.warning(f"{self.name}: Circuit breaker open, waiting {delay}s before retry")
            time.sleep(delay)

    def acquire_driver(self):
        debug_mode = debug
        if debug_mode:
            debug_logger.debug(f"{self.name}: Acquiring driver with blocking semantics")
        try:
            self.driver = acquire_driver_with_pressure_check(self.driver_pool, context=self.name)
            if self.driver is not None:
                if debug_mode:
                    debug_logger.debug(f"{self.name}: Successfully acquired driver")
                return True
            else:
                if debug_mode:
                    debug_logger.error(f"{self.name}: Failed to acquire driver")
                return False
        except Exception as e:
            if debug_mode:
                debug_logger.error(f"{self.name}: Exception during driver acquisition: {e}", exc_info=True)
            return False

    def cleanup_driver(self):
        if self.driver:
            try:
                self.driver_pool.return_driver(self.driver)
            except Exception as e:
                debug_logger.error(f"{self.name}: Error returning driver: {e}")
            self.driver = None

    def stop(self):
        self.task_queue.put(None)

    def get_stats(self) -> dict:
        with self._stats_lock:
            return {
                'task_count': self.task_count,
                'successful_tasks': self.successful_tasks,
                'failed_tasks': self.failed_tasks,
                'exit_reason': self._exit_reason
            }
    
    def _should_return_driver_for_pressure(self) -> bool:
        if not self.driver or not self.driver_pool:
            return False
        
        if self.driver_pool.should_close_driver_for_pressure():
            if not self.manager:
                self.driver_pool.mark_driver_closed_for_pressure()
                
                try:
                    self.driver_pool._destroy(self.driver)
                    self.driver = None
                    return True
                except Exception as e:
                    debug_logger.error(f"{self.name}: Error destroying driver under pressure: {e}")
                    return False
            
            now = time.monotonic()
            
            with self.manager._stats_lock:
                if now - self.manager.last_scale_down_time >= self.manager.scale_down_cooldown:
                    if self.manager._scale_downs_this_cycle < self.manager.scale_down_step:
                        self.manager._scale_downs_this_cycle += 1
                        self.manager.last_scale_down_time = now
                        
                        debug_logger.info(f"{self.name}: Reclaiming driver under pressure (cycle {self.manager._scale_downs_this_cycle}/{self.manager.scale_down_step})")
                        
                        try:
                            self.driver_pool._destroy(self.driver)
                            self.driver = None
                            return True
                        except Exception as e:
                            debug_logger.error(f"{self.name}: Error destroying driver under pressure: {e}")
                            return False
            
            return False
        else:
            if self.manager:
                with self.manager._stats_lock:
                    self.manager._scale_downs_this_cycle = 0
            
        return False