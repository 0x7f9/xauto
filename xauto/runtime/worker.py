#!/usr/bin/env python3

from xauto.internal.geckodriver.driver import DriverPool
from xauto.utils.logging import debug_logger
from xauto.utils.config import Config
from xauto.utils.setup import debug
from xauto.utils.validation import is_connection_error
from xauto.internal.memory import acquire_driver_with_pressure_check

from typing import Any, Optional
import time
import threading
import traceback
import queue

class Worker(threading.Thread):
    __slots__ = (
        'task_queue', 'driver_pool', 'driver', 'name', 'task_count', 
        'successful_tasks', 'failed_tasks', '_exit_reason', 
        '_max_task_retries', 'manager', 'current_task'
    )
    
    def __init__(
            self, 
            task_queue, 
            driver_pool: DriverPool, 
            name: Optional[str] = None, 
            manager: Optional[Any] = None
    ):
        super().__init__(daemon=True)
        
        self.task_queue = task_queue
        self.driver_pool = driver_pool
        self.name = name or "Worker-no_name"
        self.manager = manager
        self.driver = None
        self.current_task = None

        self.task_count = 0
        self.successful_tasks = 0
        self.failed_tasks = 0
        self._exit_reason = "normal"
        self._max_task_retries = Config.get("misc.timeouts.max_worker_task_retries")
    
    def stop(self) -> None:
        self.task_queue.put(None)

    def get_worker_stats(self) -> dict:
        return {
            'worker': self.name,
            'task_count': self.task_count,
            'successful_tasks': self.successful_tasks,
            'failed_tasks': self.failed_tasks,
            'exit_reason': self._exit_reason
        }

    def run(self):
        if not self.manager:
            self._exit_reason = "no_manager"
            return
        
        processor = self.manager.task_processor

        while True:
            try:
                task_wrapper = self.task_queue.get(timeout=0.5)
            except queue.Empty:
                time.sleep(1)
                continue

            if task_wrapper is None:
                debug_logger.info(f"{self.name}: Exiting worker, got stop signal")
                self.task_queue.task_done()
                self._return_driver()
                break

            self.current_task = task_wrapper
            try:
                if not self.driver:
                    # worker will block inside here waiting for a driver if under high load
                    self.driver = acquire_driver_with_pressure_check(self.driver_pool, context=f"{self.name} trying to get driver")

                processor(task_wrapper.idx, self.driver, task_wrapper.tasks)
                self.successful_tasks += 1

            except Exception as e:
                self.failed_tasks += 1
                self._handle_driver_failure(e)
                
                task_wrapper.retry_count += 1
                if task_wrapper.retry_count <= self._max_task_retries:
                    self.task_queue.put_nowait(task_wrapper)

            finally:
                self.task_count += 1
                self.current_task = None
                self.task_queue.task_done()
                self._maybe_destroy_driver_for_pressure()

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
        
        delay = Config.get("misc.timeouts.driver_recreate_delay")
        if debug:
            debug_logger.warning(f"{self.name} waiting {delay}s before recreating")
        time.sleep(delay)

    def _return_driver(self) -> None:
        if not self.driver:
            return
        try:
            self.driver_pool.return_driver(self.driver)
        except Exception as e:
            debug_logger.error(f"Returning {self.name} failed: {e}")
        finally:
            self.driver = None
    
    def _maybe_destroy_driver_for_pressure(self):
        if not self.driver or not self.driver_pool:
            return

        if not self.driver_pool.should_close_driver_for_pressure():
            return

        if not self.manager:
            return

        if self.manager._allow_driver_destroy_under_pressure(self):
            try:
                self.driver_pool._destroy(self.driver)
            except Exception as e:
                debug_logger.error(f"Destroying {self.name} under pressure: {e}")
            finally:
                self.driver = None

