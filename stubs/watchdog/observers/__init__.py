"""Minimal watchdog.observers stub used during tests."""

from __future__ import annotations

__all__ = ["Observer", "api"]


class Observer:  # pragma: no cover - behaviorless stub
    def schedule(self, *_args, **_kwargs) -> None:
        pass

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def join(self, *_args, **_kwargs) -> None:
        pass


class _BaseObserver:  # pragma: no cover - behaviorless stub
    def schedule(self, *_args, **_kwargs) -> None:
        pass

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def join(self, *_args, **_kwargs) -> None:
        pass


class api:  # pragma: no cover - behaviorless stub module
    BaseObserver = _BaseObserver
