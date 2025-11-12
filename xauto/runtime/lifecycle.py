#!/usr/bin/env python3

from xauto.utils.logging import debug_logger, monitor_details
from xauto.utils.config import Config
from xauto.runtime.task_manager import TaskManager, SafeThread
from xauto.utils.setup import get_options
from xauto.utils.common import status_monitor
from xauto.runtime.shutdown_helpers import shutdown_component_with_timeout
from xauto.internal.geckodriver.driver import get_driver_pool
from xauto.internal.memory import pressure_monitor_loop, cleanup_memory_monitor
from xauto.internal.thread_safe import AtomicCounter, ThreadSafeDict

from typing import Callable, Optional, Any, Tuple, Union
import threading
import time

_thread_state = ThreadSafeDict()
stop = threading.Event()
runtime_state = ThreadSafeDict()

def is_thread_healthy(thread_key: str) -> bool:
    thread = _thread_state.get(thread_key)
    if thread is None:
        return False
    return thread.is_alive()

def start_thread_if_needed(thread_key: str, target_fn: Callable, *args, **kwargs) -> bool:
    if not is_thread_healthy(thread_key):
        thread = SafeThread(
            target_fn=target_fn,
            **kwargs
        )
        thread.start()
        _thread_state[thread_key] = thread
        debug_logger.info(f"Started {thread_key}")
        return True
    else:
        debug_logger.info(f"{thread_key} already running")
        return False

def force_kill_thread(thread_key: str) -> None:
    thread = _thread_state.get(thread_key)
    if thread and thread.is_alive():
        try:
            thread.join(timeout=1.0)
            if thread.is_alive():
                debug_logger.warning(f"Force killing {thread_key}")
        except Exception as e:
            debug_logger.error(f"Error killing {thread_key}: {e}")
        finally:
            _thread_state[thread_key] = None

def get_worker_limits() -> Tuple[Union[int, float], int]:
    driver_limit = Config.get("system.driver_limit")

    if str(driver_limit).lower() == "auto":
        debug_logger.info("Driver pool configured with driver_limit set to auto (unlimited scaling)")
        return float('inf'), 100

    limit = int(driver_limit or 1)
    debug_logger.info(f"Driver pool configured with driver_limit = {driver_limit}")
    return limit, limit

def setup_runtime(task_processor: Callable) -> Tuple[TaskManager, Any]:
    options = get_options()
    driver_pool_max_size, max_workers = get_worker_limits()
    
    monitor_details.info(f"[SETUP_RUNTIME] (driver_pool_max_size={driver_pool_max_size}, max_workers={max_workers})")
    
    driver_pool = get_driver_pool(
        max_size=driver_pool_max_size,
        firefox_options=options
    )
    
    task_manager = TaskManager(
        driver_pool=driver_pool,
        task_processor=task_processor,
        max_workers=max_workers,
    )
    task_manager.start()
    
    runtime_state['start_time'] = time.perf_counter()
    runtime_state['outcomes'] =     {
        'completed': AtomicCounter(),
        'successful': AtomicCounter(),
        'failed': AtomicCounter(),
        'invalid': AtomicCounter()
    }
    runtime_state['tasks'] = []
    
    start_thread_if_needed(
        'resource_thread',
        pressure_monitor_loop,
        driver_pool=driver_pool, 
        stop_event=stop
    )
    
    start_thread_if_needed(
        'status_thread',
        status_monitor,
        driver_pool=driver_pool,
        stop_event=stop, 
    )

    return task_manager, driver_pool

def teardown_runtime(task_manager: Optional[TaskManager], driver_pool: Optional[Any]) -> None:
    shutdown_timeout = Config.get("misc.timeouts.program_shutdown_timeout")
    
    debug_logger.info(f"Starting runtime teardown (timeout: {shutdown_timeout}s)")
    
    stop.set()
    
    shutdown_threads = []
    
    def _start_shutdown_thread(component, display_name, thread_name, timeout, action="shutdown"):
        def _target():
            debug_logger.info(f"{display_name} shutdown thread started")
            shutdown_component_with_timeout(component, display_name, timeout, action)
            debug_logger.info(f"{display_name} shutdown thread completed")

        t = SafeThread(target_fn=_target, name=thread_name)
        shutdown_threads.append(t)
        t.start()
        return t

    _start_shutdown_thread(driver_pool, "DriverPool", "DriverPoolShutdown", shutdown_timeout)
    _start_shutdown_thread(task_manager, "TaskManager", "TaskManagerShutdown", shutdown_timeout)

    debug_logger.info("Stopping background threads...")
    force_kill_thread("resource_thread")
    force_kill_thread("status_thread")

    cleanup_memory_monitor()
    
    debug_logger.info(f"Waiting for {len(shutdown_threads)} shutdown threads...")
    for thread in shutdown_threads:
        thread.join(timeout=shutdown_timeout)
    
    _thread_state.clear()
    debug_logger.info("Runtime teardown completed")

    