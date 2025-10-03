"""Minimal watchdog.observers implementation."""

from __future__ import annotations

__all__ = ["Observer"]


class Observer:
    """Stub Observer that exposes required interface for tests."""

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def join(self, timeout: float | None = None) -> None:
        return None
