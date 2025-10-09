"""Tests for the loop detection command registry helpers."""

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
    ("command_name", "expected_class"),
    [
        ("LoopDetectionCommand", LoopDetectionCommand),
        ("ToolLoopDetectionCommand", ToolLoopDetectionCommand),
        ("ToolLoopMaxRepeatsCommand", ToolLoopMaxRepeatsCommand),
        ("ToolLoopModeCommand", ToolLoopModeCommand),
        ("ToolLoopTTLCommand", ToolLoopTTLCommand),
    ],
)
def test_get_loop_detection_command_returns_registered_class(
    command_name: str, expected_class: type[LoopDetectionCommand]
) -> None:
    """The registry should return the concrete command class for each name."""

    command_cls = get_loop_detection_command(command_name)

    assert command_cls is expected_class


def test_get_loop_detection_command_raises_value_error_for_unknown_name() -> None:
    """An informative ``ValueError`` should be raised for unknown commands."""

    with pytest.raises(ValueError, match="Unknown loop detection command: unknown"):
        get_loop_detection_command("unknown")


def test_get_loop_detection_commands_returns_copy_of_registry() -> None:
    """The registry function should return a defensive copy of the commands map."""

    first_result = get_loop_detection_commands()
    first_result["new"] = LoopDetectionCommand

    second_result = get_loop_detection_commands()

    assert "new" not in second_result
    assert set(second_result) == {
        "LoopDetectionCommand",
        "ToolLoopDetectionCommand",
        "ToolLoopMaxRepeatsCommand",
        "ToolLoopModeCommand",
        "ToolLoopTTLCommand",
    }
