from xauto.utils.logging import debug_logger
from xauto.utils.utility import require_connected

from pathlib import Path
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.remote.webdriver import WebDriver
from typing import Any

_XAUTO_PATH = Path("xauto/internal/js/xauto_api.js")

if not _XAUTO_PATH.is_file():
    raise FileNotFoundError(f"Missing API file: {_XAUTO_PATH.resolve()}")

XAUTO_CLOSEPOPUPS = "return window._xautoAPI.closePopups?.() ?? 0"
XAUTO_ENABLE_DEBUG = "return window._xautoAPI.enableDebug()"

@require_connected(False)
def ensure_injected(driver: WebDriver) -> bool:
    try:
        injected = driver.execute_script(
            "return !!(window._xautoAPI && "
            "typeof window._xautoAPI === 'object' && "
            "Object.isFrozen(window._xautoAPI));"
        )
    except WebDriverException:
        injected = False
    except Exception:
        injected = False

    if not injected:
        return _inject_api(driver)

    return True

@require_connected(False)
def _inject_api(driver: WebDriver) -> bool:
    try:
        driver.execute_script(_XAUTO_PATH.read_text(encoding="utf-8"))

        injected = driver.execute_script(
            "return !!(document.documentElement.getAttribute('data-injected') && "
            "window._xautoAPI && typeof window._xautoAPI === 'object' && Object.isFrozen(window._xautoAPI));"
        )

        return bool(injected)
    except WebDriverException as e:
        debug_logger.debug(f"[JS_INJECTION] Execution error during inject: {e}")
        return False
    except Exception as e:
        debug_logger.debug(f"[JS_INJECTION] Failed to inject: {e}")
        return False

def wrap_driver_with_injection(driver: WebDriver) -> WebDriver:
    _orig_get = driver.get

    def get_injected_driver(url: str, *args: Any, **kwargs: Any) -> Any:
        result = _orig_get(url, *args, **kwargs)
        ensure_injected(driver)
        return result

    driver.get = get_injected_driver
    return driver

