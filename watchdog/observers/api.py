"""Core observer base class stub."""
from __future__ import annotations


class BaseObserver:
    """Base observer exposing schedule for compatibility."""

    def schedule(self, handler: object, path: str, recursive: bool = False) -> None:  # pragma: no cover - stub
        del handler, path, recursive
        return None
