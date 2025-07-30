#!/usr/bin/env python3

import os 
import sys 
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from xauto.bootstrap.build import bootstrap
if not bootstrap():
    print("Bootstrap failed")
    sys.exit(1)
    
from xauto.utils.config import Config
from xauto.runtime.lifecycle import setup_runtime, teardown_runtime
from xauto.utils.page_loading import wait_for_page_load
from xauto.utils.validation import is_bot_page

import lxml.html

config = Config()
config.set("proxy.enabled", False)
config.set("driver.headless", True)
config.freeze()

BASE_URL = "https://www.cvedetails.com/cve/"
TARGETS_CVE = [
    {'cve_id': 'CVE-2025-54769'}, 
    {'cve_id': 'CVE-2025-54768'},
    {'cve_id': 'CVE-2025-476'}
]

def scrape(task, driver):
    cve_id = task['cve_id']
    url = f"{BASE_URL}{cve_id}/"
    print(f"[xauto] Loading {url}")
    driver.get(url)

    if not wait_for_page_load(driver, timeout=2):
        print("Page did not load")
        return

    if is_bot_page(driver, driver.current_url):
        print("Bot page has been detected")
        return

    root = lxml.html.fromstring(driver.page_source)
    print(root)
    return

task_manager, driver_pool = setup_runtime(task_processor=scrape)

for task in TARGETS_CVE:
    task_manager.add_task(task)

task_manager.wait_completion()
teardown_runtime(task_manager, driver_pool)

print("\nDone.")