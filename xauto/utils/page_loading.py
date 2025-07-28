from xauto.utils.injection import ensure_injected
from xauto.utils.logging import debug_logger
from xauto.utils.utility import require_connected
from xauto.utils.config import Config

from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.by import By
import time

_LOAD_TIME = "return window.performance.timing.loadEventEnd - window.performance.timing.navigationStart"

@require_connected(False)
def explicit_page_load(driver, timeout=None):
    # driver is used for require_connected check
    timeout = timeout or Config.get("misc.timeouts.body_load")
    end_time = time.time() + timeout

    while time.time() < end_time:
        time.sleep(0.1)

    return True

@require_connected(False)
def wait_for_page_load(driver, timeout=None):
    timeout = timeout or Config.get("misc.timeouts.body_load")

    if not ensure_body_loaded(driver, timeout=timeout):
        return False

    ensure_injected(driver)

    injected = bool(driver.execute_script(
        "return document.documentElement.getAttribute('data-injected')"))

    if injected:
        try:
            js_timeout_ms = int(timeout * 1000)
            driver.execute_script(f"return window._xautoAPI.waitForReady({js_timeout_ms})")
            load_time = driver.execute_script(_LOAD_TIME) / 1000.0
            debug_logger.debug(f"[PAGE_LOAD] Load time: {load_time:.2f}s")
            return True
        except Exception as e:
            debug_logger.debug(f"[PAGE_LOAD] Promise wait failed: {e}")

    return False

@require_connected(False)
def ensure_body_loaded(driver, timeout=None):
    timeout = timeout or Config.get("misc.timeouts.body_load")
    try:
        WebDriverWait(driver, timeout).until(lambda d: d.find_element(By.CSS_SELECTOR, "body"))
        return True
    except Exception:
        debug_logger.debug("[BODY_CHECK] Body element not found within timeout")
        return False
