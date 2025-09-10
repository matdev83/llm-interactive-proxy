from __future__ import annotations

import threading
from collections import defaultdict

_lock = threading.Lock()
_counters: dict[str, int] = defaultdict(int)


def inc(name: str, by: int = 1) -> None:
    with _lock:
        _counters[name] += by


def get(name: str) -> int:
    with _lock:
        return int(_counters.get(name, 0))


def snapshot() -> dict[str, int]:
    with _lock:
        return dict(_counters)
