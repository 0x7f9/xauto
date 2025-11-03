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
from xauto.utils.utility import counter
from xauto.utils.common import status_print 

config = Config()
config.set("proxy.enabled", False)
config.set("system.headless", False)
config.freeze()

BASE_URL = "https://www.cvedetails.com/cve/"
TARGETS_CVE = [
    {'cve_id': 'CVE-2025-54769'}, 
    {'cve_id': 'CVE-2025-54768'},
    {'cve_id': 'CVE-2025-476'}
]

def scrape(current_task, driver, tasks):
    try:
        task = tasks[current_task]
        cve_id = task['cve_id']
        url = f"{BASE_URL}{cve_id}/"
        print(f"[xauto] Loading {url}")
        driver.get(url)

        if not wait_for_page_load(driver, timeout=2):
            print("Page did not load")
            counter("failed")
            return

        if is_bot_page(driver, driver.current_url):
            print("Bot page has been detected")
            counter("invalid")
            return

        print(driver.page_source[:100])
        counter("successful")
    except:
        counter("failed")
    finally:
        counter("completed")

task_manager, driver_pool = setup_runtime(task_processor=scrape, tasks=TARGETS_CVE)
task_manager.add_tasks(range(len(TARGETS_CVE)))

# you can set the runtime up with a empty list,
# then add to the existing runtime_state and manager
# this can also be used to update the runtime
# with new tasks without restarting the current session
# task_manager, driver_pool = setup_runtime(
#     task_processor=scrape,
#     tasks=[]
# )  
# runtime_state['tasks'].extend(TARGETS_CVE)
# task_manager.tasks = TARGETS_CVE

task_manager.wait_completion()
teardown_runtime(task_manager, driver_pool)

from xauto.runtime.lifecycle import runtime_state
start_time = runtime_state['start_time']
tasks = runtime_state['tasks']
outcomes = runtime_state['outcomes']

status_print(start_time, tasks, outcomes)

print("\nDone.")
