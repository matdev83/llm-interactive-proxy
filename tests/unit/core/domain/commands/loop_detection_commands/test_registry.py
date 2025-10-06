"""Tests for loop detection command registry helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from src.core.domain.commands.loop_detection_commands import (
    LoopDetectionCommand,
    ToolLoopDetectionCommand,
    ToolLoopMaxRepeatsCommand,
    ToolLoopModeCommand,
    ToolLoopTTLCommand,
    get_loop_detection_command,
    get_loop_detection_commands,
)

EXPECTED_COMMANDS: Mapping[str, type[Any]] = {
    "LoopDetectionCommand": LoopDetectionCommand,
    "ToolLoopDetectionCommand": ToolLoopDetectionCommand,
    "ToolLoopMaxRepeatsCommand": ToolLoopMaxRepeatsCommand,
    "ToolLoopModeCommand": ToolLoopModeCommand,
    "ToolLoopTTLCommand": ToolLoopTTLCommand,
}


@pytest.mark.parametrize("command_name, command_cls", EXPECTED_COMMANDS.items())
def test_get_loop_detection_command_returns_registered_class(
    command_name: str, command_cls: type[Any]
) -> None:
    """Each known command name resolves to its registered class."""

    resolved = get_loop_detection_command(command_name)

    assert resolved is command_cls


def test_get_loop_detection_command_unknown_name() -> None:
    """An unknown command name raises a clear ``ValueError``."""

    with pytest.raises(ValueError, match="Unknown loop detection command: unknown"):
        get_loop_detection_command("unknown")


def test_get_loop_detection_commands_returns_copy() -> None:
    """Mutating a retrieved mapping does not affect the registry state."""

    commands = get_loop_detection_commands()

    # Baseline sanity check for returned mapping contents.
    assert commands == EXPECTED_COMMANDS

    # Mutate the mapping and ensure a subsequent call is unaffected.
    mutable_commands = dict(commands)
    mutable_commands["LoopDetectionCommand"] = type(
        "DummyLoopDetectionCommand",
        (),
        {},
    )

    fresh_commands = get_loop_detection_commands()

    assert fresh_commands == EXPECTED_COMMANDS
