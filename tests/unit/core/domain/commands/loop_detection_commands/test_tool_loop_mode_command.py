"""Tests for the ToolLoopModeCommand."""

import asyncio

from pytest import MonkeyPatch

from src.core.domain.commands.loop_detection_commands.tool_loop_mode_command import (
    ToolLoopModeCommand,
)
from src.core.domain.configuration.loop_detection_config import (
    LoopDetectionConfiguration,
)
from src.core.domain.session import Session, SessionState, SessionStateAdapter
from src.tool_call_loop.config import ToolLoopMode


def test_execute_requires_mode_argument() -> None:
    """The command reports an error when no mode argument is provided."""
    session = Session("session-id", state=SessionState())
    command = ToolLoopModeCommand()

    result = asyncio.run(command.execute({}, session))

    assert result.success is False
    assert result.message == "Mode must be specified"
    assert result.name == command.name
    assert result.new_state is None


def test_execute_returns_error_for_invalid_mode() -> None:
    """An informative error is returned when the mode value is invalid."""
    session = Session("session-id", state=SessionState())
    command = ToolLoopModeCommand()

    result = asyncio.run(command.execute({"mode": "invalid"}, session))

    assert result.success is False
    assert (
        result.message
        == "Invalid mode 'invalid'. Valid modes: break, chance_then_break"
    )
    assert result.name == command.name
    assert result.new_state is None


def test_execute_sets_mode_successfully() -> None:
    """Providing a valid mode updates the loop configuration."""
    session = Session("session-id", state=SessionState())
    command = ToolLoopModeCommand()

    result = asyncio.run(command.execute({"mode": "BrEaK"}, session))

    assert result.success is True
    assert result.data == {"mode": ToolLoopMode.BREAK.value}
    assert result.message == "Tool loop mode set to break"
    assert isinstance(result.new_state, SessionStateAdapter)
    assert result.new_state.loop_config.tool_loop_mode is ToolLoopMode.BREAK
    # Ensure the original session state remains unchanged.
    assert session.state.loop_config.tool_loop_mode is None


def test_execute_handles_loop_config_errors(monkeypatch: MonkeyPatch) -> None:
    """Unexpected errors while updating the config are reported to the caller."""
    session = Session("session-id", state=SessionState())
    command = ToolLoopModeCommand()

    def raise_error(
        _self: LoopDetectionConfiguration, _mode: ToolLoopMode
    ) -> LoopDetectionConfiguration:  # pragma: no cover - exercised through command
        raise RuntimeError("boom")

    monkeypatch.setattr(
        LoopDetectionConfiguration,
        "with_tool_loop_mode",
        raise_error,
    )

    result = asyncio.run(command.execute({"mode": "break"}, session))

    assert result.success is False
    assert result.message.startswith("Error setting tool loop mode: boom")
    assert result.name == command.name
    assert result.new_state is None
