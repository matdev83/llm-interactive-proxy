"""Stub observer implementation for tests."""
from __future__ import annotations

from .api import BaseObserver


class Observer(BaseObserver):
    """Simplified observer that satisfies the interface."""

    def start(self) -> None:  # pragma: no cover - simple stub
        return None

    def stop(self) -> None:  # pragma: no cover - simple stub
        return None

    def join(self, timeout: float | None = None) -> None:  # pragma: no cover - simple stub
        del timeout
        return None
