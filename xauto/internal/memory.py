#!/usr/bin/env python3

from xauto.internal.thread_safe import ThreadSafeList
from xauto.utils.logging import debug_logger, monitor_details
from xauto.utils.config import Config
from xauto.utils.setup import debug
from xauto.internal.dataclasses import ResourceStats
from xauto.utils.utility import open_file_ro, LogTimer

from typing import Any, Optional, Tuple
import threading
import time
import os

_memory_monitor: Optional["MemoryMonitor"] = None
_memory_monitor_lock = threading.RLock()
_meminfo_fd = None
_stat_fd = None
_fd_lock = threading.RLock()
_meminfo_buf = bytearray(4096)
_stat_buf = bytearray(1024)

def _get_meminfo_fd():
    global _meminfo_fd
    with _fd_lock:
        if _meminfo_fd is None:
            try:
                _meminfo_fd = open_file_ro("/proc/meminfo")
            except OSError:
                _meminfo_fd = None
        return _meminfo_fd

def _get_stat_fd():
    global _stat_fd
    with _fd_lock:
        if _stat_fd is None:
            try:
                _stat_fd = open_file_ro("/proc/stat")
            except OSError:
                _stat_fd = None
        return _stat_fd

def _cleanup_fds():
    global _meminfo_fd, _stat_fd
    with _fd_lock:
        if _meminfo_fd is not None:
            try:
                os.close(_meminfo_fd)
            except OSError:
                pass
            _meminfo_fd = None
        if _stat_fd is not None:
            try:
                os.close(_stat_fd)
            except OSError:
                pass
            _stat_fd = None

def get_memory_monitor(reset=False):
    global _memory_monitor
    
    with _memory_monitor_lock:
        if reset or _memory_monitor is None:
            if _memory_monitor is not None:
                _memory_monitor.cleanup()
            _memory_monitor = MemoryMonitor()
        return _memory_monitor

def cleanup_memory_monitor():
    global _memory_monitor
    
    with _memory_monitor_lock:
        if _memory_monitor is not None:
            _memory_monitor.cleanup()
            _memory_monitor = None
    _cleanup_fds()

def _read_memory_percent() -> float:
    fd = _get_meminfo_fd()
    if fd is None:
        return 0.0
    
    try:
        os.lseek(fd, 0, os.SEEK_SET)
        data = os.read(fd, len(_meminfo_buf))
        if not data:
            return 0.0

        lines = data.decode("utf-8").splitlines()
        meminfo = {}
        for line in lines:
            if ':' not in line:
                continue
            key, val = line.split(':', 1)
            key = key.strip()
            try:
                meminfo[key] = int(val.strip().split()[0])
            except (ValueError, IndexError):
                continue

        total = meminfo.get("MemTotal", 0)
        free = (
            meminfo.get("MemFree", 0) +
            meminfo.get("Buffers", 0) +
            meminfo.get("Cached", 0) +
            meminfo.get("SReclaimable", 0) -
            meminfo.get("Shmem", 0)
        )
        used = total - free
        return (used / total) * 100.0 if total else 0.0
    except Exception:
        return 0.0

def _read_cpu_times() -> Tuple[int, ...]:
    fd = _get_stat_fd()
    if fd is None:
        return (0, 0, 0, 0, 0, 0, 0, 0)
    
    try:
        os.lseek(fd, 0, os.SEEK_SET)
        data = os.read(fd, len(_stat_buf))
        if not data:
            return (0, 0, 0, 0, 0, 0, 0, 0)

        lines = data.decode('utf-8').split('\n')
        for line in lines:
            if line.startswith("cpu "):
                fields = line.split()[1:9]  
                if len(fields) == 8:
                    return tuple(map(int, fields))
                break
        return (0, 0, 0, 0, 0, 0, 0, 0)
    except Exception:
        return (0, 0, 0, 0, 0, 0, 0, 0)

def _calculate_cpu_percent(prev: Tuple[int, ...], curr: Tuple[int, ...]) -> float:
    if len(prev) < 8 or len(curr) < 8:
        return 0.0
    
    prev_idle = prev[3] + prev[4]  
    curr_idle = curr[3] + curr[4]  

    prev_total = sum(prev)
    curr_total = sum(curr)

    total_delta = curr_total - prev_total
    idle_delta = curr_idle - prev_idle

    if total_delta == 0:
        return 0.0
    return (1.0 - (idle_delta / total_delta)) * 100.0


