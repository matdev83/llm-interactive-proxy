import asyncio

from src.core.domain.commands.loop_detection_commands.tool_loop_detection_command import (
    ToolLoopDetectionCommand,
)
from src.core.domain.configuration.loop_detection_config import LoopDetectionConfiguration
from src.core.domain.session import Session, SessionState


def test_execute_enables_tool_loop_detection_when_true() -> None:
    command = ToolLoopDetectionCommand()
    session_state = SessionState(
        loop_config=LoopDetectionConfiguration(tool_loop_detection_enabled=False)
    )
    session = Session("session-id", state=session_state)

    result = asyncio.run(command.execute({"enabled": "true"}, session))

    assert result.success is True
    assert result.name == "tool-loop-detection"
    assert result.message == "Tool loop detection enabled"
    assert result.data == {"enabled": True}
    assert result.new_state.loop_config.tool_loop_detection_enabled is True


def test_execute_disables_tool_loop_detection_when_false() -> None:
    command = ToolLoopDetectionCommand()
    session_state = SessionState(
        loop_config=LoopDetectionConfiguration(tool_loop_detection_enabled=True)
    )
    session = Session("session-id", state=session_state)

    result = asyncio.run(command.execute({"enabled": "false"}, session))

    assert result.success is True
    assert result.message == "Tool loop detection disabled"
    assert result.data == {"enabled": False}
    assert result.new_state.loop_config.tool_loop_detection_enabled is False


def test_execute_defaults_to_enable_when_argument_missing() -> None:
    command = ToolLoopDetectionCommand()
    session_state = SessionState(
        loop_config=LoopDetectionConfiguration(tool_loop_detection_enabled=False)
    )
    session = Session("session-id", state=session_state)

    result = asyncio.run(command.execute({}, session))

    assert result.success is True
    assert result.data == {"enabled": True}
    assert result.message == "Tool loop detection enabled"
    assert result.new_state.loop_config.tool_loop_detection_enabled is True


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


def test_execute_returns_error_result_when_state_update_fails() -> None:
    command = ToolLoopDetectionCommand()
    session = _FailingSession()

    result = asyncio.run(command.execute({"enabled": "true"}, session))

    assert result.success is False
    assert result.name == "tool-loop-detection"
    assert result.data == {}
    assert (
        result.message
        == "Error toggling tool loop detection: unable to persist loop configuration"
    )
