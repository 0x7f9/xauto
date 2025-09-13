from xauto.utils.config import Config
from xauto.utils.logging import debug_logger
from xauto.utils.utility import require_connected, iframe_context
from xauto.utils.injection import (
    ensure_injected, XAUTO_CLOSEPOPUPS, XAUTO_ENABLE_DEBUG, 
)

from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import StaleElementReferenceException
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement
from typing import Optional
import random
import time

@require_connected(False)
def enable_injection_debug(driver: WebDriver) -> bool:
    if not ensure_injected(driver):
        debug_logger.debug(
            "Could not proceed with [enable_injection_debug] due to failed injection"
        )
        return False

    try:
        driver.execute_script(XAUTO_ENABLE_DEBUG)
        debug_logger.debug("[DEBUG] JavaScript debug mode enabled")
        return True
    except Exception as e:
        debug_logger.debug(f"[DEBUG] Failed to enable debug mode: {e}")
        return False

@require_connected(False)
def close_popups(driver: WebDriver) -> bool:
    if not ensure_injected(driver):
        debug_logger.debug("Could not proceed with [close_popups] due to failed injection")
        return False

    try:
        closed_count = driver.execute_script(XAUTO_CLOSEPOPUPS)
        if closed_count > 0:
            return True
    except Exception as e:
        debug_logger.error(f"[CLOSE_POPUPS] JS API call failed: {e}")

    try:
        original = driver.current_window_handle
        handles = driver.window_handles

        if len(handles) <= 1:
            return False

        for handle in handles:
            if handle == original:
                continue
            try:
                driver.switch_to.window(handle)
                driver.close()
            except Exception:
                pass

        driver.switch_to.window(original)
        return True

    except Exception as e:
        debug_logger.error(f"[CLOSE_POPUPS] Fallback popup closing failed: {e}")
        return False

@require_connected(False)
def send_key(
    driver: WebDriver,
    field: WebElement, 
    keys: str,
    check_url: bool = False,
    iframe: Optional[WebElement] = None,
    clear_field: bool = True
) -> bool:
    retries = Config.get("misc.timeouts.max_task_retries")

    for attempt in range(retries):
        try:
            with iframe_context(driver, iframe):
                before = None
                if check_url:
                    before = driver.current_url

                if clear_field:
                    field.clear()
                field.send_keys(keys)

                if check_url and before:
                    field.send_keys(Keys.RETURN)
                    from xauto.utils.page_loading import wait_for_url_change
                    wait_for_url_change(driver, before, wait_for=5)

                return True

        except StaleElementReferenceException:
            debug_logger.debug(f"[send_key] StaleElement on attempt {attempt+1}, retrying")
    
            # add re-find elements on stale errors here
            # use your method of finding elements on the page

            time.sleep(
                Config.get("misc.timeouts.task_retry_base") +
                random.uniform(0, Config.get("misc.timeouts.task_retry_jitter"))
            )

        except Exception as e:
            debug_logger.error(f"[send_key] Unexpected error: {e}")
            break

    debug_logger.debug("[send_key] All attempts failed")
    return False
