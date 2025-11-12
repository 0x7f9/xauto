#!/usr/bin/env python3

from xauto.runtime.worker import Worker
from xauto.internal.dataclasses import TaskWrapper
from xauto.internal.geckodriver.driver import DriverPool
from xauto.internal.thread_safe import AtomicCounter, ThreadSafeList, SafeThread
from xauto.utils.logging import debug_logger, monitor_details
from xauto.utils.config import Config
from xauto.utils.setup import debug

from typing import Optional, Callable
import threading
import queue
import time

class TaskManager:
    __slots__ = (
        'driver_pool', 'task_processor', 'task_queue', 'tasks', 'config', 'max_workers', 
        'worker_timeout', '_workers', '_stop_event', 'monitor_thread', '_stats_lock', 
        '_monitor_interval', 'step_up', 'step_down', '_tasks_added', '_workers_lock',
        'scale_down_cooldown', 'scale_downs_this_cycle', 'last_scale_down_time'
    )
    
    def __init__(
            self, 
            driver_pool: DriverPool, 
            task_processor: Callable, 
            max_workers: Optional[int] = None, 
    ):
        
        if max_workers is None:
            debug_logger.warning("No worker limit set in TaskManager")
            return
        
        self.driver_pool = driver_pool
        self.task_processor = task_processor
        self.max_workers = max_workers

        self._monitor_interval = Config.get("misc.thread_monitoring.worker_monitor_loop_interval")
        self.worker_timeout = Config.get("misc.timeouts.stop_worker_timeout")
        
        autoscaling = Config.get("resources.driver_autoscaling")
        self.step_up = autoscaling.get("step_up")
        self.step_down = autoscaling.get("step_down")
        self.scale_down_cooldown = autoscaling.get("scale_down_cooldown")

        self._stats_lock = threading.Lock()
        self.scale_downs_this_cycle = AtomicCounter()
        self.last_scale_down_time = 0.0

        self.task_queue = queue.Queue()
        self._workers = ThreadSafeList()
        self._stop_event = threading.Event()
        self._tasks_added = 0
        self.monitor_thread = None

    def add_task(self, idx: int, task: list) -> None:
        if not task:
            return
        self.task_queue.put(TaskWrapper(idx=idx, tasks=task))
        self._tasks_added += 1

    def add_tasks(self, tasks: list) -> None:
        for idx, _ in enumerate(tasks):
            self.add_task(idx, tasks)
    
    def wait_completion(self):
        self.task_queue.join()
        return
    
    def start(self, initial_workers: Optional[int] = None) -> None:
        if len(self._workers) > 0:
            debug_logger.warning("TaskManager already started, ignoring start request")
            return
        
        workers = initial_workers or 1
        num_workers = min(workers, self.max_workers)

        if num_workers == 0:
            return
        
        debug_logger.info(f"Starting TaskManager with {num_workers} workers")
        self._spawn_workers(num_workers)
        
        self.monitor_thread = SafeThread(
            target_fn=self._monitor_loop,
            name="TaskManagerMonitor"
        )
        self.monitor_thread.start()
    
    def shutdown(self, wait: bool = True) -> bool:
        debug_logger.info("Shutting down TaskManager")
        self._stop_event.set()
        
        if wait:
            self.task_queue.join()
            
        self._stop_all_workers()
            
        if self.monitor_thread and self.monitor_thread.is_alive():
            self.monitor_thread.join(self.worker_timeout)
            
        return True
    
    def get_stats(self) -> dict:
        return {
            "active_workers": len([w for w in self._workers if w.is_alive()]),
            "total_workers": len(self._workers),
            "queue_size": self.task_queue.qsize(),
            "tasks_added": self._tasks_added
        }
    
    def _create_worker(self, name: str) -> Worker:
        return Worker(
            task_queue=self.task_queue,
            driver_pool=self.driver_pool,
            manager=self,
            name=name
        )
    
    def _spawn_workers(self, n: int) -> None:
        if not self.driver_pool.can_create_driver():
            return
        
        base = len(self._workers)
        for i in range(n):
            w = self._create_worker(f"Worker-{base + i}")
            self._workers.append(w)
            w.start()
        time.sleep(0.1)

    def _monitor_loop(self) -> None:
        while not self._stop_event.is_set():
            self._stop_event.wait(self._monitor_interval)
            if self._stop_event.is_set():
                break

            try:
                self._remove_dead_workers()
                self._maybe_scale_up()
                # self._maybe_scale_down()
            except Exception as e:
                debug_logger.error(f"[MONITOR_WORKERS_THREAD] runtime {e}", exc_info=True)
    
    def _remove_dead_workers(self) -> None:
        now = time.monotonic()
        alive = []
        dead = 0

        for w in self._workers:
            if w.is_alive():
                alive.append(w)
                continue 

            age = now - w._start_time
            if age > 2.0:
                dead += 1
                debug_logger.warning(
                    f"Worker {w.name} died after {age:.1f}s "
                    f"exit_reason: {w._exit_reason}, scheduling replacement"
                )
            else:
                debug_logger.warning(
                    f"Worker {w.name} died during startup "
                    f"(age: {age:.1f}s)"
                )

        self._workers.clear()
        for w in alive:
            self._workers.append(w)

        if dead > 0:
            try:
                debug_logger.info(f"Replacing {dead} dead workers")
                self._spawn_workers(dead)
            except Exception as e:
                debug_logger.error(f"Failed to replace dead workers: {e}", exc_info=True)
    
    def _maybe_scale_up(self) -> None:
        if len(self._workers) >= self.max_workers:
            return
        
        if self.task_queue.empty():
            return

        if not self.driver_pool.can_create_driver():
            # monitor_details.debug("[SCALE_UP] blocked: cannot create new driver (high_load or budget)")
            return
    
        add = min(self.step_up, self.max_workers - len(self._workers))
        if add <= 0:
            return
        
        monitor_details.info(
            f"[SCALE_UP] current_workers={len(self._workers)}, "
            f"drivers_inuse={self.driver_pool.drivers_inuse}, try adding={add}"
        )
        self._spawn_workers(add)

    def _maybe_scale_down(self) -> None:
        # will only scale down idle workers that are not 
        # holding a ._current_task flag given from Worker.run()
        if self.task_queue.qsize() > 0:
            return
        
        if self.driver_pool:
            self.driver_pool.cleanup_idle_drivers()
            
        idle_workers = [
            w for w in self._workers
            if w.is_alive() and w._current_task is None
        ]

        remove = min(self.step_down, len(idle_workers))
        if remove == 0:
            return
        
        monitor_details.info(
            f"[SCALE_DOWN] current={len(self._workers)}, "
            f"drivers_inuse={self.driver_pool.drivers_inuse}, removing={remove}"
        )

        for w in idle_workers[:remove]:
            w.stop()
            
        keep = []
        removed = 0
        for w in self._workers:
            if removed < remove and w in idle_workers:
                removed += 1         
                continue
            keep.append(w)

        self._workers.clear()
        for w in keep:
            self._workers.append(w)

    def _stop_all_workers(self) -> None:
        debug_logger.info(f"Stopping {len(self._workers)} workers...")
        timeout = Config.get("misc.timeouts.stop_all_workers_timeout")

        for w in self._workers:
            w.stop()
        
        start = time.perf_counter()
        for w in self._workers:
            try:
                w.join(timeout=timeout)
                if w.is_alive():
                    debug_logger.warning(f"Worker {w.name} did not exit cleanly within {timeout}s")
                else:
                    debug_logger.debug(f"Worker {w.name} exited cleanly")
            except Exception as e:
                debug_logger.error(f"Error joining worker {w.name}: {e}", exc_info=debug)
        
        elapsed = time.perf_counter() - start
        debug_logger.info(f"Worker shutdown completed in {elapsed:.2f}s")
    
    def _allow_driver_destroy_under_pressure(self, worker: Worker) -> bool:
        now = time.monotonic()
        
        with self._stats_lock:
            if now - self.last_scale_down_time >= self.scale_down_cooldown:
                self.scale_downs_this_cycle.reset()
                self.driver_pool.high_load_count.reset()
        
            if now - self.last_scale_down_time < self.scale_down_cooldown:
                return False
            
            if self.scale_downs_this_cycle.get() >= self.step_down:
                return False

            self.scale_downs_this_cycle.increment()
            self.last_scale_down_time = now

        monitor_details.info(
            f"[DESTROY_DRIVER] {worker.name} reason - under pressure "
            f"scale downs [{self.scale_downs_this_cycle.get()}/{self.step_down}]"
        )
        return True
    
