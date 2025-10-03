"""Tests for the loop detection commands module exports."""

from importlib import import_module, reload
from types import ModuleType

import pytest

MODULE_PATH = "src.core.domain.commands.loop_detection_commands"

EXPORT_MODULE_MAP = {
    "LoopDetectionCommand": "loop_detection_command",
    "ToolLoopDetectionCommand": "tool_loop_detection_command",
    "ToolLoopMaxRepeatsCommand": "tool_loop_max_repeats_command",
    "ToolLoopModeCommand": "tool_loop_mode_command",
    "ToolLoopTTLCommand": "tool_loop_ttl_command",
}


def _reload_module() -> ModuleType:
    return reload(import_module(MODULE_PATH))


def _import_command_class(name: str) -> type[object]:
    module = import_module(f"{MODULE_PATH}.{EXPORT_MODULE_MAP[name]}")
    return getattr(module, name)


def test_loop_detection_commands_module_exports_expected_classes() -> None:
    """Verify that the module exposes the documented command classes."""

    module = _reload_module()

    expected_exports = list(EXPORT_MODULE_MAP)

    assert module.__all__ == expected_exports

    for export_name in expected_exports:
        assert getattr(module, export_name) is _import_command_class(export_name)

    namespace: dict[str, object] = {}
    exec(f"from {MODULE_PATH} import *", namespace)

    for export_name in expected_exports:
        assert namespace[export_name] is getattr(module, export_name)


def test_get_loop_detection_command_returns_expected_class() -> None:
    module = _reload_module()

    command = module.get_loop_detection_command("ToolLoopTTLCommand")

    assert command is _import_command_class("ToolLoopTTLCommand")


def test_get_loop_detection_command_rejects_unknown_command_name() -> None:
    module = _reload_module()

    with pytest.raises(ValueError, match="Unknown loop detection command: unknown"):
        module.get_loop_detection_command("unknown")


def test_get_loop_detection_commands_returns_isolated_copy() -> None:
    module = _reload_module()

    commands = module.get_loop_detection_commands()

    assert list(commands) == list(EXPORT_MODULE_MAP)
    assert commands["LoopDetectionCommand"] is _import_command_class(
        "LoopDetectionCommand"
    )

    commands["LoopDetectionCommand"] = object

    refreshed_commands = module.get_loop_detection_commands()
    assert refreshed_commands["LoopDetectionCommand"] is _import_command_class(
        "LoopDetectionCommand"
    )
