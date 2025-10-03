"""Minimal runtime stub for the ``colorama`` package used in tests."""

from __future__ import annotations

__all__ = ["Fore", "Back", "Style", "init"]


class _BaseColor:
    RESET = ""
    BLACK = ""
    RED = ""
    GREEN = ""
    YELLOW = ""
    BLUE = ""
    MAGENTA = ""
    CYAN = ""
    WHITE = ""


class Fore(_BaseColor):
    pass


class Back(_BaseColor):
    pass


class Style:
    RESET_ALL = ""
    BRIGHT = ""
    DIM = ""
    NORMAL = ""


def init(*args, **kwargs) -> None:  # type: ignore[no-untyped-def]
    """Placeholder ``init`` implementation."""

    return None
