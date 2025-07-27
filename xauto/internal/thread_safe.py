#!/usr/bin/env python3

from typing import Any, List, Optional, Iterator
from collections import deque
import threading

class AtomicCounter:
    def __init__(self, initial_value: int = 0):
        self._value = initial_value
        self._lock = threading.Lock()
    
    def __int__(self) -> int:
        with self._lock:
            return self._value
    
    def __iadd__(self, other: int) -> 'AtomicCounter':
        with self._lock:
            self._value += other
            return self
    
    def __isub__(self, other: int) -> 'AtomicCounter':
        with self._lock:
            self._value -= other
            return self
    

class RingBuffer:
    def __init__(self, max_size: int):
        self.max_size = max_size
        self._buffer = deque(maxlen=max_size)
        self._sum = 0.0
        self._lock = threading.RLock()
    
    def append(self, item: Any) -> None:
        with self._lock:
            if len(self._buffer) >= self.max_size:
                self._sum -= self._buffer[0]
            self._buffer.append(item)
            self._sum += item
    
    def clear(self) -> None:
        with self._lock:
            self._buffer.clear()
            self._sum = 0.0
    
    def __len__(self) -> int:
        with self._lock:
            return len(self._buffer)
    
    def __iter__(self) -> Iterator[Any]:
        with self._lock:
            buf = list(self._buffer)
        return iter(buf)
    
    def snapshot(self) -> List[Any]:
        with self._lock:
            return list(self._buffer)
    

class ThreadSafeList:
    def __init__(self, max_size: Optional[int] = None):
        self._lock = threading.RLock()
        if max_size is not None:
            self._list = RingBuffer(max_size)
        else:
            self._list = []
    
    def __iter__(self):
        with self._lock:
            if isinstance(self._list, RingBuffer):
                buf = list(self._list._buffer)
            else:
                buf = self._list.copy()
        return iter(buf)

    def append(self, item: Any) -> None:
        with self._lock:
            self._list.append(item)
    
    def clear(self) -> None:
        with self._lock:
            self._list.clear()
    
    def __len__(self) -> int:
        with self._lock:
            return len(self._list)
    
    def bounded_append(self, item: Any, max_size: int) -> None:
        with self._lock:
            if isinstance(self._list, RingBuffer):
                self._list.append(item)
            else:
                self._list.append(item)
                while len(self._list) > max_size:
                    self._list.pop(0)

class ThreadSafeSet:
    def __init__(self, iterable=None):
        self._set = set(iterable) if iterable else set()
        self._lock = threading.Lock()
    
    def add(self, item: Any) -> None:
        with self._lock:
            self._set.add(item)
    
    def clear(self) -> None:
        with self._lock:
            self._set.clear()
    
    def __len__(self) -> int:
        with self._lock:
            return len(self._set)
    
    def __contains__(self, item: Any) -> bool:
        with self._lock:
            return item in self._set
    
    def __iter__(self):
        with self._lock:
            items = tuple(self._set)
        return iter(items)


class ThreadSafeDict:
    def __init__(self):
        self._dict = {}
        self._lock = threading.Lock()
    
    def __getitem__(self, key: Any) -> Any:
        with self._lock:
            return self._dict[key]
    
    def __setitem__(self, key: Any, value: Any) -> None:
        with self._lock:
            self._dict[key] = value
    
    def get(self, key: Any, default: Any = None) -> Any:
        with self._lock:
            return self._dict.get(key, default)
    
    def clear(self) -> None:
        with self._lock:
            self._dict.clear()
    
    def __len__(self) -> int:
        with self._lock:
            return len(self._dict)
    
    def __iter__(self):
        with self._lock:
            keys = list(self._dict.keys())
        return iter(keys)
    
    def __contains__(self, key: Any) -> bool:
        with self._lock:
            return key in self._dict