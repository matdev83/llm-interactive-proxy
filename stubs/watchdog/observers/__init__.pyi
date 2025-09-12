from __future__ import annotations

from typing import Any

from .api import BaseObserver as BaseObserver

class Observer(BaseObserver):
    def __init__(self, *args: Any, **kwargs: Any) -> None: ...
