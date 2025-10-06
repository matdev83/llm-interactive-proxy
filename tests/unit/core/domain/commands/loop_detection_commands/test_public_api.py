"""Unit tests for the loop detection command registry helpers."""

from __future__ import annotations

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


@pytest.mark.parametrize(
    "command_name, expected_class",
    [
        ("LoopDetectionCommand", LoopDetectionCommand),
        ("ToolLoopDetectionCommand", ToolLoopDetectionCommand),
        ("ToolLoopMaxRepeatsCommand", ToolLoopMaxRepeatsCommand),
        ("ToolLoopModeCommand", ToolLoopModeCommand),
        ("ToolLoopTTLCommand", ToolLoopTTLCommand),
    ],
)
def test_get_loop_detection_command_returns_registered_class(
    command_name: str, expected_class: type[object]
) -> None:
    """Each public command name resolves to the corresponding command class."""

    resolved_class = get_loop_detection_command(command_name)

    assert resolved_class is expected_class


def test_get_loop_detection_command_rejects_unknown_command() -> None:
    """An informative error is raised when the command name is not registered."""

    with pytest.raises(ValueError, match="Unknown loop detection command: missing"):
        get_loop_detection_command("missing")


def test_get_loop_detection_commands_returns_copy() -> None:
    """The registry helper returns a defensive copy of the internal mapping."""

    commands = get_loop_detection_commands()

    assert commands == {
        "LoopDetectionCommand": LoopDetectionCommand,
        "ToolLoopDetectionCommand": ToolLoopDetectionCommand,
        "ToolLoopMaxRepeatsCommand": ToolLoopMaxRepeatsCommand,
        "ToolLoopModeCommand": ToolLoopModeCommand,
        "ToolLoopTTLCommand": ToolLoopTTLCommand,
    }

    commands["LoopDetectionCommand"] = object

    refreshed_commands = get_loop_detection_commands()

    assert refreshed_commands["LoopDetectionCommand"] is LoopDetectionCommand
