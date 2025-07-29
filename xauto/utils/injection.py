from xauto.utils.logging import debug_logger
from selenium.common.exceptions import WebDriverException
from pathlib import Path

_XAUTO_PATH = Path("xauto/internal/js/xauto_api.js")

if not _XAUTO_PATH.is_file():
    raise FileNotFoundError(f"Missing API file: {_XAUTO_PATH.resolve()}")

_XAUTO_API = _XAUTO_PATH.read_text(encoding="utf-8")

def ensure_injected(driver):
    curr = driver.current_url
    if curr != getattr(driver, "_last_url", None):
        driver._is_injected = False
        driver._last_url = curr
    else:
        try:
            dirty = driver.execute_script("return window._pageDirty === true")
            if dirty:
                driver._is_injected = False
                driver.execute_script("window._pageDirty = false")
        except WebDriverException:
            driver._is_injected = False

    injected = bool(driver.execute_script(
        "return document.documentElement.getAttribute('data-injected')"))

    if not injected and not getattr(driver, "_is_injected", False):
        _inject_api(driver)

def _inject_api(driver):
    try:
        exe = driver.execute_script
        exe(_XAUTO_API)

        injected = bool(driver.execute_script(
            "return document.documentElement.getAttribute('data-injected')")
        )

        if not injected:
            driver._is_injected = False
            return False

        driver._is_injected = True
        driver._last_url = driver.current_url

        return True
    except Exception as e:
        debug_logger.debug(f"[JS_INJECTION] Failed to inject: {e}")
        driver._is_injected = False
        return False
