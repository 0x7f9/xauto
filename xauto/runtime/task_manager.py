#!/usr/bin/env python3

from xauto.runtime.worker import Worker
from xauto.internal.dataclasses import TaskWrapper
from xauto.internal.geckodriver.driver import DriverPool
from xauto.internal.thread_safe import ThreadSafeList, SafeThread
from xauto.utils.logging import debug_logger, monitor_details
from xauto.utils.config import Config
from xauto.utils.setup import debug

from typing import Optional, Callable, Any, Iterable
import threading
import queue
import time

class TaskManager:
    __slots__ = (
        'driver_pool', 'task_processor', 'task_queue', 'tasks', 'config', 'max_workers', 
        'worker_timeout', 'workers', 'stop_event', 'monitor_thread', '_shutdown_complete', 
        '_stats_lock', 'monitor_interval', 'scale_up_step', 'scale_down_step',
        '_last_driver_creation_failure', '_consecutive_driver_failures',
        'scale_down_cooldown', 'last_scale_down_time', '_scale_downs_this_cycle',
        '_tasks_added', '_last_scale_up_blocked_log', '_last_scale_up_blocked_reason',
        '_workers_lock'
    )
    
    def __init__(self, driver_pool: DriverPool, task_processor: Callable, 
                 max_workers: Optional[int] = None, task_queue: Optional[queue.Queue] = None,
                 tasks: Optional[list] = None):
        
        if max_workers is None:
            debug_logger.warning("No worker limit set in TaskManager")
            return
        
        self.driver_pool = driver_pool
        self.task_processor = task_processor
        self.task_queue = task_queue or queue.Queue()
        self.tasks = tasks
        self.max_workers = max_workers
        self.worker_timeout = Config.get("misc.timeouts.worker")
        self.monitor_interval = Config.get("misc.thread_monitoring.interval_sec")
        autoscaling = Config.get("resources.driver_autoscaling", {})
        self.scale_up_step = autoscaling.get("step_up", 2)
        self.scale_down_step = autoscaling.get("step_down", 1)
        self.scale_down_cooldown = autoscaling.get("scale_down_cooldown", 5.0)
        self.last_scale_down_time = 0.0
        self._scale_downs_this_cycle = 0
        self.workers = ThreadSafeList()
        self.stop_event = threading.Event()
        self.monitor_thread = None
        self._shutdown_complete = threading.Event()
        self._stats_lock = threading.Lock()
        self._last_driver_creation_failure = 0.0
        self._consecutive_driver_failures = 0
        self._tasks_added = 0
        self._last_scale_up_blocked_log = 0.0
        self._last_scale_up_blocked_reason = None
        self._workers_lock = threading.Lock()

    def _create_worker(self, name: str) -> Worker:
        return Worker(
            task_queue=self.task_queue,
            driver_pool=self.driver_pool,
            per_task_fn=self._task_wrapper,
            manager=self,
            name=name
        )
    
    def add_task(self, task: Any) -> None:
        self.task_queue.put(TaskWrapper(task))
        self._tasks_added += 1
    
    def add_tasks(self, tasks: Iterable[Any]) -> None:
        if not tasks:
            return
        
        task_count = 0
        for task in tasks:
            self.task_queue.put(TaskWrapper(task))
            task_count += 1
        self._tasks_added += task_count
    
    def start(self, initial_workers: Optional[int] = None) -> None:
        if len(self.workers) > 0:
            debug_logger.warning("TaskManager already started, ignoring start request")
            return
        
        desired_workers = initial_workers if initial_workers is not None else 1
        num_workers = min(desired_workers, self.max_workers)

        debug_logger.info(f"Starting TaskManager with {num_workers} workers")

        self.monitor_thread = SafeThread(
            target_fn=self._monitor_workers,
            name="TaskManagerMonitor"
        )
        self.monitor_thread.start()

        if num_workers == 0:
            return
    
        if not self.driver_pool.can_create_driver():
            debug_logger.warning(f"Cannot create driver, starting with 0 workers instead of {num_workers}")
            return

        for i in range(num_workers):
            worker = self._create_worker(f"Worker-{i}")
            self.workers.append(worker)
            worker.start()

        time.sleep(0.1)

    def _task_wrapper(self, task: Any, driver: Any) -> None:
        if self.tasks is not None:
            self.task_processor(task, driver, self.tasks)
        else:
            self.task_processor(task, driver)
    
    def _monitor_workers(self) -> None:
        while not self.stop_event.is_set():
            if self.stop_event.wait(timeout=self.monitor_interval):
                break

            try:
                self._check_worker_health()
                self._scale_workers_if_needed()
            except Exception as e:
                debug_logger.error(f"[MONITOR_WORKERS_THREAD] runtime {e}", exc_info=True)
            
            time.sleep(1)
    
    def _check_worker_health(self) -> None:
        dead_count = 0
        current_time = time.monotonic()
        live_workers = []

        with self._workers_lock:
            for worker in self.workers:
                if not worker.is_alive():
                    worker_age = current_time - worker._start_time
                    exit_reason = worker._exit_reason

                    if worker_age > 2.0:
                        dead_count += 1
                        debug_logger.warning(
                            f"Worker {worker.name} is dead after {worker_age:.1f}s "
                            f"(exit_reason: {exit_reason}), scheduling replacement"
                        )
                    else:
                        debug_logger.info(
                            f"Worker {worker.name} appears dead but still in startup phase "
                            f"(age: {worker_age:.1f}s)"
                        )
                    continue 

                live_workers.append(worker)

            self.workers.clear()
            for w in live_workers:
                self.workers.append(w)

        if dead_count > 0:
            try:
                debug_logger.info(f"Replacing {dead_count} dead workers")
                self._replace_dead_workers(dead_count)
            except Exception as e:
                debug_logger.error(f"Failed to replace dead workers: {e}", exc_info=True)
    
    def _replace_dead_workers(self, dead_count: int) -> None:
        if self.stop_event.is_set():
            return
        
        if not self.driver_pool.can_create_driver():
            debug_logger.warning(f"Cannot create driver, skipping replacement of {dead_count} dead workers")
            return
        
        for i in range(dead_count):
            worker = self._create_worker(f"Worker-Replacement-{i}")
            self.workers.append(worker)
            worker.start()
        time.sleep(0.1)
    
    def _scale_workers_if_needed(self) -> None:
        qsize = self.task_queue.qsize()
        current_workers = len(self.workers)
        
        if current_workers >= self.max_workers:
            return
        
        if (
            qsize > 0
            and self.driver_pool.can_create_driver()
        ):
            workers_to_add = min(
                self.scale_up_step,
                self.max_workers - current_workers,
            )

            monitor_details.info(
                f"[SCALE_WORKERS] current={current_workers}, "
                f"drivers_inuse={self.driver_pool.drivers_inuse}, adding={workers_to_add}"
            )

            for i in range(workers_to_add):
                worker = self._create_worker(f"Worker-{current_workers + i}")
                self.workers.append(worker)
                worker.start()
            time.sleep(0.5) 

            new_count = len(self.workers)
            monitor_details.info(
                f"[SCALE_WORKERS] new workers={new_count}, drivers_active={self.driver_pool.drivers_inuse}"
            )
    
    def _shutdown_workers(self) -> None:
        debug_logger.info("Shutting down all workers")
        join_timeout = min(2.0, Config.get("misc.timeouts.join"))
        worker_count = len(self.workers)
        
        debug_logger.info(f"Stopping {worker_count} workers...")
        for worker in self.workers:
            worker.stop()
        
        debug_logger.info(f"Waiting for {worker_count} workers to finish (timeout: {join_timeout}s each)...")
        start_time = time.perf_counter()
        
        for worker in self.workers:
            try:
                worker.join(timeout=join_timeout)
                if worker.is_alive():
                    debug_logger.warning(f"Worker {worker.name} did not exit cleanly within {join_timeout}s")
                else:
                    debug_logger.debug(f"Worker {worker.name} exited cleanly")
            except Exception as e:
                debug_logger.error(f"Error joining worker {worker.name}: {e}", exc_info=debug)
        
        elapsed = time.perf_counter() - start_time
        debug_logger.info(f"Worker shutdown completed in {elapsed:.2f}s")
        self._shutdown_complete.set()
    
    def wait_completion(self, timeout: Optional[float] = None) -> bool:
        self.task_queue.join()
        return True
    
    def wait_for_workers_to_finish(self, timeout: Optional[float] = None) -> bool:
        if timeout is None:
            timeout = 30.0
        start_time = time.perf_counter()
        self.task_queue.join()
        remaining_timeout = timeout - (time.perf_counter() - start_time)
        if remaining_timeout <= 0:
            return False
        for worker in self.workers:
            worker.join(timeout=remaining_timeout)
        return True
    
    def shutdown(self, wait: bool = True, timeout: Optional[float] = None) -> bool:
        debug_logger.info("Shutting down TaskManager")
        self.stop_event.set()
        
        if wait:
            self.task_queue.join()
            
        self._shutdown_workers()
            
        if self.monitor_thread:
            self.monitor_thread.join(self.worker_timeout)
            
        return True
    
    def reset_for_new_file(self) -> None:
        self.task_queue.join()
        # after join() returns, the queue is empty and workers are idle,
        # ready for the next add_tasks()
    
    def is_ready_for_new_tasks(self) -> bool:
        return self.task_queue.empty()
    
    def get_stats(self) -> dict:
        return {
            "active_workers": len([w for w in self.workers if w.is_alive()]),
            "total_workers": len(self.workers),
            "queue_size": self.task_queue.qsize(),
            "tasks_added": self._tasks_added
        }
    
    