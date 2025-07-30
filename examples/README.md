# xauto Examples

### `basic_example.py`
Basic example demonstrating:
- Config loading and freezing
- Firefox anti detection options loading
- Task manager and driver pool setup
- Loading multiple URLs in parallel

### `cve_scraper.py`
Minimal example demonstrating:
- Config loading and freezing
- Task manager and driver pool setup
- Loading multiple URLs in parallel
- Waits for page load with JS API injection
- Detects bot/challenge pages before trying to parse

### `exploitdb_scraper.py`
Automates scraping Exploit-DB:
- Waits for page load with JS API injection
- Detects bot/challenge pages before trying to parse
- Parses exploit list and details with lxml
- Saves extracted comments and metadata to markdown

### `mullvad_cleaner.py`
Driver direct access example:
- Uses direct driver access instead of the task manager
- Waits for page load with JS API injection
- Detects bot/challenge pages before trying to parse
- Logging into a Mullvad account using an environment variable
- Revoking devices while keeping known ones

> Make sure to export your Mullvad token before running:
> ```bash
> export MULLVAD_ACCOUNT="9876543210"
> ```

---

Try run examples with:

```bash
python examples/basic_example.py
python examples/cve_scraper.py 
python examples/exploitdb_scraper.py
python examples/mullvad_cleaner.py
```

## Quick Usage Example

```python
from xauto.utils.config import Config
from xauto.utils.setup import get_options
from xauto.internal.geckodriver.driver import get_driver_pool
from xauto.runtime.task_manager import TaskManager

# initialize configuration you can freeze it also
config = Config()
config.freeze()

# get browser options with anti detection features
options = get_options()

# create a thread safe driver pool
driver_pool = get_driver_pool(max_size=10, firefox_options=options)

# define a task for the workers
def your_task_function(task_data, driver):
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
from xauto.runtime.lifecycle import setup_runtime, teardown_runtime

# initialize configuration
config = Config()
config.freeze()

# define your task function
def your_task_function(task_data, driver):
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

