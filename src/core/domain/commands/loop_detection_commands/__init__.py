"""Loop detection command exports and helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .loop_detection_command import LoopDetectionCommand
from .tool_loop_detection_command import ToolLoopDetectionCommand
from .tool_loop_max_repeats_command import ToolLoopMaxRepeatsCommand
from .tool_loop_mode_command import ToolLoopModeCommand
from .tool_loop_ttl_command import ToolLoopTTLCommand

_LOOP_DETECTION_COMMANDS: dict[str, type[Any]] = {
    "LoopDetectionCommand": LoopDetectionCommand,
    "ToolLoopDetectionCommand": ToolLoopDetectionCommand,
    "ToolLoopMaxRepeatsCommand": ToolLoopMaxRepeatsCommand,
    "ToolLoopModeCommand": ToolLoopModeCommand,
    "ToolLoopTTLCommand": ToolLoopTTLCommand,
}

__all__ = list(_LOOP_DETECTION_COMMANDS)


def get_loop_detection_command(name: str) -> type[Any]:
    """Return a loop detection command class by ``name``."""

    try:
        return _LOOP_DETECTION_COMMANDS[name]
    except KeyError as exc:
        raise ValueError(f"Unknown loop detection command: {name}") from exc


def get_loop_detection_commands() -> Mapping[str, type[Any]]:
    """Return a copy of the registered loop detection commands."""

    return dict(_LOOP_DETECTION_COMMANDS)
