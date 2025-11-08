# Selenium WebDriver Infrastructure

This repository provides a Selenium WebDriver infrastructure in Python. It is designed for web automation tasks including scraping, form filling, and browser automation.

## Core Utilities

### JavaScript API Injection

```python
from xauto.utils.injection import ensure_injected
# core utilities call ensure_injected internally
# injects internal JS API into the page
ensure_injected(driver)
```
> APIs can be extended to support DOM traversal, element extraction, in page URL parsing, etc.

Currently, the API provides:

- `waitForReady()` - waits for full document readiness and 70% of `fetch()` requests to complete
- `closePopups()` - attempts to close all tabs in `window.openedWindows` that are not the original tab
- `stealthPatches()` - masks common browser automation fingerprints such as navigator, plugins, etc
- Injection state tracking via `data-injected` attribute
- Safe reinjection on navigation or dynamic DOM reloads
- Code is frozen and hidden from enumeration

### Driver Pool Management
```python
from xauto.internal.geckodriver.driver import get_driver_pool
# create driver pool
driver_pool = get_driver_pool(max_size=10, firefox_options=options)

# will call get_driver_with_injection() internally
acquire_driver_with_pressure_check(driver_pool, "Worker-name")

# helpful methods of driver_pool
driver_pool.get_driver(timeout=)  
driver_pool.get_driver_with_injection(timeout=)
driver_pool.return_driver(driver)          
driver_pool.mark_driver_failed(driver)      
driver_pool.cleanup_idle_drivers(max_idle_time=)
driver_pool.should_close_driver_for_pressure(cooldown_seconds=)

# get pool stats
stats = driver_pool.get_pool_stats()
print(f"Active drivers: {stats['in_use']}")
print(f"Total created: {stats['created']}")
print(f"Errors: {stats['errors']}")
```

### Resource Monitoring
```python
from xauto.internal.memory import get_memory_monitor
monitor = get_memory_monitor()
if monitor.is_under_pressure():
    # handle high resource usage here
    print("System under pressure")

# get resource stats
stats = monitor.get_resource_stats()
print(f"Memory usage: {stats.memory_percent}%")
print(f"CPU usage: {stats.cpu_percent}%")

from xauto.internal.memory import acquire_driver_with_pressure_check
# only acquire a driver when system is under CPU/MEM thresholds
# class Worker uses this check before spawning drivers
driver = acquire_driver_with_pressure_check(driver_pool, context="unknown")
driver.get()

from xauto.internal.memory import wait_high_load
# blocks the threads runtime preventing work under high load 
forced_unblock = wait_high_load(pool, context="url_navigation", allow_timeout=True)
if forced_unblock:
  print("Unblocked due to max_wait_time")
```

### Browser Validation Checks
```python
from xauto.utils.validation import is_up
# quick page probe before trying a driver.get()
up, status_code = is_up(url, driver)
if not up:
    print(f"Page is not up {status_code}")
    # handle error here
# else continue with driver.get()

from xauto.utils.validation import is_browser_error_page
if is_browser_error_page(driver):
    print("Browser error page detected")
    # handle error page here

from xauto.utils.validation import is_connection_error
if is_connection_error(error):
    print("Browser connection error detected")
    # handle connection error here

from xauto.utils.validation import is_bot_page
if is_bot_page(driver, url):
    print("Browser bot page detected")
    # handle bot page error here
```

### Browser Handling
```python
from xauto.utils.browser_utils import close_popups
# closes all tabs in window.openedWindows that are not the original tab
# for cleaning up popups or new tabs triggered by window.open during automation
# close_popups is called internally by all page loading functions
close_popups(driver)

from xauto.utils.browser_utils import send_key
# sends keys to a form field with retry logic and optional iframe handling
# check_url=True waits for a URL change after pressing RETURN
send_key(driver, field, "username", check_url=False, iframe=iframe_element)
send_key(driver, field, "password1", check_url=True, iframe=iframe_element)
```

