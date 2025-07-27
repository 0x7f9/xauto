#!/usr/bin/env python3

from xauto.bootstrap.build import bootstrap
if not bootstrap():
    print("Bootstrap failed")
    import sys
    sys.exit(1)

from xauto.utils.config import Config
from xauto.utils.setup import get_options
from xauto.internal.geckodriver.driver import get_driver_pool
from xauto.utils.task_manager import TaskManager
from xauto.utils.logging import debug_logger

config = Config()
config.freeze()

def get_worker_limits():
    driver_limit = Config.get("system.driver_limit")

    if str(driver_limit).lower() == "auto":
        debug_logger.info("Driver pool configured with driver_limit set to auto (unlimited scaling)")
        return float('inf'), 100

    driver_limit = int(driver_limit or 1)
    debug_logger.info(f"Driver pool configured with driver_limit = {driver_limit}")
    return driver_limit, driver_limit

def task(task_data, driver):
    url = task_data.get("url")
    driver.get(url)
    title = driver.title
    debug_logger.info(f"Visited {url}, title: {title}")
    return title

def main():
    options = get_options()

    max_drivers, max_workers = get_worker_limits()

    driver_pool = get_driver_pool(
        max_size=max_drivers,
        firefox_options=options
    )

    task_manager = TaskManager(
        driver_pool=driver_pool,
        task_processor=task,
        max_workers=max_workers
    )

    task_manager.start()

    task_manager.add_tasks([
        {"url": "https://example.com"},
        {"url": "https://www.python.org"},
        {"url": "https://github.com"},
    ])

    task_manager.wait_completion()

    task_manager.shutdown()
    driver_pool.shutdown()
    
    print("Done.")

main()

