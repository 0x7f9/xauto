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

        