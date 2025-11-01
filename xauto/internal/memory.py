#!/usr/bin/env python3

from xauto.internal.thread_safe import ThreadSafeList
from xauto.utils.logging import debug_logger, monitor_details
from xauto.utils.config import Config
from xauto.utils.setup import debug
from xauto.internal.dataclasses import ResourceStats
from xauto.utils.utility import open_file_ro

from typing import Any, Optional, Tuple
import threading
import time
import os
import random

class DriverSpawnBudget:
    def __init__(self, max_per_window: int = 10, window_size_sec: int = 60):
        self.max_per_window = max_per_window
        self.window_size_sec = window_size_sec
        self.spawn_count = 0
        self.window_start = time.monotonic()
        self.last_spawn_time = 0.0
        self._last_override_log = 0.0
        self._lock = threading.Lock()

    def can_spawn(self, driver_pool=None) -> bool:
        with self._lock:
            now = time.monotonic()

            if now - self.window_start > self.window_size_sec:
                self.spawn_count = 0
                self.window_start = now

            high_load = driver_pool.is_high_load if driver_pool else False

            if driver_pool and driver_pool.drivers_inuse >= driver_pool.max_size:
                monitor_details.info(f"[CAN_SPAWN] denied pool full ({driver_pool.drivers_inuse}/{driver_pool.max_size})")
                return False

            if self.spawn_count < self.max_per_window and not high_load:
                self.spawn_count += 1
                monitor_details.info(f"[CAN_SPAWN] allowed spawn_count={self.spawn_count}")
                return True

            # monitor_details.info(f"[CAN_SPAWN] denied high_load={high_load}, spawn_count={self.spawn_count}")
            return False
    
    def get_remaining(self, driver_pool=None) -> int:
        with self._lock:
            now = time.monotonic()
            if now - self.window_start > self.window_size_sec:
                return self.max_per_window
            
            if driver_pool and not driver_pool.is_high_load:
                return 999999
            
            return max(0, self.max_per_window - self.spawn_count)

    def get_time_until_reset(self) -> float:
        with self._lock:
            now = time.monotonic()
            time_elapsed = now - self.window_start
            return max(0, self.window_size_sec - time_elapsed)

_memory_monitor_instance = None
_instance_lock = threading.RLock()
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
    global _memory_monitor_instance
    
    with _instance_lock:
        if reset or _memory_monitor_instance is None:
            if _memory_monitor_instance is not None:
                _memory_monitor_instance.cleanup()
            _memory_monitor_instance = MemoryMonitor()
        
        return _memory_monitor_instance

