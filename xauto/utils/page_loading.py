from xauto.internal.geckodriver.driver import get_driver_pool
from xauto.utils.config import Config
from xauto.utils.injection import ensure_injected
from xauto.utils.logging import debug_logger, monitor_details as md
from xauto.utils.utility import require_connected

from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException
from typing import Optional
import time

_LOAD_TIME = "return window.performance.timing.loadEventEnd - window.performance.timing.navigationStart"
_SCROLL_HEIGHT = "return document.body.scrollHeight;"

def load_page_with_high_load_check(driver, url, timeout=8):
    from xauto.utils.browser_utils import close_popups
    close_popups(driver)
    
    driver_pool = get_driver_pool()
    if driver_pool:
        from xauto.internal.memory import wait_high_load
        forced = wait_high_load(driver_pool, context="validation.navigate", url=url)
        driver._forced_navigation = forced
    
    try:
        driver.get(url)
    except Exception as e:
        md.info(f"[DEBUG] {url} marked invalid: driver.get() failed: {e}")
        return False
    
    if not wait_for_page_load(driver, timeout=timeout):
        md.info(f"[DEBUG] {url} marked invalid: wait_for_page_load() timeout")
        return False
    
    return True

@require_connected(False)
def explicit_page_load(driver: WebDriver, wait_for: Optional[float] = None) -> bool:
    from xauto.utils.browser_utils import close_popups
    close_popups(driver)

    timeout = wait_for or Config.get("misc.timeouts.body_load")
    end_time = time.time() + timeout

    while time.time() < end_time:
        time.sleep(0.1)

    return True

@require_connected(False)
def ensure_body_stable(driver, timeout=10, poll=0.1):
    deadline = time.monotonic() + timeout
    last_height = driver.execute_script(_SCROLL_HEIGHT)
    stable_since = time.monotonic()

    while time.monotonic() < deadline:
        time.sleep(poll)
        height = driver.execute_script(_SCROLL_HEIGHT)
        if height != last_height:
            last_height = height
            stable_since = time.monotonic()
        elif time.monotonic() - stable_since > 1:
            return True
    return False

@require_connected(False)
def wait_for_page_load(driver: WebDriver, timeout: Optional[float] = None) -> bool:
    from xauto.utils.browser_utils import close_popups
    close_popups(driver)
    
    load_time = Config.get("misc.timeouts.body_load")
    t = timeout or load_time

    if not ensure_body_loaded(driver, timeout=timeout):
        return False

    if not ensure_injected(driver):
        debug_logger.debug("Could not procced with [wait_for_page_load] due to failed injection")
        return False

    driver.set_script_timeout(int(t + 2))

    s = """
        var cb = arguments[arguments.length - 1];
        var timeout = arguments[0] || 10000;

        try {
            if (window._xautoAPI && typeof window._xautoAPI.waitForReady === 'function') {
                window._xautoAPI.waitForReady(timeout)
                    .then(result => cb(result))
                    .catch(() => cb(false));
            } else {
                cb(false);
            }
        } catch (e) {
            cb(false);
        }
    """

    deadline = time.monotonic() + t
    while time.monotonic() < deadline:
        try:
            ready = driver.execute_async_script(
                s, int(max(0, (deadline - time.monotonic()) * 1000))
            )
            if ready:
                ensure_body_stable(driver, timeout=5)
                load_time = driver.execute_script(_LOAD_TIME) / 1000.0
                debug_logger.debug(f"[PAGE_LOAD] Load time: {load_time:.2f}s")
                return True
        except TimeoutException:
            continue 
        except Exception:
            break

    return False

@require_connected(False)
def ensure_body_loaded(driver: WebDriver, timeout: Optional[float] = None) -> bool:
    timeout = timeout or Config.get("misc.timeouts.body_load")
    try:
        WebDriverWait(driver, timeout).until(lambda d: d.find_element(By.CSS_SELECTOR, "body"))  # type: ignore
        return True
    except Exception:
        debug_logger.debug("[BODY_CHECK] Body element not found within timeout")
        return False

@require_connected(False)
def wait_for_url_change(
    driver: WebDriver, 
    old_url: str, 
    wait_for: Optional[float] = None
) -> bool:
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

