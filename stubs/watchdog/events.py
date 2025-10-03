"""Minimal subset of watchdog.events used in tests."""

from __future__ import annotations

__all__ = ["FileSystemEventHandler"]


class FileSystemEventHandler:  # pragma: no cover - behaviorless stub
    def on_any_event(self, _event) -> None:
        pass

    def on_created(self, _event) -> None:
        pass

    def on_modified(self, _event) -> None:
        pass

    def on_deleted(self, _event) -> None:
        pass