def cleanup_memory_monitor():
    global _memory_monitor_instance
    
    with _instance_lock:
        if _memory_monitor_instance is not None:
            _memory_monitor_instance.cleanup()
            _memory_monitor_instance = None
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
        '_cache_duration', '_max_history', '_memory_threshold', '_cpu_threshold',
        '_last_check', '_cached_memory_percent', '_cached_cpu_percent', '_last_update_result',
        '_update_in_progress', '_history_memory', '_history_cpu', '_last_cpu_times', '_state_lock',
        '_last_high_load_change', '_spawn_hysteresis_time', '_high_load_state',
        '_histogram_memory', '_histogram_cpu', '_histogram_bins', '_last_cpu_times_set'
    )
    
    def __init__(self):
        pressure = Config.get("resources.memory_tuning.pressure")
        self._cache_duration = pressure.get("system_check_interval")
        self._max_history = pressure.get("history")
        self._memory_threshold = pressure.get("mem_threshold")
        self._cpu_threshold = pressure.get("cpu_threshold")
        
        driver_autoscaling = Config.get("resources.driver_autoscaling")
        spawn_buffer = driver_autoscaling.get("spawn_buffer")
        self._spawn_hysteresis_time = spawn_buffer

        self._state_lock = threading.RLock()

        self._last_check = 0.0
        self._cached_memory_percent = 0.0
        self._cached_cpu_percent = 0.0

        self._last_cpu_times = _read_cpu_times()
        self._last_cpu_times_set = False
        
        self._history_memory = ThreadSafeList()
        self._history_cpu = ThreadSafeList()
        
        self._histogram_bins = 20
        self._histogram_memory = [0] * self._histogram_bins
        self._histogram_cpu = [0] * self._histogram_bins
        
        self._update_in_progress = 0
        self._last_update_result = ResourceStats(0.0, 0.0)
        
        self._last_high_load_change = 0.0
        self._high_load_state = False

        init_mem = _read_memory_percent()
        init_cpu = 0.0  

        bin_width = 100.0 / self._histogram_bins
        mem_bin = min(int(init_mem // bin_width), self._histogram_bins - 1)
        cpu_bin = 0  

        self._histogram_memory[mem_bin] = 3
        self._histogram_cpu[cpu_bin] = 3

        self._cached_memory_percent = init_mem
        self._cached_cpu_percent = init_cpu

        monitor_details.info(
            f"[MemoryMonitor] started (initial hist: mem={init_mem:.1f}%, cpu={init_cpu:.1f}%)"
        )

    def _needs_update(self) -> bool:
        return time.monotonic() - self._last_check > self._cache_duration

    def _update_stats(self):
        with self._state_lock:
            if self._update_in_progress:
                return
            
            self._update_in_progress = True
            try:
                memory_percent = _read_memory_percent()
                curr_cpu = _read_cpu_times()

                if not self._last_cpu_times_set:
                    cpu_percent = 0.0
                    self._last_cpu_times_set = True
                else:
                    cpu_percent = _calculate_cpu_percent(self._last_cpu_times, curr_cpu)

                self._last_cpu_times = curr_cpu
                self._cached_memory_percent = memory_percent
                self._cached_cpu_percent = cpu_percent
                self._last_check = time.monotonic()

                self._history_memory.bounded_append(memory_percent, self._max_history)
                self._history_cpu.bounded_append(cpu_percent, self._max_history)
                
                bin_width = 100.0 / self._histogram_bins
                mem_bin = min(int(memory_percent // bin_width), self._histogram_bins - 1)
                cpu_bin = min(int(cpu_percent // bin_width), self._histogram_bins - 1)

                decay = 0.9 
                self._histogram_memory = [int(x * decay) for x in self._histogram_memory]
                self._histogram_cpu = [int(x * decay) for x in self._histogram_cpu]

                self._histogram_memory[mem_bin] += 1
                self._histogram_cpu[cpu_bin] += 1
                
                self._last_update_result = ResourceStats(memory_percent, cpu_percent)

            except Exception as e:
                debug_logger.error(f"[UPDATE_STATS] {e}", exc_info=debug)
            finally:
                self._update_in_progress = False
    
    def get_memory_percent(self) -> float:
        if self._needs_update():
            self._update_stats()
        return self._cached_memory_percent
    
    def get_cpu_percent(self) -> float:
        if self._needs_update():
            self._update_stats()
        return self._cached_cpu_percent
    
    def get_resource_stats(self) -> ResourceStats:
        if self._needs_update():
            self._update_stats()
        return self._last_update_result
    
    def is_under_memory_pressure(self, threshold: Optional[float] = None) -> bool:
        actual_threshold = threshold if threshold is not None else self._memory_threshold
        return self.get_memory_percent() > actual_threshold
    
    def is_under_cpu_pressure(self, threshold: Optional[float] = None) -> bool:
        actual_threshold = threshold if threshold is not None else self._cpu_threshold
        return self.get_cpu_percent() > actual_threshold
    
    def is_under_pressure(self, memory_threshold: Optional[float] = None, cpu_threshold: Optional[float] = None) -> bool:
        return (self.is_under_memory_pressure(memory_threshold) or 
                self.is_under_cpu_pressure(cpu_threshold))
    
    def reset(self):
        with self._state_lock:
            self._last_check = 0.0
            self._cached_memory_percent = 0.0
            self._cached_cpu_percent = 0.0
            self._last_cpu_times = _read_cpu_times()

        self._history_memory.clear()
        self._history_cpu.clear()
        
        self._histogram_memory = [0] * self._histogram_bins
        self._histogram_cpu = [0] * self._histogram_bins
    
    def cleanup(self):
        try:
            self._history_memory.clear()
            self._history_cpu.clear()
            with self._state_lock:
                self._cached_memory_percent = 0.0
                self._cached_cpu_percent = 0.0
                self._last_cpu_times = (0, 0, 0, 0, 0, 0, 0, 0)
                self._histogram_memory = [0] * self._histogram_bins
                self._histogram_cpu = [0] * self._histogram_bins
        except Exception as e:
            debug_logger.error(f"[CLEANUP] {e}", exc_info=debug)

    def check_load(self, driver_pool=None):
        if self._needs_update():
            self._update_stats()
        
        min_samples = 5
        ok = len(self._histogram_cpu) >= min_samples and len(self._histogram_memory) >= min_samples
        if not ok:
            monitor_details.warning("[CHECK_LOAD] Skipping high_load check, not enough samples")
            return False
        
        hist_mem_ratio = self.get_histogram_pressure_ratio("memory", self._memory_threshold)
        hist_cpu_ratio = self.get_histogram_pressure_ratio("cpu", self._cpu_threshold)
        
        current_time = time.monotonic()
        time_since_last_change = current_time - self._last_high_load_change
        
        sustained_pressure_threshold = 0.5
        should_block = hist_mem_ratio > sustained_pressure_threshold or hist_cpu_ratio > sustained_pressure_threshold
        should_unblock = hist_mem_ratio < 0.3 and hist_cpu_ratio < 0.3
        
        prev_high_load = self._high_load_state
        
        if self._high_load_state and should_unblock and time_since_last_change >= self._spawn_hysteresis_time:
            self._high_load_state = False
            self._last_high_load_change = current_time
            monitor_details.info(f"[CHECK_LOAD] high_load = False (unblocked: mem_hist={hist_mem_ratio:.1%}, cpu_hist={hist_cpu_ratio:.1%})")
        elif not self._high_load_state and should_block and time_since_last_change >= self._spawn_hysteresis_time:
            self._high_load_state = True
            self._last_high_load_change = current_time
            monitor_details.info(f"[CHECK_LOAD] high_load = True (blocked: mem_hist={hist_mem_ratio:.1%}, cpu_hist={hist_cpu_ratio:.1%})")
        
        if self._high_load_state != prev_high_load:
            monitor_details.info(
                f"[CHECK_LOAD] high_load {prev_high_load} -> {self._high_load_state} "
                f"(mem_hist={hist_mem_ratio:.1%}, cpu_hist={hist_cpu_ratio:.1%})"
            )
        
        if driver_pool:
            driver_pool.set_high_load(self._high_load_state)

        return self._high_load_state

    def get_histogram_pressure_ratio(self, kind: str, threshold: float) -> float:
        if kind == "memory":
            hist = self._histogram_memory
        elif kind == "cpu":
            hist = self._histogram_cpu
        else:
            raise ValueError("kind must be 'memory' or 'cpu'")

        if not hist or sum(hist) == 0:
            return 0.0

        bin_width = 100.0 / self._histogram_bins
        cutoff_bin = int(threshold // bin_width)
        cutoff_bin = min(cutoff_bin, len(hist) - 1)  

        high_bins = hist[cutoff_bin:]
        total = sum(hist)
        if total == 0:
            return 0.0

        return sum(high_bins) / total
    

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
            self._negative_buffer = max(5, self._negative_buffer - adjust_rate)
            self._positive_buffer = min(15, self._positive_buffer + adjust_rate)
        elif avg_mem > 70 or avg_cpu > 70:
            self._negative_buffer = max(10, self._negative_buffer - 1)
            self._positive_buffer = min(12, self._positive_buffer + 1)
        elif avg_mem < 50 and avg_cpu < 50:
            self._negative_buffer = min(30, self._negative_buffer + adjust_rate)
            self._positive_buffer = max(5, self._positive_buffer - adjust_rate)

        return self._negative_buffer, self._positive_buffer

def resource_pressure_monitor(driver_pool, stop_event):
    memory_monitor = get_memory_monitor()
    dynamic_buffer = DynamicBuffer()

    driver_cfg = Config.get("resources.driver_autoscaling")
    memory_buffer_cfg = Config.get("resources.memory_tuning.buffer")
    memory_pressure_cfg = Config.get("resources.memory_tuning.pressure")
    timeouts_cfg = Config.get("misc.timeouts")
    
    base_buffer_negative = memory_buffer_cfg.get("down_margin")
    base_buffer_positive = memory_buffer_cfg.get("up_margin")
    check_interval = driver_cfg.get("scaling_check_interval")
    
    max_idle_time = timeouts_cfg.get("max_driver_idle_sec")
    idle_check_cycles = timeouts_cfg.get("idle_cycle_check")
    
    driver_limit = Config.get("system.driver_limit")
    
    log_interval = Config.get("misc.logging.interval")
    log_counter = 0
    
    if isinstance(driver_limit, str) and driver_limit.lower() == "auto":
        mem_pressure_threshold = None
        cpu_pressure_threshold = None
    else:
        mem_pressure_threshold = memory_pressure_cfg.get("mem_threshold")
        cpu_pressure_threshold = memory_pressure_cfg.get("cpu_threshold")
    
    idle_check_counter = 0
    
    while not stop_event.is_set():
        try:
            log_counter = (log_counter + 1) % log_interval
            should_log = log_counter == 0
            
            stats = memory_monitor.get_resource_stats()
            avg_mem = stats.memory
            avg_cpu = stats.cpu
            
            hist_mem_ratio = memory_monitor.get_histogram_pressure_ratio("memory", mem_pressure_threshold or 85)
            hist_cpu_ratio = memory_monitor.get_histogram_pressure_ratio("cpu", cpu_pressure_threshold or 85)
   
            negative_buffer, positive_buffer = dynamic_buffer(
                avg_mem, avg_cpu, base_buffer_negative, base_buffer_positive
            )
            
            negative_buffer = negative_buffer or 0
            positive_buffer = positive_buffer or 0

            dynamic_mem_threshold = (mem_pressure_threshold or 85) - negative_buffer
            dynamic_cpu_threshold = (cpu_pressure_threshold or 85) - negative_buffer
            
            mem_release_threshold = (mem_pressure_threshold or 85) - positive_buffer
            cpu_release_threshold = (cpu_pressure_threshold or 85) - positive_buffer
            
            if should_log:
                monitor_details.info(f"[MONITOR_THREAD] memory > {mem_pressure_threshold or 85}% in {hist_mem_ratio:.1%} of checks")
                monitor_details.info(f"[MONITOR_THREAD] cpu > {cpu_pressure_threshold or 85}% in {hist_cpu_ratio:.1%} of checks")
                monitor_details.info(
                    f"[MONITOR_THREAD] thresholds: mem={dynamic_mem_threshold:.1f}%, cpu={dynamic_cpu_threshold:.1f}% "
                    f"(buffers: neg={negative_buffer}, pos={positive_buffer})"
                )
            
            sustained_pressure_threshold = 0.5
            under_pressure = hist_mem_ratio > sustained_pressure_threshold or hist_cpu_ratio > sustained_pressure_threshold
            
            approaching_mem_limit = avg_mem > dynamic_mem_threshold
            approaching_cpu_limit = avg_cpu > dynamic_cpu_threshold
            
            prev_high_load = driver_pool.is_high_load
            
            if prev_high_load:
                high_load = under_pressure or avg_mem > mem_release_threshold or avg_cpu > cpu_release_threshold
            else:
                high_load = under_pressure or approaching_mem_limit or approaching_cpu_limit
            
            driver_pool.set_consecutive_high_load(under_pressure)
            driver_pool.set_high_load(high_load)
            new_high_load = driver_pool.is_high_load
            
            if new_high_load != prev_high_load:
                monitor_details.info(f"[MONITOR_THREAD] high_load changed: {prev_high_load} -> {new_high_load}")
                monitor_details.info(
                    f"[MONITOR_THREAD] reason: under_pressure={under_pressure}, "
                    f"approaching_mem={approaching_mem_limit}, approaching_cpu={approaching_cpu_limit}"
                )
            
            if should_log:
                if high_load:
                    monitor_details.info(
                        f"[MONITOR_THREAD] Spawn blocked: memory > {dynamic_mem_threshold:.1f}% or cpu > "
                        f"{dynamic_cpu_threshold:.1f}% or sustained pressure"
                    )
                else:
                    monitor_details.info(f"[MONITOR_THREAD] Spawn allowed: memory={avg_mem:.1f}%, cpu={avg_cpu:.1f}%")
            
            idle_check_counter += 1
            if idle_check_counter >= idle_check_cycles:
                idle_check_counter = 0
                try:
                    driver_pool.cleanup_idle_drivers(max_idle_time)
                except Exception as e:
                    debug_logger.error(f"[MONITOR_THREAD] idle drivers {e}")
            
            if should_log:
                high_load = driver_pool.is_high_load if driver_pool else False
                monitor_details.info(
                    f"[MONITOR_THREAD] System state: memory={avg_mem:.1f}%, cpu={avg_cpu:.1f}%, "
                    f"high_load={high_load}"
                )
                monitor_details.info(f"[MONITOR_THREAD] Pressure ratios: mem_hist={hist_mem_ratio:.1%}, cpu_hist={hist_cpu_ratio:.1%}")
                monitor_details.info(
                    f"[MONITOR_THREAD] Thresholds: mem_dynamic={dynamic_mem_threshold:.1f}%, cpu_dynamic={dynamic_cpu_threshold:.1f}%, "
                    f"release: mem={mem_release_threshold:.1f}%, cpu={cpu_release_threshold:.1f}%"
                )
            
        except Exception as e:
            debug_logger.error(f"[MONITOR_THREAD] Runtime error: {e}", exc_info=debug)
        stop_event.wait(timeout=check_interval)

def acquire_driver_with_pressure_check(driver_pool, context="unknown"):
    if driver_pool is None:
        debug_logger.error(f"[ACQUIRE_DRIVER] driver_pool is None in {context}")
        return None
    
    memory_monitor = get_memory_monitor()
    memory_monitor.check_load(driver_pool)
    
    if driver_pool.is_high_load:
        debug_logger.warning(f"[ACQUIRE_DRIVER] blocked due to system pressure in {context}")
        timed_out = wait_high_load(driver_pool, context=context)
        if timed_out:
            debug_logger.error(f"[ACQUIRE_DRIVER] giving up after max_wait_time in {context}")
            return None
    
    try:
        driver = driver_pool.get_driver_with_injection(skip_high_load_wait=True)
        return driver
    except Exception as e:
        debug_logger.error(f"[ACQUIRE_DRIVER] {context}: {e}", exc_info=debug)
        return None

def wait_high_load(driver_pool: Any, context: str = "unknown", url: Optional[str] = None) -> bool:
    memory_monitor = get_memory_monitor()
    memory_monitor.check_load(driver_pool)

    block_cfg = Config.get("resources.memory_tuning.pressure_blocking")
    max_wait_time = float(block_cfg.get("max_wait_time", 30.0))
    wait_chunk_time = float(block_cfg.get("wait_chunk_time", 3.0))

    wait_start = time.monotonic()
    pool_stats = driver_pool.get_pool_stats()

    if driver_pool.is_high_load:
        monitor_details.debug(
            f"[HIGH_LOAD] START {context}: high_load={driver_pool.is_high_load}, "
            f"pool_stats={pool_stats}")

    last_block_log = wait_start
    while driver_pool.is_high_load:
        elapsed = time.monotonic() - wait_start
        remaining_total = max_wait_time - elapsed
        if remaining_total <= 0:
            monitor_details.info(
                f"[HIGH_LOAD] blocking timeout after {elapsed:.1f}s waiting "
                f"for unblock in {context}{f' (url={url})' if url else ''}"
            )
            return True

        now = time.monotonic()
        if now - last_block_log >= 5.0:
            monitor_details.info(
                f"[HIGH_LOAD] blocked for {elapsed:.1f}s in {context}{f' (url={url})' if url else ''}"
            )
            last_block_log = now

        jitter = wait_chunk_time + random.uniform(0.1, 0.3)
        chunk = min(jitter, remaining_total)

        unblocked = driver_pool.wait_for_unblock(timeout=chunk)
        if unblocked:
            break

        memory_monitor.check_load(driver_pool)

    elapsed = time.monotonic() - wait_start
    if elapsed > 0:
        pool_stats = driver_pool.get_pool_stats()
        monitor_details.info(
            f"[HIGH_LOAD] END {context}: elapsed={elapsed:.1f}s, high_load={driver_pool.is_high_load}, pool_stats={pool_stats}"
        )

    return False

