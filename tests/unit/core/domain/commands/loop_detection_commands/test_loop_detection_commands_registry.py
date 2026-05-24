"""Tests for loop detection command registry helpers."""

from __future__ import annotations

import pytest
import src.core.domain.commands.loop_detection_commands as registry_module

COMMAND_NAMES: list[str] = [
    "LoopDetectionCommand",
    "ToolLoopDetectionCommand",
    "ToolLoopMaxRepeatsCommand",
    "ToolLoopModeCommand",
    "ToolLoopTTLCommand",
]


@pytest.mark.parametrize("command_name", COMMAND_NAMES)
def test_get_loop_detection_command_returns_registered_class_parametrized(
    command_name: str,
) -> None:
    """Each known command name resolves to its registered class."""

    expected_cls = getattr(registry_module, command_name)
    resolved = registry_module.get_loop_detection_command(command_name)

    assert resolved is expected_cls


def test_get_loop_detection_command_unknown_name_parametrized() -> None:
    """An unknown command name raises a clear ``ValueError``."""

    with pytest.raises(ValueError, match="Unknown loop detection command: unknown"):
        registry_module.get_loop_detection_command("unknown")


def test_get_loop_detection_commands_returns_copy_parametrized() -> None:
    """Mutating a retrieved mapping does not affect the registry state."""

    expected_commands = {name: getattr(registry_module, name) for name in COMMAND_NAMES}
    commands = registry_module.get_loop_detection_commands()

    # Baseline sanity check for returned mapping contents.
    assert commands == expected_commands

    # Mutate the mapping and ensure a subsequent call is unaffected.
    mutable_commands = dict(commands)
    mutable_commands["LoopDetectionCommand"] = type(
        "DummyLoopDetectionCommand",
        (),
        {},
    )

    fresh_commands = registry_module.get_loop_detection_commands()

    assert fresh_commands == expected_commands
