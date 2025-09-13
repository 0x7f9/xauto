#!/usr/bin/env python3

from xauto.utils.config import Config
from xauto.utils.setup import debug
from xauto.utils.logging import debug_logger

import os
import time
import sys
import select
import threading

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
        print(f"Runtime: {runtime:.1f}s")
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
        if start_time is None:
            return
            
        runtime = time.perf_counter() - start_time
        
        task_count = len(tasks) if tasks is not None else 0
        
        pool_size = 0
        pool_max = 0
        if driver_pool is not None:
            pool_size = driver_pool.return_driver_size()
            pool_max = driver_pool.max_size
            
        logline = f"{runtime:.1f}s | T:{int(outcomes['completed'])}/{task_count}" if outcomes else f"{runtime:.1f}s"
        
        if pool_size > 0:
            logline += f" | D:{pool_size}/{pool_max}"
            
        try:
            from xauto.internal.memory import get_memory_monitor
            memory_monitor = get_memory_monitor()
            if memory_monitor:
                stats = memory_monitor.get_resource_stats()
                logline += f" | M:{stats.memory:.1f}% | C:{stats.cpu:.1f}%"
            else:
                logline += " | M:0.0% | C:0.0%"
        except ImportError:
            logline += " | M:0.0% | C:0.0%"

        print(f"[STAT] {logline}")
        
    except Exception as e:
        debug_logger.error(f"Error in runtime_status: {e}")
        if debug:
            import traceback
            traceback.print_exc()

def status_monitor(stop_event=None, start_time=None, tasks=None, outcomes=None, driver_pool=None):
    if stop_event is None:
        stop_event = globals().get('stop', threading.Event())
    
    log_counter = 0
        
    while not stop_event.is_set():
        rlist, _, _ = select.select([sys.stdin], [], [], 0.1)
        
        log_counter = (log_counter + 1) % Config.get("misc.logging.interval")
        
        if rlist:
            line = sys.stdin.readline().strip()
            if line == '':
                runtime_status(start_time, tasks, outcomes, driver_pool)
        elif log_counter == 0 and Config.get("misc.logging.status_console"):
            runtime_status(start_time, tasks, outcomes, driver_pool)

