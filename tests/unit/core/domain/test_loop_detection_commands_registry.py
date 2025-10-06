"""Tests for the loop detection command registry helpers."""

from __future__ import annotations

from importlib import reload

import pytest

import src.core.domain.commands.loop_detection_commands as loop_detection_commands


@pytest.fixture(autouse=True)
def reload_commands_module():
    """Ensure the registry module is freshly imported for each test."""

    yield
    reload(loop_detection_commands)


def test_get_loop_detection_command_returns_registered_class() -> None:
    """Every exported command name should resolve to the exported class."""

    for command_name in loop_detection_commands.__all__:
        command_class = loop_detection_commands.get_loop_detection_command(command_name)
        exported_class = getattr(loop_detection_commands, command_name)
        assert command_class is exported_class


def test_get_loop_detection_command_raises_for_unknown_name() -> None:
    """The registry should raise ``ValueError`` for unknown command names."""

    with pytest.raises(ValueError, match="^Unknown loop detection command: missing$"):
        loop_detection_commands.get_loop_detection_command("missing")


def test_get_loop_detection_commands_returns_isolated_copy() -> None:
    """Mutating the returned mapping must not affect the registry's state."""

    commands = loop_detection_commands.get_loop_detection_commands()

    assert set(commands) == set(loop_detection_commands.__all__)

    commands["LoopDetectionCommand"] = object

    refreshed_commands = loop_detection_commands.get_loop_detection_commands()
    assert refreshed_commands["LoopDetectionCommand"] is loop_detection_commands.LoopDetectionCommand
