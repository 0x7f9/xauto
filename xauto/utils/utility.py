#!/usr/bin/env python3

from xauto.utils.logging import debug_logger

from selenium.common.exceptions import WebDriverException
from selenium.webdriver.remote.webdriver import WebDriver
from typing import Any, Generator, Optional, Set
from contextlib import contextmanager
import functools
import os
import mmap

@contextmanager
def iframe_context(
    driver: WebDriver, 
    iframe: Optional[Any] = None
) -> Generator[None, None, None]:
    if iframe:
        driver.switch_to.frame(iframe)
    try:
        yield
    finally:
        if iframe:
            driver.switch_to.default_content()

def check_driver_liveness(driver: WebDriver) -> bool:
    try:
        driver.execute_script("return 1")
        return True
    except WebDriverException as e:
        debug_logger.debug(f"Driver liveness check failed – session dead: {e}")
        return False

def require_connected(default: Any) -> Any:
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(driver, *args, **kwargs) -> bool:
            if not check_driver_liveness(driver):
                debug_logger.debug(f"{fn.__name__}: driver not connected or dead, skipping")
                return default
            return fn(driver, *args, **kwargs)
        return wrapper
    return decorator

def fnv1a_hash(key: Any) -> int:
    key_str = str(key)
    if len(key_str) < 32:
        return hash(key_str)
    
    data = key_str.encode('utf-8')
    h = 0xcbf29ce484222325
    for byte in data:
        h ^= byte
        h *= 0x100000001b3
        h &= 0xffffffffffffffff
    return h 

def open_file_ro(path: str) -> Optional[int]:
    try:
        return os.open(path, os.O_RDONLY | os.O_CLOEXEC)
    except OSError:
        return None

def open_file_rw(path: str, mode: int = 0o600) -> Optional[int]:
    try:
        return os.open(path, os.O_CREAT | os.O_RDWR | os.O_CLOEXEC, mode)
    except OSError:
        return None
    
def create_memory_mapped_file(fd: int, size: int, access: int = mmap.ACCESS_WRITE) -> Optional[mmap.mmap]:
    try:
        return mmap.mmap(fd, size, access=access)
    except OSError:
        return None
    
def truncate_file(fd: int, size: int) -> bool:
    try:
        os.ftruncate(fd, size)
        return True
    except OSError:
        return False

def read_wordlist(filepath: str) -> Set[str]:
    wordlist = set()
    fd = open_file_ro(filepath)
    if fd is None:
        print(f"File not found {filepath}")
        return wordlist

    try:
        with os.fdopen(fd, "r") as f:
            for line in f:
                line = line.strip().lower()
                if not line or line.startswith("#"):
                    continue
                wordlist.add(line)
    except OSError:
        pass
    return wordlist

def counter(name):
    from xauto.runtime.lifecycle import runtime_state
    outcomes = runtime_state.get('outcomes')
    if not outcomes:
        return
    counter = outcomes.get(name)
    if counter:
        counter += 1

        