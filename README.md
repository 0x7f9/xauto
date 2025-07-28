# Selenium WebDriver Infrastructure

This repository provides a generic Selenium WebDriver infrastructure in Python. It is designed for web automation tasks including scraping, form filling, and browser automation.

## Quick Usage Example

```python
from xauto.bootstrap.build import bootstrap

# bootstrap install.txt file
if not bootstrap():
    print("ERROR: Bootstrap failed. Cannot proceed.")
    import sys; sys.exit(1)

from xauto.utils.config import Config
from xauto.utils.setup import get_options
from xauto.internal.geckodriver.driver import get_driver_pool
from xauto.utils.task_manager import TaskManager

# initialize configuration you can freeze it also
config = Config()
config.freeze()

# get browser options with anti detection features
options = get_options()
# includes: private browsing, fingerprinting resistance,
# disabled automation flags, cache disabled, notifications disabled

# create a thread safe driver pool
driver_pool = get_driver_pool(max_size=10, firefox_options=options)

# define a task for the workers
def your_task_function(task_data, driver):
    """
    The function each worker thread will run.
    """
    url = task_data.get('url')
    driver.get(url)
    # add your scraping or automation logic here
    return driver.title

# define task data
your_task_data = {
    'url': 'https://example.com'
}

# create and configure the task manager
task_manager = TaskManager(
    driver_pool=driver_pool,
    task_processor=your_task_function,
    max_workers=5
)

# start worker threads
task_manager.start()

# add a task to the queue
task_manager.add_task(your_task_data)

# add tasks to the queue
task_manager.add_tasks([task1, task2])

# wait for all tasks to complete
task_manager.wait_completion()

# clean ups
task_manager.shutdown()
driver_pool.shutdown()
```

## Recommended Usage with setup_runtime()

For simplicity and minimal boilerplate, the recommended approach is to use the `setup_runtime()` function which handles all the infrastructure setup automatically:

```python
from xauto.utils.config import Config
from xauto.utils.lifecycle import setup_runtime, teardown_runtime

# initialize configuration
config = Config()
config.freeze()

# define your task function
def your_task_function(task_data, driver):
    """
    The function each worker thread will run.
    """
    url = task_data.get('url')
    driver.get(url)
    # add your scraping or automation logic here
    return driver.title

# setup runtime with 5 workers
task_manager, driver_pool = setup_runtime(
    task_processor=your_task_function
)

# add your tasks
task_manager.add_task({'url': 'https://example.com'})

# wait for completion
task_manager.wait_completion()

# cleanup (handles all shutdown automatically)
teardown_runtime(task_manager, driver_pool)
```

The `setup_runtime()` function automatically:
- Creates the driver pool with proper sizing
- Sets up the task manager with auto scaling
- Starts resource monitoring threads
- Handles configuration and logging setup
- Returns ready to use task_manager and driver_pool objects

## Simple Direct Usage

For single tasks or simple automation, you can use the driver pool directly without the task manager:

```python
from xauto.utils.setup import get_options, is_browser_error_page
from xauto.internal.geckodriver.driver import get_driver_pool

options = get_options()

driver_pool = get_driver_pool(max_size=1, firefox_options=options)
driver = None

try:
    driver = driver_pool.get_driver()
    if driver is None:
        print("ERROR: Failed to acquire driver")
        sys.exit(1)
    
    # logic here
    driver.get("https://example.com")
    
    if is_browser_error_page(driver):
        print("Browser error page detected")
        return
    
    # continue with your logic...
    
except Exception as e:
    print(f"ERROR: Task failed due to: {e}")
finally:
    if driver is not None:
        driver_pool.return_driver(driver)
    driver_pool.shutdown()
```

## Core Utilities

### JavaScript API Injection

```python
from xauto.utils.injection import ensure_injected

driver.get("https://example.com")

# core utilities like wait_for_page_load already call ensure_injected internally
# ensure internal JS API is injected into the page
ensure_injected(driver)
```
> APIs can be extended to support DOM traversal, element extraction, in page URL parsing, etc.

Currently, the API provides:

- `waitForReady()` — waits until the page is fully loaded, and no pending JS requests are active. Does not account for fetch() yet.
- Injection state tracking via `data-injected` attribute
- Safe reinjection on navigation or dynamic DOM reloads
- window._xautoAPI is frozen and hidden from enumeration

### Driver Pool Management
```python
from xauto.internal.geckodriver.driver import get_driver_pool

# create driver pool
driver_pool = get_driver_pool(max_size=10, firefox_options=options)

# driver management methods
driver = driver_pool.get_driver(timeout=30)  
driver_pool.return_driver(driver)          
driver_pool.mark_driver_failed(driver)      
driver_pool.cleanup_idle_drivers(max_idle_time=30) 

# get pool stats
stats = driver_pool.get_pool_stats()
print(f"Active drivers: {stats['in_use']}")
print(f"Total created: {stats['created']}")
print(f"Errors: {stats['errors']}")
```

### Resource Monitoring
```python
from xauto.internal.memory import get_memory_monitor

# check system pressure
monitor = get_memory_monitor()
if monitor.is_under_pressure():
    # handle high resource usage here
    print("System under pressure")

# get resource stats
stats = monitor.get_resource_stats()
print(f"Memory usage: {stats.memory_percent}%")
print(f"CPU usage: {stats.cpu_percent}%")
```

### Browser Validation Checks
```python
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

### Browser Page Loading
```python
from xauto.utils.page_loading import wait_for_page_load
# ensure_body_loaded is called inside of wait_for_page_load
if not wait_for_page_load(driver, timeout=):
    print("Page failed to load")
    # handle page loading error here

from xauto.utils.page_loading import ensure_body_loaded
if not ensure_body_loaded(driver, timeout=):
    print("Page body failed to load")
    # handle page loading error here

from xauto.utils.page_loading import explicit_page_load
if not explicit_page_load(driver, timeout=):
    print("Page did not load after a explict wait")
    # handle page loading error here
```

### Thread Safe Utilities
```python
from xauto.internal.thread_safe import ThreadSafeList, ThreadSafeDict, AtomicCounter

safe_list = ThreadSafeList()
safe_dict = ThreadSafeDict()
counter = AtomicCounter()

safe_list.append(item)
safe_dict[key] = value
counter.increment()
```

## Features

- **Thread Safe WebDriver Pool**: Enables management of multiple browser instances
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

## Installation

- Python 3.10+
- Linux

### Quick Start
```bash
git clone https://github.com/0x7f9/xauto.git
cd xauto

# will bootstrap automatically
python example.py
```

The bootstrap system will:
1. Create a virtual environment
2. Install required dependencies
3. Download GeckoDriver
4. Initialize the WebDriver infrastructure

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

### Timeouts
```yaml
misc:
  timeouts:
    body_load: 10
    max_task_retries: 2
    shutdown: 10
    worker: 5
    circuit_breaker_window: 30
    circuit_breaker_max_delay: 60
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

This infrastructure is designed for legitimate web automation tasks. Repository contains only the core infrastructure. The actual automation logic and credential processing components have been removed for privacy and security reasons.

