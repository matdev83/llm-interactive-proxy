"""Tests for the loop detection commands module exports."""

from importlib import import_module, reload


MODULE_PATH = "src.core.domain.commands.loop_detection_commands"


def test_loop_detection_commands_module_exports_expected_classes() -> None:
    """Verify that the module exposes the documented command classes."""

    module = reload(import_module(MODULE_PATH))

    expected_exports = [
        "LoopDetectionCommand",
        "ToolLoopDetectionCommand",
        "ToolLoopMaxRepeatsCommand",
        "ToolLoopModeCommand",
        "ToolLoopTTLCommand",
    ]

    assert module.__all__ == expected_exports

    loop_detection_command = import_module(f"{MODULE_PATH}.loop_detection_command").LoopDetectionCommand
    tool_loop_detection_command = import_module(f"{MODULE_PATH}.tool_loop_detection_command").ToolLoopDetectionCommand
    tool_loop_max_repeats_command = import_module(f"{MODULE_PATH}.tool_loop_max_repeats_command").ToolLoopMaxRepeatsCommand
    tool_loop_mode_command = import_module(f"{MODULE_PATH}.tool_loop_mode_command").ToolLoopModeCommand
    tool_loop_ttl_command = import_module(f"{MODULE_PATH}.tool_loop_ttl_command").ToolLoopTTLCommand

    assert module.LoopDetectionCommand is loop_detection_command
    assert module.ToolLoopDetectionCommand is tool_loop_detection_command
    assert module.ToolLoopMaxRepeatsCommand is tool_loop_max_repeats_command
    assert module.ToolLoopModeCommand is tool_loop_mode_command
    assert module.ToolLoopTTLCommand is tool_loop_ttl_command

    namespace: dict[str, object] = {}
    exec(f"from {MODULE_PATH} import *", namespace)

    for export_name in expected_exports:
        assert namespace[export_name] is getattr(module, export_name)