### Browser Page Loading
```python
from xauto.utils.page_loading import load_page_with_high_load_check
# wait_for_page_load and wait_high_load are called inside
if not load_page_with_high_load_check(driver, url, timeout=):
    print("Page failed to load")
    return

from xauto.utils.page_loading import wait_for_page_load
# ensure_body_loaded is called inside
if not wait_for_page_load(driver, wait_for=):
    print("Page failed to load")
    # handle page loading error here

from xauto.utils.page_loading import ensure_body_loaded
if not ensure_body_loaded(driver, wait_for=):
    print("Page body failed to load")
    # handle page loading error here

from xauto.utils.page_loading import explicit_page_load
if not explicit_page_load(driver, wait_for=):
    print("Page did not load after a explict wait")
    # handle page loading error here

from xauto.utils.page_loading import wait_for_url_change
# wait for a URL change after sending RETURN key
wait_for_url_change(driver, old_url, wait_for=)
```

### Thread Safe
```python
from xauto.internal.thread_safe import ThreadSafeList, ThreadSafeDict, AtomicCounter
safe_list = ThreadSafeList()
safe_dict = ThreadSafeDict()
counter = AtomicCounter()

safe_list.append(item)
safe_dict[key] = value
counter.increment()
counter.decrement()
counter.reset()
counter.get()

from xauto.internal.thread_safe import SafeThread
thread = SafeThread(
    target_fn=dummy_function,
    name="DummyName"
)
thread.start()
```

### Bootstrap
```python
from xauto.bootstrap.build import bootstrap
if not bootstrap():
    print("Bootstrap failed")
    sys.exit(1)
```

The bootstrap system will:
1. Check python version is compatible 
2. Download GeckoDriver
3. Create a virtual environment
4. Install required dependencies

## Features

- **Thread Safety**: Uses SafeThread wrappers to isolate thread crashes from the main event loop
- **Resource Monitoring**: Real time memory and CPU pressure monitoring
- **Auto scaling**: Driver pool scales based on system feedback
- **Graceful Shutdown**: Cleanup and resource management
- **Configuration Management**: YAML based configuration with runtime freezing
- **Proxy Support**: Supports proxy rotation, authentication, and SOCKS5 proxies.
- **Browser Automation**: Firefox/GeckoDriver with some anti detection features
- **Task Management**: Thread safe task queuing and worker management
- **Browser Error Detection**: Built in detection of browser error pages
- **Generic Infrastructure**: Designed for any web automation task, not just scraping
- **Logging**: Multiple log levels and output files
- **JavaScript API Injection**: Custom browser API (_xautoAPI)
- **Bot Detection**: Able to detect pages with bot challenges for handling or bypass logic

## Configuration

The application is configured via `settings.yaml`. Key configuration sections:

### System Settings
```yaml
system:
  driver_limit: auto  # or specific number
  headless: false
```

### Resource Management
```yaml
resources:
  driver_autoscaling:
    scaling_check_interval: 0.5
    step_up: 2
    step_down: 1
    scale_down_cooldown: 5.0
  memory_tuning:
    pressure:
      mem_threshold: 75.0
      cpu_threshold: 80.0
```

### Misc 
```yaml
misc:
  logging:
    log_timer_interval: 5

  thread_monitoring:
    worker_monitor_loop_interval: 1

  timeouts:
    # shutdown timeouts 
    program_shutdown_timeout: 10
    stop_all_workers_timeout: 10
    stop_worker_timeout: 5

    # function retries
    max_send_key_retries: 2
    max_worker_task_retries: 2

   # loading timeouts
    max_body_load_wait: 10
    max_url_load_wait: 5

    # driver timeouts
    driver_recreate_delay: 5
    driver_slot_wait_delay: 3
```

### Proxy Configuration
```yaml
proxy:
  enabled: true
  credentials:
    enabled: false
    username: ""
    password: ""
  list: []
```

## Dependencies

Core dependencies (see `bootstrap/installs.txt`):
- `selenium==4.33.0` - WebDriver automation
- `selenium-wire==5.1.0` - Proxy support
- `requests` - HTTP client
- `psutil` - System monitoring
- `pyyaml` - Configuration parsing
- `termcolor` - Colored output
- `blinker` - Event signaling

## Disclaimer

This infrastructure is designed for legitimate web automation tasks. Repository contains only the core infrastructure. The actual automation logic and credential processing components have been removed.

