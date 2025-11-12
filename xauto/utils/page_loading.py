from xauto.internal.geckodriver.driver import get_driver_pool
from xauto.utils.config import Config
from xauto.utils.injection import ensure_injected
from xauto.utils.logging import debug_logger
from xauto.utils.utility import require_connected

from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException
from typing import Optional
import time

_LOAD_TIME = "return window.performance.timing.loadEventEnd - window.performance.timing.navigationStart"
_SCROLL_HEIGHT = "return document.body ? document.body.scrollHeight : 0;"

def load_page_with_high_load_check(driver, url, timeout=8):
    from xauto.utils.browser_utils import close_popups
    close_popups(driver)
    
    driver_pool = get_driver_pool()
    if driver_pool:
        from xauto.internal.memory import wait_high_load
        context = "validation.navigate"
        forced = wait_high_load(driver_pool, context=context, url=url)
        if forced:
            debug_logger.warning(f"[LOAD_PAGE] Forced nav due to max_wait_time during {context}")
    
    try:
        driver.get(url)
    except Exception as e:
        debug_logger.error(f"[LOAD_PAGE] {url}: driver.get() failed: {e}")
        return False
    
    if not wait_for_page_load(driver, timeout=timeout):
        debug_logger.warning(f"[DEBUG] {url} marked invalid: wait_for_page_load() timeout")
        return False
    
    return True

@require_connected(False)
def explicit_page_load(driver: WebDriver, wait_for: Optional[float] = None) -> bool:
    from xauto.utils.browser_utils import close_popups
    close_popups(driver)

    timeout = wait_for or Config.get("misc.timeouts.max_body_load_wait")
    end_time = time.time() + timeout

    while time.time() < end_time:
        time.sleep(0.1)

    return True

@require_connected(False)
def _ensure_body_stable(driver, timeout=10, poll=0.1, since=1.0):
    if not ensure_body_loaded(driver, timeout=5):
        return False

    deadline = time.monotonic() + timeout
    last_height = driver.execute_script(_SCROLL_HEIGHT)
    stable_since = time.monotonic()

    while time.monotonic() < deadline:
        time.sleep(poll)
        height = driver.execute_script(_SCROLL_HEIGHT)
        if height != last_height:
            last_height = height
            stable_since = time.monotonic()
        elif time.monotonic() - stable_since > since:
            return
    return

@require_connected(False)
def wait_for_page_load(driver: WebDriver, timeout: Optional[float] = None) -> bool:
    from xauto.utils.browser_utils import close_popups
    close_popups(driver)
    
    t = timeout or 15
    body_load_time = Config.get("misc.timeouts.max_body_load_wait")

    if not ensure_body_loaded(driver, timeout=body_load_time):
        return False
    
    # _ensure_body_stable(driver, since=0.5)

    if not ensure_injected(driver):
        debug_logger.debug("Could not procced with [wait_for_page_load] due to failed injection")
        return False

    driver.set_script_timeout(int(t))

    s = """
        var cb = arguments[arguments.length - 1];
        try {
            if (window._xautoAPI && typeof window._xautoAPI.waitForReady === 'function') {
                window._xautoAPI.waitForReady()
                    .then(result => cb(result))
                    .catch(() => cb(false));
            } else {
                cb(false);
            }
        } catch (e) {
            cb(false);
        }
    """

    try:
        ready = None
        try:
            ready = driver.execute_async_script(s)
        except Exception as e:
            from xauto.utils.setup import network_debug
            if network_debug:
                print(
                    "driver.execute_async_script Exception\n"
                    f"Reinjecting and loading page again\n{e}")
            return False
    
        if ready:
            _ensure_body_stable(driver, timeout=5, since=1.0)
            load_time = driver.execute_script(_LOAD_TIME) / 1000.0
            debug_logger.info(f"[PAGE_LOAD] Load time: {load_time:.2f}s")
            return True
    except TimeoutException as e:
        from xauto.utils.setup import network_debug
        if network_debug:
            print("JS API.waitForReady TimeoutException\n", e)
        return False 
    except Exception as e:
        from xauto.utils.setup import network_debug
        if network_debug:
            print("JS API.waitForReady Exception\n", e)
        return False 

    return False

@require_connected(False)
def ensure_body_loaded(driver: WebDriver, timeout: Optional[float] = None) -> bool:
    timeout = timeout or float(Config.get("misc.timeouts.max_body_load_wait"))
    try:
        WebDriverWait(driver, timeout).until(lambda d: d.find_element(By.CSS_SELECTOR, "body"))  
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
    timeout = wait_for or Config.get("misc.timeouts.max_url_load_wait")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if driver.current_url != old_url:
                return True
        except Exception:
            pass
        time.sleep(0.1)
    
    return False

