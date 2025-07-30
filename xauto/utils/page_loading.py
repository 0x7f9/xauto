from xauto.utils.config import Config
from xauto.utils.injection import ensure_injected
from xauto.utils.logging import debug_logger
from xauto.utils.utility import require_connected
from xauto.utils.browser_utils import close_popups

from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.by import By
import time

_LOAD_TIME = "return window.performance.timing.loadEventEnd - window.performance.timing.navigationStart"

@require_connected(False)
def explicit_page_load(driver, wait_for=None) -> bool:
    close_popups(driver)

    # driver is needed for require_connected check
    timeout = wait_for or Config.get("misc.timeouts.body_load")
    end_time = time.time() + timeout

    while time.time() < end_time:
        time.sleep(0.1)

    return True

@require_connected(False)
def wait_for_page_load(driver, timeout=None) -> bool:
    close_popups(driver)
    
    timeout = timeout or Config.get("misc.timeouts.body_load")

    if not ensure_body_loaded(driver, timeout=timeout):
        return False

    injected = ensure_injected(driver)
    if not injected:
        debug_logger.debug("Could not procced with [wait_for_page_load] due to failed injection")
        return False

    try:
        timeout = int(timeout * 1000)
        driver.execute_script(f"return window._xautoAPI.waitForReady({timeout})")
        load_time = driver.execute_script(_LOAD_TIME) / 1000.0
        debug_logger.debug(f"[PAGE_LOAD] Load time: {load_time:.2f}s")
        return True
    except Exception as e:
        debug_logger.debug(f"[PAGE_LOAD] Promise wait failed: {e}")

    return False

@require_connected(False)
def ensure_body_loaded(driver, timeout=None) -> bool:
    timeout = timeout or Config.get("misc.timeouts.body_load")
    try:
        WebDriverWait(driver, timeout).until(lambda d: d.find_element(By.CSS_SELECTOR, "body"))
        return True
    except Exception:
        debug_logger.debug("[BODY_CHECK] Body element not found within timeout")
        return False

@require_connected(False)
def wait_for_url_change(driver, old_url, wait_for=None) -> bool:
    timeout = wait_for or Config.get("misc.timeouts.url_loading")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if driver.current_url != old_url:
                return True
        except Exception:
            pass
        time.sleep(0.1)
    
    return False