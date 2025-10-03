"""Minimal runtime stub for the colorama package used in tests."""

from __future__ import annotations

__all__ = ["init", "deinit", "Fore", "Back", "Style"]


def init(*_args, **_kwargs) -> None:  # pragma: no cover - behaviorless stub
    """No-op replacement for :func:`colorama.init`."""


def deinit() -> None:  # pragma: no cover - behaviorless stub
    """No-op replacement for :func:`colorama.deinit`."""


class _ColorAttributes:
    def __getattr__(self, _name: str) -> str:  # pragma: no cover - trivial return
        return ""


Fore = _ColorAttributes()
Back = _ColorAttributes()
Style = _ColorAttributes()
Style.RESET_ALL = ""
