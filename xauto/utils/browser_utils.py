from xauto.utils.logging import debug_logger
from xauto.utils.utility import require_connected
from xauto.utils.injection import ensure_injected

@require_connected(False)
def close_popups(driver) -> bool:
    if not ensure_injected(driver):
        debug_logger.debug("Could not proceed with [close_popups] due to failed injection")
        return False

    try:
        closed_count = driver.execute_script("return window._xautoAPI.closePopups?.() ?? 0")
        if closed_count > 0:
            return True
    except Exception as e:
        debug_logger.debug(f"[CLOSE_POPUPS] JS API call failed: {e}")

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
        debug_logger.debug(f"[CLOSE_POPUPS] Fallback popup closing failed: {e}")
        return False

