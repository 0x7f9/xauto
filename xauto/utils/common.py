#!/usr/bin/env python3

from xauto.utils.config import Config
from xauto.utils.setup import debug
from xauto.utils.logging import debug_logger

import os
import time
import sys
import select

DEBUG_LOGS_DIR = "xauto/debug_logs"

def clear_debug_files():
    try:
        debug_files = [
            os.path.join(DEBUG_LOGS_DIR, "monitor_details.log"),
            os.path.join(DEBUG_LOGS_DIR, "debug.log"),
            os.path.join(DEBUG_LOGS_DIR, "debug_bot_detection.log")
        ]
        
        for debug_file in debug_files:
            if os.path.exists(debug_file):
                os.remove(debug_file)

    except Exception as e:
        debug_logger.error(f"Error deleting debug files: {e}")
        if debug:
            import traceback
            traceback.print_exc()

def status_print(start_time=None, tasks=None, outcomes=None):
    try:
        if start_time is None or outcomes is None:
            return
            
        runtime = time.perf_counter() - start_time
        task_count = len(tasks) if tasks is not None else 0
        
        completed_count = int(outcomes['completed']) if 'completed' in outcomes else 0
        print(f"\nRuntime: {runtime:.1f}s")
        print(f"Completed: {completed_count} out of {task_count} tasks")
        print(f"Successful tasks: {int(outcomes['successful']) if 'successful' in outcomes else 0}")
        print(f"Failed tasks: {int(outcomes['failed']) if 'failed' in outcomes else 0}")
        print(f"Invalid pages: {int(outcomes['invalid']) if 'invalid' in outcomes else 0}")
        
    except Exception as e:
        debug_logger.error(f"Error in status_print: {e}")
        if debug:
            import traceback
            traceback.print_exc()

def runtime_status(start_time=None, tasks=None, outcomes=None, driver_pool=None):
    try:
        if start_time is None or outcomes is None:
            return
            
        runtime = time.perf_counter() - start_time
        
        task_count = len(tasks) if tasks is not None else 0
        
        inuse = 0
        pool_max = 0
        if driver_pool is not None:
            inuse = driver_pool.drivers_inuse
            pool_max = driver_pool.max_size

        logline = f"[STAT]{runtime:5.1f}s | Tasks {outcomes['completed'].get()}/{task_count}"

        if inuse > 0:
            logline += f" | Drivers {inuse}/{pool_max}"

        try:
            from xauto.internal.memory import get_memory_monitor
            memory_monitor = get_memory_monitor()
            if memory_monitor:
                stats = memory_monitor.get_resource_stats()
                logline += f" | Mem {stats.memory:.1f}% | CPU {stats.cpu:.1f}%"
            else:
                logline += " | Mem 0.0% | CPU 0.0%"
        except ImportError:
            logline += " | Mem 0.0% | CPU 0.0%"

        print(logline)
        
    except Exception as e:
        debug_logger.error(f"Error in runtime_status: {e}")
        if debug:
            import traceback
            traceback.print_exc()

def status_monitor(driver_pool, stop_event):
    from xauto.runtime.lifecycle import runtime_state

    start_time = runtime_state['start_time']
    tasks = runtime_state['tasks']
    outcomes = runtime_state['outcomes']
    
    while not stop_event.is_set():
        rlist, _, _ = select.select([sys.stdin], [], [], 0.1)
        
        if not rlist and Config.get("misc.logging.status_console"):
            continue

        line = sys.stdin.readline().strip()
        if line == '':
            runtime_status(start_time, tasks, outcomes, driver_pool)

