import asyncio
import logging
from collections.abc import Mapping
from typing import Any

import pytest
from src.core.domain.commands.loop_detection_commands.tool_loop_detection_command import (
    ToolLoopDetectionCommand,
)
from src.core.domain.configuration.loop_detection_config import (
    LoopDetectionConfiguration,
)
from src.core.domain.session import Session, SessionState


def _build_session(loop_config: LoopDetectionConfiguration) -> Session:
    return Session("session-id", state=SessionState(loop_config=loop_config))


def _run_command(
    command: ToolLoopDetectionCommand, args: Mapping[str, Any], session: Session
):
    return asyncio.run(command.execute(args, session))


def test_execute_enables_tool_loop_detection_when_true() -> None:
    command = ToolLoopDetectionCommand()
    session = _build_session(
        LoopDetectionConfiguration(tool_loop_detection_enabled=False)
    )

    result = _run_command(command, {"enabled": "true"}, session)

    assert result.success is True
    assert result.name == "tool-loop-detection"
    assert result.message == "Tool loop detection enabled"
    assert result.data == {"enabled": True}
    assert result.new_state.loop_config.tool_loop_detection_enabled is True


def test_execute_disables_tool_loop_detection_when_false() -> None:
    command = ToolLoopDetectionCommand()
    session = _build_session(
        LoopDetectionConfiguration(tool_loop_detection_enabled=True)
    )

    result = _run_command(command, {"enabled": "false"}, session)

    assert result.success is True
    assert result.message == "Tool loop detection disabled"
    assert result.data == {"enabled": False}
    assert result.new_state.loop_config.tool_loop_detection_enabled is False


def test_execute_defaults_to_enable_when_argument_missing() -> None:
    command = ToolLoopDetectionCommand()
    session = _build_session(
        LoopDetectionConfiguration(tool_loop_detection_enabled=False)
    )

    result = _run_command(command, {}, session)

    assert result.success is True
    assert result.data == {"enabled": True}
    assert result.message == "Tool loop detection enabled"
    assert result.new_state.loop_config.tool_loop_detection_enabled is True


@pytest.mark.parametrize(
    "value, expected",
    [
        ("yes", True),
        ("YES", True),
        ("1", True),
        ("on", True),
        ("   On   ", True),
        (True, True),
        ("no", False),
        ("0", False),
        (" off ", False),
        (None, False),
        (False, False),
    ],
)
def test_execute_handles_various_truthy_and_falsy_values(
    value: Any, expected: bool
) -> None:
    command = ToolLoopDetectionCommand()
    session = _build_session(
        LoopDetectionConfiguration(tool_loop_detection_enabled=not expected)
    )

    result = _run_command(command, {"enabled": value}, session)

    assert result.success is True
    assert result.data == {"enabled": expected}
    assert result.new_state.loop_config.tool_loop_detection_enabled is expected


def test_command_metadata_properties() -> None:
    command = ToolLoopDetectionCommand()

    assert command.name == "tool-loop-detection"
    assert command.format == "tool-loop-detection(enabled=true|false)"
    assert (
        command.description
        == "Enable or disable tool loop detection for the current session"
    )
    assert command.examples == ["!/tool-loop-detection(enabled=true)"]


class _FailingState:
    def __init__(self) -> None:
        self.loop_config = LoopDetectionConfiguration()

    def with_loop_config(
        self, loop_config: LoopDetectionConfiguration
    ) -> None:  # pragma: no cover - simple passthrough raising
        raise RuntimeError("unable to persist loop configuration")


class _FailingSession:
    def __init__(self) -> None:
        self.state = _FailingState()


def test_execute_returns_error_result_when_state_update_fails(
    caplog: pytest.LogCaptureFixture,
) -> None:
    command = ToolLoopDetectionCommand()
    session = _FailingSession()

    with caplog.at_level(logging.ERROR):
        result = _run_command(command, {"enabled": "true"}, session)

    assert result.success is False
    assert result.name == "tool-loop-detection"
    assert result.data == {}
    assert (
        result.message
        == "Error toggling tool loop detection: unable to persist loop configuration"
    )
    assert "Error toggling tool loop detection" in caplog.text
    assert caplog.records[0].exc_info
