#!/usr/bin/env python3

from xauto.utils.logging import debug_logger
from xauto.utils.setup import debug

from typing import Callable, Any

def shutdown_component(name: str, close_fn: Callable) -> None:
    debug_logger.info(f"{name}: shutting down")
    try:
        close_fn()
    except Exception as e:
        debug_logger.error(f"{name}: error during shutdown: {e}", exc_info=debug)

def shutdown_component_with_timeout(
    component: Any, 
    name: str, 
    timeout: float, 
    shutdown_method: str = "shutdown"
) -> None:
    if component is None:
        debug_logger.warning(f"No {name} to close")
        return
    
    debug_logger.info(f"Initiating {name} shutdown…")
    try:
        if hasattr(component, shutdown_method):
            method = getattr(component, shutdown_method)
            try:
                method(wait=True, timeout=timeout)
            except TypeError:
                method(wait=True)
        else:
            debug_logger.warning(f"{name} has no {shutdown_method} method")
    except Exception as e:
        debug_logger.error(f"Error during {name}.{shutdown_method}(): {e}", exc_info=debug)

    debug_logger.info(f"{name} closed") 