class MemoryMonitor:
    __slots__ = (
        '_check_interval', '_max_history', '_state_lock', '_base_pos', '_base_neg',
        '_update_in_progress', '_history_memory', '_history_cpu', '_last_cpu_times', 
        '_dynamic_buffer', '_base_mem_threshold', '_base_cpu_threshold', '_last_check',
        '_last_high_load_change', '_spawn_buffer', '_high_load_state', '_avg_stats',
        '_last_stats', '_log_limiter', '_safe_margin'
    )
    
    def __init__(self):
        self._log_limiter = LogTimer() 

        pressure = Config.get("resources.memory_tuning.pressure")
        self._check_interval = pressure.get("system_check_interval")
        self._max_history = pressure.get("history")    
        self._base_mem_threshold = pressure.get("mem_threshold")
        self._base_cpu_threshold = pressure.get("cpu_threshold")
        self._safe_margin = pressure.get("safe_margin")

        buffer = Config.get("resources.memory_tuning.buffer")
        self._base_neg = buffer.get("down_margin")
        self._base_pos = buffer.get("up_margin")
        self._spawn_buffer = Config.get("resources.driver_autoscaling.spawn_buffer")

        self._history_memory = ThreadSafeList(max_size=self._max_history)
        self._history_cpu = ThreadSafeList(max_size=self._max_history)
        
        self._dynamic_buffer = DynamicBuffer()
        self._state_lock = threading.RLock()
        self._last_cpu_times = _read_cpu_times()
        self._last_stats = ResourceStats(0.0, 0.0)
        self._avg_stats = ResourceStats(0.0, 0.0)
        self._last_check = 0.0
        
        self._update_in_progress = False
        self._last_high_load_change = 0.0
        self._high_load_state = False

    def get_resource_stats(self) -> ResourceStats:
        if self._needs_update():
            self._update_stats()
        return self._last_stats
    
    def get_avg_stats(self) -> ResourceStats:
        if self._needs_update():
            self._update_stats()
        return self._avg_stats
    
    def cleanup(self):
        try:
            self._history_memory.clear()
            self._history_cpu.clear()
            with self._state_lock:
                self._last_cpu_times = (0, 0, 0, 0, 0, 0, 0, 0)
                self._last_stats = ResourceStats(0.0, 0.0)
                self._avg_stats = ResourceStats(0.0, 0.0)
        except Exception as e:
            debug_logger.error(f"[CLEANUP] {e}", exc_info=debug)

    def check_load(self, driver_pool=None):
        self._update_stats()

        cur_mem = self._last_stats.memory
        cur_cpu = self._last_stats.cpu
        avg_mem = self._avg_stats.memory
        avg_cpu = self._avg_stats.cpu
        base_mem = self._base_mem_threshold
        base_cpu = self._base_cpu_threshold

        down_margin, up_margin = self._dynamic_buffer(avg_mem, avg_cpu, self._base_neg, self._base_pos)
        
        if self._log_limiter.should_log():
            monitor_details.info(
                f"[CHECK_LOAD] cur_mem={cur_mem:.1f}%, "
                f"avg_mem={avg_mem:.1f}%, "
                f"cur_cpu={cur_cpu:.1f}%, "
                f"avg_cpu={avg_cpu:.1f}%"
            )
            monitor_details.info(
                f"[CHECK_LOAD] block at: "
                f"mem={base_mem + up_margin:.1f}%, "
                f"cpu={base_cpu + up_margin:.1f}% "
                f"up_margin={up_margin}"
            )
            monitor_details.info(
                f"[CHECK_LOAD] release at: "
                f"mem={base_mem - down_margin:.1f}%, "
                f"cpu={base_cpu - down_margin:.1f}% "
                f"down_margin={down_margin}"
            )

        near_threshold = any([
            avg_mem >= (base_mem - self._safe_margin),
            avg_cpu >= (base_cpu - self._safe_margin)
        ])

        spike_block = any([
            cur_mem > (base_mem + up_margin),
            cur_cpu > (base_cpu + up_margin)
        ])

        trend_block = any([
            avg_mem > (base_mem + up_margin),
            avg_cpu > (base_cpu + up_margin)
        ])

        release_ok = any([
            avg_mem <= (base_mem - down_margin),
            avg_cpu <= (base_cpu - down_margin)
        ])

        now = time.monotonic()
        since = now - self._last_high_load_change

        if self._high_load_state:
            high_load = spike_block or not release_ok
        else:
            high_load = spike_block and trend_block

        if since >= self._spawn_buffer:
            if self._high_load_state and not high_load:
                self._high_load_state = False
                self._last_high_load_change = now
                monitor_details.info(
                    f"[CHECK_LOAD] high_load = False (unblocked: avg_mem={avg_mem:.1f}%, avg_cpu={avg_cpu:.1f}%)"
                )
            elif not self._high_load_state and high_load:
                self._high_load_state = True
                self._last_high_load_change = now
                monitor_details.info(
                    f"[CHECK_LOAD] high_load = True (blocked: avg_mem={avg_mem:.1f}%, avg_cpu={avg_cpu:.1f}%)"
                )

        if driver_pool:
            driver_pool.set_consecutive_high_load(self._high_load_state)
            driver_pool.set_high_load(self._high_load_state)
            driver_pool.set_near_threshold(near_threshold)

        return self._high_load_state
    
    def _needs_update(self) -> bool:
        return time.monotonic() - self._last_check > self._check_interval
    
    def _update_stats(self):
        with self._state_lock:
            if self._update_in_progress:
                return
            
            self._update_in_progress = True
            try:
                memory_percent = _read_memory_percent()
                curr_cpu = _read_cpu_times()
                cpu_percent = _calculate_cpu_percent(self._last_cpu_times, curr_cpu)
                self._last_cpu_times = curr_cpu
                self._last_check = time.monotonic()
                
                self._history_memory.bounded_append(memory_percent, self._max_history)
                self._history_cpu.bounded_append(cpu_percent, self._max_history)

                self._avg_stats = ResourceStats(
                    self._history_memory.rolling_sum / len(self._history_memory),
                    self._history_cpu.rolling_sum / len(self._history_cpu)
                )

                self._last_stats = ResourceStats(memory_percent, cpu_percent)

            except Exception as e:
                debug_logger.error(f"[UPDATE_STATS] {e}", exc_info=debug)
            finally:
                self._update_in_progress = False


