import time

class ResourceStats:
    __slots__ = ('memory', 'cpu')

    def __init__(self, memory: float, cpu: float):
        self.memory = memory
        self.cpu = cpu


class TaskWrapper:
    __slots__ = ('task', 'retry_count')
    
    def __init__(self, task: int):
        self.task = task
        self.retry_count = 0


class DriverInfo:
    __slots__ = ('pids', 'last_access', 'heap_timestamp', 'failure_count')
    
    def __init__(self, pids: list[int]):
        self.pids = pids
        self.last_access = time.monotonic()
        self.heap_timestamp = self.last_access
        self.failure_count = 0
        
        