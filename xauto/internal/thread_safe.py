#!/usr/bin/env python3

from xauto.utils.logging import debug_logger

from typing import Any, List, Optional, Iterator
from collections import deque
import threading

class SafeThread(threading.Thread):
    def __init__(self, target_fn=None, name=None, **kwargs):
        super().__init__(name=name, daemon=True)
        self._fn = target_fn
        self._args = ()
        self._kwargs = kwargs
        
    def run(self):
        try:
            if self._fn:
                self._fn(**self._kwargs)
        except Exception as e:
            from xauto.utils.setup import debug
            fn_name = getattr(self._fn, '__name__', 'unknown_function') if self._fn else 'unknown_function'
            debug_logger.error(f"Thread error in {fn_name}: {e}", exc_info=debug)


class AtomicCounter:
    def __init__(self, initial_value: int = 0):
        self._value = initial_value
        self._lock = threading.Lock()
        
    def increment(self):
        with self._lock:
            self._value += 1
    
    def decrement(self):
        with self._lock:
            self._value -= 1

    def reset(self):
        with self._lock:
            self._value = 0
    
    def get(self) -> int:
        with self._lock:
            return self._value


class RingBuffer:
    def __init__(self, max_size: int):
        if max_size <= 0:
            raise ValueError("max_size must be > 0")
        self.max_size = max_size
        self._buffer = deque()
        self._sum = 0.0
        self._lock = threading.RLock()

    def __len__(self) -> int:
        with self._lock:
            return len(self._buffer)

    def __iter__(self) -> Iterator[float]:
        with self._lock:
            snapshot = list(self._buffer)
        return iter(snapshot)
    
    def append(self, item: float) -> None:
        with self._lock:
            if len(self._buffer) >= self.max_size:
                evicted = self._buffer.popleft()
                self._sum -= float(evicted)
            self._buffer.append(item)
            self._sum += float(item)

    def pop(self, index: int = -1) -> float:
        with self._lock:
            if not self._buffer:
                raise IndexError("pop from empty RingBuffer")
            if index == 0:
                value = self._buffer.popleft()
            elif index == -1:
                value = self._buffer.pop()
            else:
                buf = list(self._buffer)
                value = buf.pop(index)
                self._buffer = deque(buf, maxlen=self.max_size)
            self._sum -= float(value)
            return value

    def clear(self) -> None:
        with self._lock:
            self._buffer.clear()
            self._sum = 0.0

    def copy(self) -> List[Any]:
        with self._lock:
            return list(self._buffer)

    def snapshot(self) -> List[Any]:
        return self.copy()

    @property
    def rolling_sum(self) -> float:
        with self._lock:
            return self._sum


class ThreadSafeList:
    def __init__(self, max_size: Optional[int] = None):
        self._lock = threading.RLock()
        if max_size is not None:
            self._list = RingBuffer(max_size)
            self._bounded = True
        else:
            self._list = []
            self._bounded = False

    def __len__(self) -> int:
        with self._lock:
            return len(self._list)

    def __iter__(self) -> Iterator[Any]:
        with self._lock:
            return iter(self._list.copy())
        
    def append(self, item: Any) -> None:
        with self._lock:
            self._list.append(item)

    def bounded_append(self, item: Any, max_size: int) -> None:
        with self._lock:
            self._list.append(item)
            while not self._bounded and len(self._list) > max_size:
                self._list.pop(0)

    def clear(self) -> None:
        with self._lock:
            self._list.clear()

    def copy(self) -> List[Any]:
        with self._lock:
            if self._bounded:
                return self._list.copy()
            else:
                return self._list.copy()

    def snapshot(self) -> List[Any]:
        return self.copy()

    @property
    def rolling_sum(self) -> float:
        with self._lock:
            if self._bounded:
                if isinstance(self._list, RingBuffer):
                    return self._list.rolling_sum
            return 0.0


class ThreadSafeSet:
    def __init__(self, iterable=None):
        self._set = set(iterable) if iterable else set()
        self._lock = threading.Lock()
    
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
    
    def add(self, item: Any) -> None:
        with self._lock:
            self._set.add(item)
    
    def clear(self) -> None:
        with self._lock:
            self._set.clear()
    

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
        
    def get(self, key: Any, default: Any = None) -> Any:
        with self._lock:
            return self._dict.get(key, default)
    
    def clear(self) -> None:
        with self._lock:
            self._dict.clear()
    
    def pop(self, key: Any, default: Any = None) -> Any:
        with self._lock:
            return self._dict.pop(key, default)

    def items(self):
        with self._lock:
            return list(self._dict.items())

    def values(self):
        with self._lock:
            return list(self._dict.values())
        
