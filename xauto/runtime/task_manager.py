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
        'driver_pool', 'task_processor', 'task_queue', 'creds', 'config', 'max_workers', 
        'worker_timeout', 'workers', 'stop_event', '_monitor_thread', '_shutdown_complete', 
        '_stats_lock', 'monitor_interval', 'scale_up_step', 'scale_down_step',
        '_last_driver_creation_failure', '_consecutive_driver_failures',
        'scale_down_cooldown', 'last_scale_down_time', '_scale_downs_this_cycle',
        '_tasks_added'
    )
    
    def __init__(self, driver_pool: DriverPool, task_processor: Callable, 
                 max_workers: Optional[int] = None, task_queue: Optional[queue.Queue] = None,
                 creds: Optional[list] = None):
        self.driver_pool = driver_pool
        self.task_processor = task_processor
        self.task_queue = task_queue or queue.Queue()
        self.creds = creds
        if max_workers is not None:
            self.max_workers = max_workers
        else:
            self.max_workers = 4
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
        self._monitor_thread = None
        self._shutdown_complete = threading.Event()
        self._stats_lock = threading.Lock()
        self._last_driver_creation_failure = 0.0
        self._consecutive_driver_failures = 0
        self._tasks_added = 0

    def _create_worker(self, name: str) -> Worker:
        return Worker(
            task_queue=self.task_queue,
            driver_pool=self.driver_pool,
            per_task_fn=self._task_wrapper,
            manager=self,
            name=name
        )
    
    def _can_create_workers(self) -> bool:
        return self.driver_pool.can_create_driver()
    
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
        self._monitor_thread = SafeThread(
            target_fn=self._monitor_workers,
            name="TaskManagerMonitor"
        )
        self._monitor_thread.start()
        if num_workers > 0:
            can_create_drivers = self._can_create_workers()
            if not can_create_drivers:
                debug_logger.warning(f"Cannot create drivers, starting with 0 workers instead of {num_workers}")
                monitor_details.debug(f"[TASK_MANAGER] start_blocked: requested_workers={num_workers}, can_create_drivers={can_create_drivers}")
                num_workers = 0
            for i in range(num_workers):
                worker = self._create_worker(f"Worker-{i}")
                self.workers.append(worker)
                worker.start()
            time.sleep(0.1)

    def _task_wrapper(self, task: Any, driver: Any) -> None:
        if self.creds is not None:
            self.task_processor(task, driver, self.creds)
        else:
            self.task_processor(task, driver)
    
    def _monitor_workers(self) -> None:
        while not self.stop_event.is_set():
            self._check_worker_health()
            if self.stop_event.wait(timeout=self.monitor_interval):
                break
    
    def _check_worker_health(self) -> None:
        dead_count = 0
        current_time = time.monotonic()
        live_workers = []
        for worker in self.workers:
            if worker.is_alive():
                live_workers.append(worker)
            else:
                exit_reason = getattr(worker, '_exit_reason', 'unknown')
                if exit_reason == 'normal':
                    debug_logger.debug(f"Removing worker {worker.name} that exited normally")
                else:
                    worker_age = current_time - getattr(worker, '_start_time', current_time)
                    if worker_age > 2.0:
                        dead_count += 1
                        debug_logger.warning(f"Worker {worker.name} is dead (exit_reason: {exit_reason}), will replace")
                    else:
                        debug_logger.debug(f"Worker {worker.name} appears dead but is still in startup phase (age: {worker_age:.1f}s)")
        
        self.workers.clear()
        for worker in live_workers:
            self.workers.append(worker)
        if dead_count > 0:
            debug_logger.info(f"Replacing {dead_count} dead workers")
            self._replace_dead_workers(dead_count)
        if not self.stop_event.is_set():
            self._scale_workers_if_needed()
    
    def _replace_dead_workers(self, dead_count: int) -> None:
        if not self.stop_event.is_set():
            can_create_drivers = self._can_create_workers()
            if not can_create_drivers:
                debug_logger.warning(f"Cannot create drivers, skipping replacement of {dead_count} dead workers")
                monitor_details.debug(f"[TASK_MANAGER] replace_blocked: dead_count={dead_count}, can_create_drivers={can_create_drivers}")
                return
            
            for i in range(dead_count):
                worker = self._create_worker(f"Worker-Replacement-{i}")
                self.workers.append(worker)
                worker.start()
            time.sleep(0.1)
    
    def _scale_workers_if_needed(self) -> None:
        current_workers = len(self.workers)
        qsize = self.task_queue.qsize
        queue_size = qsize()
        
        get_active = self.driver_pool.get_active_count
        current_drivers = get_active()
        
        get_pool_stats = self.driver_pool.get_pool_stats
        pool_stats = get_pool_stats()
        
        can_create = self._can_create_workers
        can_create_drivers = can_create()
        
        monotonic = time.monotonic
        current_time = monotonic()
        
        if not can_create_drivers:
            if current_time - self._last_driver_creation_failure > 10.0:
                self._consecutive_driver_failures = 1
            else:
                self._consecutive_driver_failures += 1
            self._last_driver_creation_failure = current_time
        else:
            self._consecutive_driver_failures = 0
            
        available_driver_slots = self.driver_pool.max_size - current_drivers if self.driver_pool.max_size != float('inf') else float('inf')
        max_workers_without_drivers = min(10, self.max_workers // 4)
        should_limit_workers = (
            not can_create_drivers and 
            self._consecutive_driver_failures >= 3 and 
            current_workers >= max_workers_without_drivers
        )

        if not can_create_drivers and self._consecutive_driver_failures >= 1:
            should_limit_workers = True
            
        monitor_details.debug(f"[TASK_MANAGER] scaling_check: workers={current_workers}/{self.max_workers}, queue={queue_size}, drivers_active={current_drivers}, drivers_available={available_driver_slots}, can_create_drivers={can_create_drivers}, consecutive_failures={self._consecutive_driver_failures}, should_limit_workers={should_limit_workers}")
        monitor_details.debug(f"[TASK_MANAGER] pool_stats: {pool_stats}")
        
        if queue_size > 0 and current_workers < self.max_workers and available_driver_slots > 0 and can_create_drivers and not should_limit_workers:
            if available_driver_slots == float('inf'):
                workers_to_add = min(self.scale_up_step, self.max_workers - current_workers)
            else:
                workers_to_add = min(self.scale_up_step, self.max_workers - current_workers, int(available_driver_slots))
            
            if workers_to_add > 0:
                debug_logger.info(f"Worker scale-up triggered: current={current_workers}, queue={queue_size}, adding={workers_to_add}")
                monitor_details.debug(f"[TASK_MANAGER] scale_up START: current_workers={current_workers}, queue_size={queue_size}, adding={workers_to_add}, available_driver_slots={available_driver_slots}, can_create_drivers={can_create_drivers}")
                
                for i in range(workers_to_add):
                    worker = self._create_worker(f"Worker-ScaleUp-{i}")
                    self.workers.append(worker)
                    worker.start()
                
                time.sleep(0.1)
                new_workers = len(self.workers)
                new_drivers = get_active()
                monitor_details.debug(f"[TASK_MANAGER] scale_up END: workers={new_workers}, drivers_active={new_drivers}")
        
        elif queue_size > 0 and current_workers < self.max_workers and (available_driver_slots <= 0 or not can_create_drivers):
            reason = "no_driver_capacity" if available_driver_slots <= 0 else "spawn_blocked_or_budget_exhausted"
            debug_logger.debug(f"Queue backing up but cannot create drivers: queue_size={queue_size}, current_workers={current_workers}, current_drivers={current_drivers}, max_drivers={self.driver_pool.max_size}, reason={reason}")
            monitor_details.debug(f"[TASK_MANAGER] scale_up_blocked: queue_size={queue_size}, current_workers={current_workers}, current_drivers={current_drivers}, max_drivers={self.driver_pool.max_size}, reason={reason}, spawn_blocked={getattr(self.driver_pool, '_spawn_blocked', False)}, budget_remaining={pool_stats.get('spawn_budget_remaining', 0)}")
            
        if queue_size < current_workers // 2 and current_workers > 1:
            workers_to_remove = min(self.scale_down_step, current_workers // 2)
            
            if workers_to_remove > 0:
                debug_logger.info(f"Scaling down workers: queue_size={queue_size}, current_workers={current_workers}, removing={workers_to_remove}")
                monitor_details.debug(f"[TASK_MANAGER] scale_down START: queue_size={queue_size}, current_workers={current_workers}, removing={workers_to_remove}")
                debug_logger.debug(f"CHECKPOINT: scaling down workers (current={current_workers}, target={current_workers - workers_to_remove})")
                all_workers_list = list(self.workers)
                workers_to_stop = all_workers_list[-workers_to_remove:]
                
                for worker in workers_to_stop:
                    worker.stop()
                self.workers.clear()
                
                for worker in all_workers_list[:-workers_to_remove]:
                    self.workers.append(worker)
                
                try:
                    if self.driver_pool.scale_down(workers_to_remove):
                        debug_logger.info(f"Successfully scaled down driver pool by {workers_to_remove} drivers")
                        monitor_details.debug(f"[TASK_MANAGER] driver_scale_down_success: removed={workers_to_remove}")
                    else:
                        debug_logger.warning(f"Failed to scale down driver pool")
                        monitor_details.debug(f"[TASK_MANAGER] driver_scale_down_failed: attempted={workers_to_remove}")
                
                except Exception as e:
                    debug_logger.error(f"Error scaling down driver pool: {e}")
                    monitor_details.debug(f"[TASK_MANAGER] driver_scale_down_error: {e}")
                    
                new_workers = len(self.workers)
                new_drivers = get_active()
                monitor_details.debug(f"[TASK_MANAGER] scale_down END: workers={new_workers}, drivers_active={new_drivers}")
        else:
            if queue_size > 0 and current_workers < self.max_workers:
                reason = "no_driver_capacity" if available_driver_slots <= 0 else "spawn_blocked_or_budget_exhausted" if not can_create_drivers else "unknown"
                monitor_details.debug(f"[TASK_MANAGER] no_scale_up: queue_size={queue_size}, current_workers={current_workers}, max_workers={self.max_workers}, available_driver_slots={available_driver_slots}, can_create_drivers={can_create_drivers}, reason={reason}")
            elif queue_size < current_workers // 2 and current_workers > 1:
                monitor_details.debug(f"[TASK_MANAGER] no_scale_down: queue_size={queue_size}, current_workers={current_workers}")
            else:
                monitor_details.debug(f"[TASK_MANAGER] no_scaling_needed: queue_size={queue_size}, current_workers={current_workers}")
    
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
            
        if self._monitor_thread:
            self._monitor_thread.join(self.worker_timeout)
            
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