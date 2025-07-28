#!/usr/bin/env python3
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from xauto.bootstrap.build import bootstrap
if not bootstrap():
    print("ERROR: Bootstrap failed. Cannot proceed.")
    sys.exit(1)

from xauto.utils.setup import get_options
from xauto.internal.geckodriver.driver import get_driver_pool
from xauto.utils.page_loading import wait_for_page_load
from xauto.utils.validation import is_bot_page
from selenium.webdriver.common.by import By
from time import sleep
import os

TOKEN = os.environ.get("MULLVAD_ACCOUNT")
if not TOKEN:
    raise RuntimeError("Missing MULLVAD_ACCOUNT environment variable")

KEEP_NAMES = {
    "list of names to not revoke",
}

def login_to_mullvad(driver):
    driver.get("https://mullvad.net/en/account/login")

    if not wait_for_page_load(driver):
        print("Page did not load")
        return
    
    if is_bot_page(driver, driver.current_url):
        print("Bot page has been detected")
        return
    
    try:
        input = driver.find_element(By.NAME, "account_number")
        input.send_keys(TOKEN)
        sleep(0.3)

        btn = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
        btn.click()

        sleep(2)  
        print("[xauto] Logged into Mullvad account.")
    except Exception as e:
        print(f"[xauto] Error in login_to_mullvad function: {e}")

def revoke_devices(driver):
    driver.get("https://mullvad.net/en/account/devices")
    sleep(2)

    from xauto.utils.validation import is_browser_error_page
    if is_browser_error_page(driver):
        print("[xauto] Browser error page detected. Exiting.")
        return

    devices = driver.find_elements(By.CLASS_NAME, "device-header")
    print(f"[xauto] Found {len(devices)} devices.")

    for header in devices:
        try:
            name = header.find_element(By.TAG_NAME, "h2").text.strip().lower()
            if name in KEEP_NAMES:
                print(f"[xauto] Keeping device: {name}")
                continue

            xpath = header.find_element(By.XPATH, "..")
            form = xpath.find_element(By.TAG_NAME, "form")
            submit = form.find_element(By.CSS_SELECTOR, "button[type='submit']")
            print(f"[xauto] Revoking device: {name}")
            submit.click()
            sleep(1.5)
        except Exception as e:
            print(f"[xauto] Error in revoke_devices function: {e}")

def run():
    options = get_options()
    driver_pool = get_driver_pool(max_size=1, firefox_options=options)
    driver = None

    try:
        driver = driver_pool.get_driver()
        if driver is None:
            print("[xauto] ERROR: Failed to acquire driver from pool")
            return

        login_to_mullvad(driver)
        revoke_devices(driver)

    except Exception as e:
        print(f"[xauto] Error in run function: {e}")

    finally:
        if driver is not None:
            driver_pool.return_driver(driver)
        driver_pool.shutdown()


print("[xauto] Starting Mullvad auto clean loop.")
while True:
    run()
    print("[xauto] Sleeping for 5 minutes...\n")
    sleep(5 * 60)
