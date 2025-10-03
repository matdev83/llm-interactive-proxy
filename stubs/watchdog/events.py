"""Minimal watchdog.events implementation for tests."""

from __future__ import annotations

__all__ = ["FileSystemEventHandler"]


class FileSystemEventHandler:
    """Placeholder handler with no behavior."""

    def on_modified(self, event) -> None:  # type: ignore[no-untyped-def]
        return None

    def on_created(self, event) -> None:  # type: ignore[no-untyped-def]
        return None

    def on_deleted(self, event) -> None:  # type: ignore[no-untyped-def]
        return None

    def on_moved(self, event) -> None:  # type: ignore[no-untyped-def]
        return None
