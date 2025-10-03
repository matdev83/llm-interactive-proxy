"""Minimal event definitions used in tests."""
from __future__ import annotations


class FileSystemEventHandler:
    """Stub event handler."""

    def on_any_event(self, event: object) -> None:  # pragma: no cover - simple stub
        del event
