from xauto.utils.setup import get_random_user_agent
from xauto.utils.config import Config
from xauto.utils.logging import monitor_details
from xauto.utils.injection import wrap_driver_with_injection
from xauto.internal.memory import DriverSpawnBudget
from xauto.internal.thread_safe import AtomicCounter
from xauto.internal.dataclasses import DriverInfo

import os
import time
import queue
import threading
import psutil
from termcolor import cprint
from selenium.webdriver.firefox.service import Service
from selenium import webdriver

_driver_pool = None
_driver_pool_lock = threading.Lock()

def get_driver_pool(max_size, firefox_options, force_reset=False):
    global _driver_pool
    
    if not force_reset and _driver_pool is not None:
        return _driver_pool
    
    with _driver_pool_lock:
        if force_reset or _driver_pool is None:
            if _driver_pool:
                _driver_pool.close_all()
            _driver_pool = DriverPool(max_size, firefox_options)
    return _driver_pool

class DriverPool:
    __slots__ = (
        '_lock', '_auto_mode', '_max_size', '_pool', '_drv_path', '_service', '_options', 
        '_created', '_errors', '_info', '_driver_objects', '_termination_failures', 
        'proxy_enabled', 'proxies', '_proxy_index', 'no_ssl_verify', 'use_auth', '_in_use', 
        'username', 'password', 'socks5', 'dns_resolver', '_logger', '_shutdown',
        '_seleniumwire_webdriver', '_pressure_lock', '_spawn_blocked', '_spawn_budget',
        '_last_scale_down_time', '_consecutive_high_load_count', 
    )
    
    def __init__(self, max_size, firefox_options):
        self._lock = threading.Condition()
        self._pressure_lock = threading.Lock()
        self._auto_mode = (isinstance(max_size, str) and max_size.lower() == "auto") or max_size == float('inf')
        if self._auto_mode:
            self._max_size = float('inf')
            queue_maxsize = 1000
            # debug_logger.info("Driver pool initialized with driver_limit = auto (unlimited)")
        else:
            self._max_size = int(max_size)
            queue_maxsize = self._max_size
            # debug_logger.info(f"Driver pool initialized with driver_limit = {self._max_size}")
        
        self._pool = queue.Queue(maxsize=queue_maxsize)
        self._drv_path = os.path.join(os.path.dirname(__file__), 'geckodriver')
        
        self._options = firefox_options
        self._info = {}
        self._driver_objects = {}
        self._in_use = AtomicCounter()
        self._created = AtomicCounter()
        self._errors = AtomicCounter()
        self._termination_failures = AtomicCounter()
        
        self._shutdown = False
        self._last_scale_down_time = 0.0
        self._consecutive_high_load_count = 0
        self._spawn_blocked = False
        
        driver_spawning = Config.get("resources.driver_spawning")
        spawn_window_sec = driver_spawning.get("spawn_window_sec")
        max_spawns_per_window = driver_spawning.get("max_spawns_per_window")
        self._spawn_budget = DriverSpawnBudget(max_spawns_per_window, spawn_window_sec)
        # debug_logger.info(f"Driver spawn budget initialized: {max_spawns_per_window} per {spawn_window_sec}s window")
        
        proxy_settings = Config.get("proxy")
        self.proxy_enabled = False
        self.proxies = []
        self._proxy_index = 0
        self.no_ssl_verify = False
        self.use_auth = False
        self.username = None
        self.password = None
        self.socks5 = False
        self.dns_resolver = False
        self._seleniumwire_webdriver = None
        
        self._load_config(proxy_settings)
        self._init_seleniumwire()
        
        if self.proxy_enabled and not self._seleniumwire_webdriver:
            raise RuntimeError("Proxies enabled but selenium-wire not installed")

    def _init_seleniumwire(self):
        try:
            import warnings
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", category=UserWarning, module="seleniumwire")
                from seleniumwire import webdriver as seleniumwire_webdriver
                self._seleniumwire_webdriver = seleniumwire_webdriver
                # debug_logger.info("selenium-wire successfully imported - proxy support available")
        except ImportError as e:
            # debug_logger.warning(f"selenium-wire import failed ({e})")
            # debug_logger.warning("Residential proxy support will NOT be available.")
            # debug_logger.warning("To enable proxy support, install selenium-wire.")
            pass
        except Exception as e:
            # debug_logger.error(f"ERROR importing selenium-wire: {e}")
            # debug_logger.error("Residential proxy support will NOT be available.")
            pass

    def _load_config(self, proxy_settings):
        self.proxy_enabled = proxy_settings.get("enabled")
        self.proxies = proxy_settings.get("list")
        self.no_ssl_verify = proxy_settings.get("no_ssl_verify")

        credentials = proxy_settings.get("credentials")
        self.use_auth = credentials.get("enabled")
        self.username = credentials.get("username") or os.getenv("EXPORT_PROXY_USERNAME")
        self.password = credentials.get("password") or os.getenv("EXPORT_PROXY_PASSWORD")

        self.socks5 = proxy_settings.get("socks5_mode")
        self.dns_resolver = proxy_settings.get("resolve_dns_locally")

        if self.proxy_enabled:
            if self.proxies:
                self._proxy_index = 0
            else:
                cprint("Proxies are enabled but the proxy list is empty. No proxies will be used.", "red")
                self._proxy_index = -1

    def _format_proxy(self, raw: str) -> str:
        if ":" not in raw:
            cprint(f"Bad proxy format: {raw!r}\nexpected format: user:pass@host:port", "red")
            raise ValueError(f"Bad proxy format: {raw!r}")
        host, port = raw.split(":", 1)
        creds = f"{self.username}:{self.password}@" if self.use_auth else ""
        scheme = "socks5" if self.socks5 else "http"
        return f"{scheme}://{creds}{host}:{port}"

    def _create_driver(self):
        driver_opts = self._options
        driver_opts.set_preference("general.useragent.override", get_random_user_agent())

        service = Service(self._drv_path, port=0)

        selected_proxy = None
        try:
            if self.proxy_enabled and self._proxy_index >= 0:
                selected_proxy = self.proxies[self._proxy_index]
                self._proxy_index = (self._proxy_index + 1) % len(self.proxies)
                if selected_proxy:
                    px_url = self._format_proxy(selected_proxy)
                    sw_opts = {
                        "proxy": {
                            "http":     px_url,
                            "https":    px_url,
                            "no_proxy": "localhost,127.0.0.1",
                        },
                        "verify_ssl":          not self.no_ssl_verify,
                        "suppress_connection_errors": False,
                        "disable_encoding":    True,
                        "mitm_http2":          False,
                    }
                    if self.socks5:
                        sw_opts["proxy"].update({
                            "socks_proxy":      px_url,
                            "socks_version":    5
                        })
                    if self.dns_resolver:
                        sw_opts["dns_resolver"] = True

                    if self._seleniumwire_webdriver is None:
                        raise RuntimeError("selenium-wire not available for proxy support")
                        
                    drv = self._seleniumwire_webdriver.Firefox(
                        seleniumwire_options=sw_opts,
                        service=service,
                        options=driver_opts
                    )
                else:
                    drv = webdriver.Firefox(service=service, options=driver_opts)
            else:
                drv = webdriver.Firefox(service=service, options=driver_opts)
        except Exception as e:
            # debug_logger.warning(f"Failed to create driver: {e}", exc_info=debug)
            self._errors += 1
            monitor_details.debug(f"[DRIVER_CREATE] FAILED: error={e}")
            return None

        pids = []
        try:
            if service.process and service.process.pid:
                pids = [service.process.pid]
        except Exception as e:
            # debug_logger.warning(f"Failed to get driver PID: {e}", exc_info=debug)
            pass

        with self._lock:
            self._info[id(drv)] = DriverInfo(pids)
            self._driver_objects[id(drv)] = drv
            self._created += 1

        with self._lock:
            info = self._info.get(id(drv))
            if info:
                info.last_access = time.monotonic()
        
        setattr(drv, '_driver_pool', self)
        pool_stats = self.get_pool_stats()
        monitor_details.debug(f"[DRIVER_CREATE] SUCCESS: driver_id={id(drv)}, pids={pids}, pool_stats={pool_stats}")
        return drv

    def _create_driver_with_retries(self, max_retries=3, backoff=1.0):
        for attempt in range(max_retries):
            try:
                driver = self._create_driver()
                if driver is not None:
                    return driver
                raise RuntimeError("Driver creation returned None")
            except Exception as e:
                if attempt < max_retries - 1:
                    time.sleep(backoff * (2 ** attempt))
                else:
                    raise RuntimeError(f"Failed to create driver after {max_retries}. ERROR: {e}")
        
        raise RuntimeError("Driver creation failed - unexpected end of retry loop")

    def set_spawn_blocked(self, blocked):
        with self._lock:
            prev_blocked = self._spawn_blocked
            self._spawn_blocked = blocked
            if prev_blocked != blocked:
                pass
            if blocked:
                # debug_logger.info("Driver spawn blocked due to high system load")
                pass
            else:
                # debug_logger.info("Driver spawn unblocked")
                self._lock.notify_all()

    def get_driver_with_injection(self, timeout=None):
        drv = self.get_driver(timeout=timeout)
        if drv is None:
            return None
        
        w = wrap_driver_with_injection(drv)
        return w

    def get_driver(self, timeout=None):
        if self._shutdown:
            return None

        drv = None
        try:
            drv = self._pool.get(timeout=timeout if timeout is not None else 0.1)
        except queue.Empty:
            if self._max_size == float('inf') or int(self._created) < self._max_size:
                # debug_logger.debug("No drivers available, creating first driver")
                
                while not self._spawn_budget.can_spawn(self):
                    remaining = self._spawn_budget.get_remaining(self)
                    time_until_reset = self._spawn_budget.get_time_until_reset()
                    # debug_logger.info(f"Driver spawn budget exhausted for this minute (remaining: {remaining}, reset in {time_until_reset:.1f}s), waiting...")
                    
                    time.sleep(Config.get("misc.timeouts.spawn_wait_delay"))
                
                from xauto.internal.memory import wait_high_load
                wait_high_load(self, context="driver_pool.get_driver")
                
                drv = self._create_driver_with_retries()
            else:
                # debug_logger.debug("At max driver capacity, blocking until driver becomes available")
                drv = self._pool.get(timeout=timeout if timeout is not None else 30)

        with self._lock:
            info = self._info.get(id(drv))
            if info:
                info.last_access = time.monotonic()
            self._in_use += 1
        
        pool_size = self._pool.qsize()
        created_count = int(self._created)
        in_use_count = int(self._in_use)
        error_count = int(self._errors)
        max_size = self._max_size if self._max_size != float('inf') else 'inf'
        
        monitor_details.debug(f"[DRIVER_POOL] get_driver: pool_size={pool_size}, created={created_count}, in_use={in_use_count}, errors={error_count}, max_size={max_size}")
        # debug_logger.debug(f"CHECKPOINT: driver acquired (id={id(drv)}, in_use={self._in_use})")
        return drv

    def return_driver(self, drv):
        if drv is None:
            return

        with self._lock:
            info = self._info.get(id(drv))
            if info:
                info.last_access = 0
            self._in_use -= 1

        try:
            self._pool.put_nowait(drv)
        except queue.Full:
            # debug_logger.warning("Driver pool is full, destroying driver")
            self._destroy(drv)
            return

        pool_size = self._pool.qsize()
        created_count = int(self._created)
        in_use_count = int(self._in_use)
        error_count = int(self._errors)
        max_size = self._max_size if self._max_size != float('inf') else 'inf'
        monitor_details.debug(f"[DRIVER_POOL] return_driver: pool_size={pool_size}, created={created_count}, in_use={in_use_count}, errors={error_count}, max_size={max_size}")

    def mark_driver_failed(self, driver):
        if driver is None:
            return

        with self._lock:
            info = self._info.get(id(driver))
            if info:
                info.failure_count += 1
            self._errors += 1

        pool_size = self._pool.qsize()
        created_count = int(self._created)
        in_use_count = int(self._in_use)
        error_count = int(self._errors)
        max_size = self._max_size if self._max_size != float('inf') else 'inf'
        monitor_details.debug(f"[DRIVER_POOL] mark_driver_failed: pool_size={pool_size}, created={created_count}, in_use={in_use_count}, errors={error_count}, max_size={max_size}")

    def has_recent_failures(self):
        with self._lock:
            return any(info.failure_count > 0 for info in self._info.values())

    def set_consecutive_high_load(self, is_high_load):
        with self._pressure_lock:
            if is_high_load:
                self._consecutive_high_load_count += 1
            else:
                self._consecutive_high_load_count = 0

    def requires_consecutive_high_load(self, required_count=2):
        with self._pressure_lock:
            return self._consecutive_high_load_count >= required_count

    def _destroy(self, drv):
        if drv is None:
            return

        driver_id = id(drv)
        pool_stats_before = self.get_pool_stats()
        monitor_details.debug(f"[DRIVER_DESTROY] START: driver_id={driver_id}, pool_stats={pool_stats_before}")

        try:
            with self._lock:
                info = self._info.get(id(drv))
                if info:
                    pids = info.pids
                else:
                    pids = []
                self._info.pop(id(drv), None)
                self._driver_objects.pop(id(drv), None)
                # Decrement the in_use counter when destroying a driver
                self._in_use -= 1

            try:
                drv.quit()
                monitor_details.debug(f"[DRIVER_DESTROY] quit_success: driver_id={driver_id}")
            except Exception as e:
                # debug_logger.warning(f"Error quitting driver: {e}")
                monitor_details.debug(f"[DRIVER_DESTROY] quit_failed: driver_id={driver_id}, error={e}")
                pass

            for pid in pids:
                try:
                    process = psutil.Process(pid)
                    if process.is_running():
                        process.terminate()
                        try:
                            process.wait(timeout=5)
                            monitor_details.debug(f"[DRIVER_DESTROY] process_terminated: driver_id={driver_id}, pid={pid}")
                        except psutil.TimeoutExpired:
                            process.kill()
                            monitor_details.debug(f"[DRIVER_DESTROY] process_killed: driver_id={driver_id}, pid={pid}")
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    monitor_details.debug(f"[DRIVER_DESTROY] process_already_dead: driver_id={driver_id}, pid={pid}")
                    pass
                except Exception as e:
                    # debug_logger.warning(f"Error terminating process {pid}: {e}")
                    monitor_details.debug(f"[DRIVER_DESTROY] process_error: driver_id={driver_id}, pid={pid}, error={e}")
                    pass

        except Exception as e:
            # debug_logger.error(f"Error destroying driver: {e}")
            self._termination_failures += 1
            monitor_details.debug(f"[DRIVER_DESTROY] destroy_error: driver_id={driver_id}, error={e}")

        pool_stats_after = self.get_pool_stats()
        monitor_details.debug(f"[DRIVER_DESTROY] END: driver_id={driver_id}, pool_stats={pool_stats_after}")

    def close_all(self):
        if self._shutdown:
            return
            
        self._shutdown = True
        # debug_logger.info("Closing all drivers")
        
        while True:
            try:
                drv = self._pool.get_nowait()
                if drv is not None:
                    self._destroy(drv)
            except queue.Empty:
                break
        
        with self._lock:
            drivers_to_destroy = list(self._driver_objects.items())
        
        for drv_id, driver in drivers_to_destroy:
            try:
                self._destroy(driver)
            except Exception as e:
                # debug_logger.warning(f"Error destroying driver {drv_id}: {e}", exc_info=debug)
                pass
        
        try:
            self._cleanup_remaining_processes()
        except Exception as e:
            # debug_logger.warning(f"Error in final process cleanup: {e}", exc_info=debug)
            pass
        
        # created_count = int(self._created)
        # debug_logger.info(f"Closed {created_count} drivers")

    def _cleanup_remaining_processes(self):
        try:
            current_user = os.getenv('USER', '')
            if not current_user:
                return
                
            for proc in psutil.process_iter(['pid', 'name', 'username']):
                try:
                    if (proc.info['username'] == current_user and 
                        proc.info['name'] and 
                        ('firefox' in proc.info['name'].lower() or 
                         'geckodriver' in proc.info['name'].lower())):
                        # debug_logger.debug(f"Killing remaining process: {proc.info['name']} (PID: {proc.info['pid']})")
                        proc.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    pass
                except Exception as e:
                    # debug_logger.debug(f"Error checking process {proc.info.get('pid', 'unknown')}: {e}")
                    pass
        except Exception as e:
            # debug_logger.debug(f"Error in remaining process cleanup: {e}")
            pass

    def cleanup_idle_drivers(self, max_idle_time=30):
        if self._shutdown:
            return

        current_time = time.monotonic()
        drivers_to_remove = []

        with self._lock:
            for driver_id, info in list(self._info.items()):
                if info.last_access == 0: 
                    if current_time - info.heap_timestamp > max_idle_time:
                        drivers_to_remove.append(driver_id)

        if drivers_to_remove:
            pool_size = self._pool.qsize()
            created_count = int(self._created)
            in_use_count = int(self._in_use)
            error_count = int(self._errors)
            max_size = self._max_size if self._max_size != float('inf') else 'inf'
            monitor_details.debug(f"[DRIVER_POOL] cleanup_idle_drivers START: removing={len(drivers_to_remove)}, pool_size={pool_size}, created={created_count}, in_use={in_use_count}, errors={error_count}, max_size={max_size}")

            for driver_id in drivers_to_remove:
                try:
                    driver = self._driver_objects.get(driver_id)
                    if driver:
                        # Note: We can't easily remove from queue, so we'll just destroy the driver
                        # The queue will eventually be cleaned up when the driver is accessed
                        self._destroy(driver)
                except Exception as e:
                    # debug_logger.warning(f"Error cleaning up idle driver: {e}")
                    pass

            pool_size = self._pool.qsize()
            created_count = int(self._created)
            in_use_count = int(self._in_use)
            error_count = int(self._errors)
            monitor_details.debug(f"[DRIVER_POOL] cleanup_idle_drivers END: pool_size={pool_size}, created={created_count}, in_use={in_use_count}, errors={error_count}")

    def _sweep_orphaned_drivers(self):
        if self._shutdown:
            return
            
        with self._lock:
            pool_contents = set()
            try:
                while True:
                    drv = self._pool.get_nowait()
                    if drv is not None:
                        pool_contents.add(id(drv))
                        self._pool.put(drv)
            except queue.Empty:
                pass
            
            orphaned_ids = set(self._driver_objects.keys()) - pool_contents - set(self._info.keys())
            
            if orphaned_ids:
                # debug_logger.info(f"Sweeping {len(orphaned_ids)} orphaned drivers")
                pass
            
            for orphaned_id in orphaned_ids:
                if orphaned_id in self._driver_objects:
                    driver = self._driver_objects[orphaned_id]
                    del self._driver_objects[orphaned_id]
                    try:
                        self._destroy(driver)
                    except Exception:
                        pass
                    # debug_logger.debug(f"Swept orphaned driver {orphaned_id}")

    def return_driver_size(self):
        return self._pool.qsize()

    @property
    def max_size(self):
        return self._max_size

    def scale_down(self, count):
        if self._shutdown:
            return False
            
        with self._lock:
            current_size = self._pool.qsize()
            if current_size > 0:
                drivers_to_remove = min(count, current_size)
                # debug_logger.info(f"Scaling down driver pool by {drivers_to_remove} drivers")
                
                pool_size = self._pool.qsize()
                created_count = int(self._created)
                in_use_count = int(self._in_use)
                error_count = int(self._errors)
                max_size = self._max_size if self._max_size != float('inf') else 'inf'
                monitor_details.debug(f"[DRIVER_POOL] scale_down START: removing={drivers_to_remove}, pool_size={pool_size}, created={created_count}, in_use={in_use_count}, errors={error_count}, max_size={max_size}")
                
                for _ in range(drivers_to_remove):
                    try:
                        drv = self._pool.get_nowait()
                        if drv is not None:
                            self._destroy(drv)
                    except queue.Empty:
                        break
                
                pool_size = self._pool.qsize()
                created_count = int(self._created)
                in_use_count = int(self._in_use)
                error_count = int(self._errors)
                monitor_details.debug(f"[DRIVER_POOL] scale_down END: pool_size={pool_size}, created={created_count}, in_use={in_use_count}, errors={error_count}")
                
                return True
            else:
                # debug_logger.debug("No idle drivers available for scale down")
                return False

    def mark_driver_bad(self, driver):
        if driver is not None:
            self.mark_driver_failed(driver)

    def get_active_count(self):
        return int(self._in_use)

    def should_close_driver_for_pressure(self, cooldown_seconds=None):
        if cooldown_seconds is None:
            from xauto.utils.config import Config
            cooldown_seconds = Config.get("resources.driver_autoscaling.scale_down_cooldown", 5.0)
            
        with self._pressure_lock:
            now = time.monotonic()
            
            if self.has_recent_failures():
                return False
            
            if now - self._last_scale_down_time < cooldown_seconds:
                return False
            
            return self._consecutive_high_load_count >= 2

    def mark_driver_closed_for_pressure(self):
        with self._pressure_lock:
            self._last_scale_down_time = time.monotonic()

    def is_driver_in_use(self, driver):
        if driver is None:
            return False
        with self._lock:
            return id(driver) in self._info and self._info[id(driver)].last_access > 0

    def shutdown(self, wait=True, timeout=None):
        if wait:
            self.close_all()
        else:
            self._shutdown = True
        return True

    def get_total_created_count(self):
        return int(self._created)

    def get_error_count(self):
        return int(self._errors)

    def can_create_driver(self) -> bool:
        return (
            not self._spawn_blocked and
            self._spawn_budget.can_spawn(self) and
            not self._shutdown
        )

    def get_pool_stats(self):
        with self._lock:
            return {
                'pool_size': self._pool.qsize(),
                'created': int(self._created),
                'in_use': int(self._in_use),
                'errors': int(self._errors),
                'termination_failures': int(self._termination_failures),
                'max_size': self._max_size if self._max_size != float('inf') else 'inf',
                'auto_mode': self._auto_mode,
                'shutdown': self._shutdown,
                'spawn_blocked': self._spawn_blocked,
                'spawn_budget_remaining': self._spawn_budget.get_remaining(self) if hasattr(self._spawn_budget, 'get_remaining') else 'N/A',
                'can_create_driver': self.can_create_driver()
            }