class DynamicBuffer:
    def __init__(self):
        self._negative_buffer = None
        self._positive_buffer = None
        self._last_buffer_adjust_time = 0.0
        self._scale_down_cooldown = Config.get("resources.driver_autoscaling.scale_down_cooldown", 5.0)

    def __call__(self, avg_mem, avg_cpu, base_buffer_negative, base_buffer_positive):
        if self._negative_buffer is None or self._positive_buffer is None:
            self._negative_buffer = base_buffer_negative
            self._positive_buffer = base_buffer_positive

        now = time.monotonic()
        if now - self._last_buffer_adjust_time < self._scale_down_cooldown:
            return self._negative_buffer, self._positive_buffer

        self._last_buffer_adjust_time = now
        buffer_cfg = Config.get("resources.memory_tuning.buffer")
        adjust_rate = buffer_cfg.get("adjust_rate", 2)

        if avg_mem > 80 and avg_cpu > 80:
            self._negative_buffer = min(1, self._negative_buffer + adjust_rate)  
            self._positive_buffer = min(8, self._positive_buffer + adjust_rate)
        elif avg_mem > 70 or avg_cpu > 70:
            self._negative_buffer = max(2, self._negative_buffer - 1)
            self._positive_buffer = min(10, self._positive_buffer + adjust_rate)
        elif avg_mem < 55 and avg_cpu < 55:
            self._negative_buffer = min(2, self._negative_buffer + adjust_rate)
            self._positive_buffer = max(2, self._positive_buffer - adjust_rate)

        return self._negative_buffer, self._positive_buffer


def pressure_monitor_loop(driver_pool, stop_event):
    check_interval = Config.get("resources.driver_autoscaling.scaling_check_interval")
    memory_monitor = get_memory_monitor()
    
    while not stop_event.is_set():
        try:
            memory_monitor.check_load(driver_pool)
        except Exception as e:
            debug_logger.error(f"[MONITOR_THREAD] Runtime error: {e}", exc_info=debug)
        stop_event.wait(timeout=check_interval)

def acquire_driver_with_pressure_check(driver_pool, context="unknown"):
    if driver_pool is None:
        debug_logger.error(f"[ACQUIRE_DRIVER] driver_pool is None in {context}")
        return None
    
    if driver_pool.is_high_load:
        debug_logger.warning(f"[ACQUIRE_DRIVER] blocked due to system pressure in {context}")
        wait_high_load(driver_pool, context=context, allow_timeout=False)
    
    try:
        driver = driver_pool.get_driver_with_injection(skip_high_load_wait=True)
        return driver
    except Exception as e:
        debug_logger.error(f"[ACQUIRE_DRIVER] {context}: {e}", exc_info=debug)
        return None
    
def wait_high_load(driver_pool: Any, context: str = "unknown", allow_timeout: bool = True) -> bool:
    block_cfg = Config.get("resources.memory_tuning.pressure_blocking")
    max_wait_time = block_cfg.get("max_wait_time")
    wait_chunk_time = block_cfg.get("wait_chunk_time")

    _log_limiter = LogTimer() 
    
    wait_start = time.monotonic()
    pool_stats = driver_pool.get_pool_stats()
    monitor_details.info(
        f"[HIGH_LOAD] START {context}, high_load={driver_pool.is_high_load}, pool_stats={pool_stats}"
    )
    
    while driver_pool.is_high_load:
        elapsed = time.monotonic() - wait_start
        remaining_total = max_wait_time - elapsed

        if _log_limiter.should_log():
            monitor_details.info(
                f"[HIGH_LOAD] blocking {elapsed:.1f}s in {context}"
            )

        if allow_timeout and remaining_total <= 0:
            break

        unblocked = driver_pool.wait_for_unblock(timeout=wait_chunk_time)
        if unblocked:
            break

    elapsed = time.monotonic() - wait_start
    pool_stats = driver_pool.get_pool_stats()
    monitor_details.info(
        f"[HIGH_LOAD] END {context}: blocked_for={elapsed:.1f}s, high_load={driver_pool.is_high_load}, pool_stats={pool_stats}"
    )

    return True

