from xauto.utils.logging import debug_logger
from xauto.utils.utility import require_connected
from xauto.utils.injection import ensure_injected

CLOSE_POPUPS = "return window._xautoAPI.closePopups()"

@require_connected(None)
def close_popups(driver) -> None:
    injected = ensure_injected(driver)
    if not injected:
        debug_logger.debug("Could not procced with [close_popups] due to failed injection")
        return
    
    try:
        closed_count = driver.execute_script(CLOSE_POPUPS)
        if closed_count > 0:
            return
    except Exception as e:
        debug_logger.debug(f"[CLOSE_POPUPS] JS API call failed: {e}")

    try:
        original = driver.current_window_handle
        handles = driver.window_handles
        
        if len(handles) <= 1:
            return
            
        switch = driver.switch_to
        
        for h in handles:
            if h == original:
                continue
            try:
                switch.window(h)
                driver.close()
            except Exception:
                pass
            
        switch.window(original)
        
    except Exception as e:
        debug_logger.debug(f"[CLOSE_POPUPS] Fallback popup closing failed: {e}")