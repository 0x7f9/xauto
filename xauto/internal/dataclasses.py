import time
from dataclasses import dataclass
from typing import Optional
from selenium.webdriver.remote.webelement import WebElement

class ResourceStats:
    __slots__ = ('memory', 'cpu')

    def __init__(self, memory: float, cpu: float):
        self.memory = memory
        self.cpu = cpu


class TaskWrapper:
    __slots__ = ('idx', 'retry_count', 'tasks')
    
    def __init__(self, idx: int, tasks: Optional[list] = None):
        self.idx = idx
        self.retry_count = 0
        self.tasks = tasks 


class DriverInfo:
    __slots__ = ('pids', 'last_access', 'heap_timestamp', 'failure_count')
    
    def __init__(self, pids: list[int]):
        self.pids = pids
        self.last_access = time.monotonic()
        self.heap_timestamp = self.last_access
        self.failure_count = 0

        