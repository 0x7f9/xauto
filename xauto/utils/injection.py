from xauto.utils.logging import debug_logger
from xauto.utils.utility import require_connected

from pathlib import Path

_XAUTO_PATH = Path("xauto/internal/js/xauto_api.js")

if not _XAUTO_PATH.is_file():
    raise FileNotFoundError(f"Missing API file: {_XAUTO_PATH.resolve()}")

@require_connected(False)
def ensure_injected(driver) -> bool:
    try:
        curr = driver.current_url
    except Exception:
        return False

    if curr != getattr(driver, "_last_url", None):
        driver._is_injected = False
        driver._last_url = curr

    try:
        injected = bool(driver.execute_script(
            "return document.documentElement.getAttribute('data-injected')")
        )
    except Exception:
        injected = False

    if not injected and not getattr(driver, "_is_injected", False):
        success = _inject_api(driver)
        driver._is_injected = success
        return success

    driver._is_injected = True
    return True

@require_connected(False)
def _inject_api(driver) -> bool:
    try:
        exe = driver.execute_script
        exe(_XAUTO_PATH.read_text(encoding="utf-8"))

        injected = (
            bool(driver.execute_script("return document.documentElement.getAttribute('data-injected')")) and
            driver.execute_script("return typeof window._xautoAPI === 'object' && Object.isFrozen(window._xautoAPI)")
        )

        driver._is_injected = injected
        if injected:
            driver._last_url = driver.current_url

        return injected
    except Exception as e:
        debug_logger.debug(f"[JS_INJECTION] Failed to inject: {e}")
        driver._is_injected = False
        return False

