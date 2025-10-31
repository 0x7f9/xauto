#!/usr/bin/env python3

import logging
import threading
import os

MAIN_LOG_FILE = "xauto/debug_logs/monitor_details.log"
DEBUG_BOT_DETECTION_LOG_FILE = "xauto/debug_logs/debug_bot_detection.log"
DEBUG_LOG_FILE = "xauto/debug_logs/debug.log"

_logger_lock = threading.Lock()
_loggers_initialized = False

def _start_loggers() -> None:
    global _loggers_initialized
    if not _loggers_initialized:
        with _logger_lock:
            if not _loggers_initialized:
                _init_loggers()
                _loggers_initialized = True

def _init_loggers() -> None:
    os.makedirs(os.path.dirname(MAIN_LOG_FILE), exist_ok=True)
    
    monitor_details = logging.getLogger("monitor_details")
    monitor_details.setLevel(logging.DEBUG)
    if not monitor_details.handlers:
        monitor_details_handler = logging.FileHandler(MAIN_LOG_FILE, mode="w")
        monitor_details_handler.setFormatter(logging.Formatter("%(levelname)s - %(message)s"))
        monitor_details.addHandler(monitor_details_handler)

    debug_bot_detection = logging.getLogger("debug_bot_detection")
    debug_bot_detection.setLevel(logging.DEBUG)
    debug_bot_detection.propagate = False 
    if not debug_bot_detection.handlers:
        debug_bot_detection_handler = logging.FileHandler(DEBUG_BOT_DETECTION_LOG_FILE, mode="w")
        debug_bot_detection_handler.setFormatter(logging.Formatter("%(levelname)s - %(message)s"))
        debug_bot_detection.addHandler(debug_bot_detection_handler)

    debug_logger = logging.getLogger("debug")
    debug_logger.setLevel(logging.DEBUG)
    debug_logger.propagate = False      
    if not debug_logger.handlers:
        debug_handler = logging.FileHandler(DEBUG_LOG_FILE, mode="w")
        debug_handler.setFormatter(logging.Formatter("%(levelname)s - %(message)s"))
        debug_logger.addHandler(debug_handler)

    logging.getLogger("urllib3").setLevel(logging.ERROR)
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("selenium.webdriver.remote.remote_connection").setLevel(logging.WARNING)
    logging.getLogger("selenium").setLevel(logging.WARNING)
    logging.getLogger("selenium.webdriver").setLevel(logging.WARNING)
    logging.getLogger("geckodriver").setLevel(logging.WARNING)

    monitor_details.info("[INIT] Setup session with random user agents per driver")

_start_loggers()

monitor_details = logging.getLogger("monitor_details")
debug_bot_detection = logging.getLogger("debug_bot_detection")
debug_logger = logging.getLogger("debug") 