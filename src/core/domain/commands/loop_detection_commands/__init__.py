"""Loop detection command exports and helpers."""

from __future__ import annotations

# pyright: reportUnsupportedDunderAll=false
from typing import Any

from .loop_detection_command import LoopDetectionCommand

_LOOP_DETECTION_COMMANDS: dict[str, type[Any]] = {
    "LoopDetectionCommand": LoopDetectionCommand,
}


def get_loop_detection_command(name: str) -> type[Any]:
    """Return a loop detection command class by ``name``."""

    try:
        return _LOOP_DETECTION_COMMANDS[name]
    except KeyError as exc:
        raise ValueError(f"Unknown loop detection command: {name}") from exc


def get_loop_detection_commands() -> dict[str, type[Any]]:
    """Return a copy of the registered loop detection commands."""

    return dict(_LOOP_DETECTION_COMMANDS)


__all__ = [
    *list(_LOOP_DETECTION_COMMANDS),
]
