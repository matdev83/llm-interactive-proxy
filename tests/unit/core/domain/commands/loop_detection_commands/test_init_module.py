"""Tests for :mod:`src.core.domain.commands.loop_detection_commands`."""

from importlib import import_module
from types import ModuleType

import pytest

from src.core.domain.commands.loop_detection_commands import (
    get_loop_detection_command,
    get_loop_detection_commands,
)
from src.core.domain.commands.loop_detection_commands.loop_detection_command import (
    LoopDetectionCommand,
)

MODULE_PATH = "src.core.domain.commands.loop_detection_commands"
EXPECTED_EXPORTS = [
    "LoopDetectionCommand",
    "ToolLoopDetectionCommand",
    "ToolLoopMaxRepeatsCommand",
    "ToolLoopModeCommand",
    "ToolLoopTTLCommand",
]


def load_module() -> ModuleType:
    """Import and return the loop detection commands module."""
    return import_module(MODULE_PATH)


def test_module_exports_expected_command_symbols() -> None:
    """The module exports the expected command classes via ``__all__``."""
    module = load_module()

    assert module.__all__ == EXPECTED_EXPORTS


@pytest.mark.parametrize("name", EXPECTED_EXPORTS)
def test_module_exports_resolve_to_public_attributes(name: str) -> None:
    """Each exported symbol is available as a public attribute on the module."""
    module = load_module()

    exported_object = getattr(module, name)

    assert exported_object.__name__ == name


def test_get_loop_detection_command_returns_registered_class() -> None:
    """``get_loop_detection_command`` returns the requested command class."""

    command_cls = get_loop_detection_command("LoopDetectionCommand")

    assert command_cls is LoopDetectionCommand


def test_get_loop_detection_command_with_unknown_name_raises_value_error() -> None:
    """Requesting an unknown command name raises ``ValueError``."""

    with pytest.raises(ValueError) as exc_info:
        get_loop_detection_command("unknown-command")

    assert "Unknown loop detection command" in str(exc_info.value)


def test_get_loop_detection_commands_returns_independent_copy() -> None:
    """Modifying the returned mapping does not affect future lookups."""

    first_snapshot = get_loop_detection_commands()
    assert first_snapshot["LoopDetectionCommand"] is LoopDetectionCommand

    first_snapshot.pop("LoopDetectionCommand")

    second_snapshot = get_loop_detection_commands()

    assert "LoopDetectionCommand" in second_snapshot
    assert first_snapshot is not second_snapshot
