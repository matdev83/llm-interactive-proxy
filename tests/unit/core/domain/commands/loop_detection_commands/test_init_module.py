"""Tests for :mod:`src.core.domain.commands.loop_detection_commands`."""

from importlib import import_module
from types import ModuleType

import pytest

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
