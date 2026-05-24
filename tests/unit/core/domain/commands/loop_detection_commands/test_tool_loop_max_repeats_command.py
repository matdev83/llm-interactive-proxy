"""Tests for :mod:`src.core.domain.commands.loop_detection_commands.tool_loop_max_repeats_command`."""

from __future__ import annotations

import asyncio

import pytest
from src.core.domain.commands.loop_detection_commands.tool_loop_max_repeats_command import (
    ToolLoopMaxRepeatsCommand,
)
from src.core.domain.configuration.loop_detection_config import (
    LoopDetectionConfiguration,
)
from src.core.domain.session import Session, SessionState, SessionStateAdapter


@pytest.fixture()
def session() -> Session:
    """Return a session with default loop detection configuration."""
    return Session(
        "session-id", state=SessionState(loop_config=LoopDetectionConfiguration())
    )


def test_metadata_describes_command() -> None:
    """The command exposes metadata describing its usage."""
    command = ToolLoopMaxRepeatsCommand()

    assert command.name == "tool-loop-max-repeats"
    assert command.format == "tool-loop-max-repeats(max_repeats=<number>)"
    assert (
        command.description
        == "Set the maximum number of repeats for tool loop detection"
    )
    assert command.examples == ["!/tool-loop-max-repeats(max_repeats=5)"]


def test_execute_requires_max_repeats_argument(session: Session) -> None:
    """Omitting the ``max_repeats`` argument fails with a helpful message."""
    command = ToolLoopMaxRepeatsCommand()

    result = asyncio.run(command.execute({}, session))

    assert result.success is False
    assert result.message == "Max repeats must be specified"
    assert result.name == command.name


def test_execute_rejects_non_integer_values(session: Session) -> None:
    """Non-integer arguments are rejected with an explanatory error."""
    command = ToolLoopMaxRepeatsCommand()

    result = asyncio.run(command.execute({"max_repeats": "abc"}, session))

    assert result.success is False
    assert result.message == "Max repeats must be a valid integer"
    assert result.name == command.name


def test_execute_requires_value_of_at_least_two(session: Session) -> None:
    """Values lower than two are rejected before mutating the session state."""
    command = ToolLoopMaxRepeatsCommand()

    result = asyncio.run(command.execute({"max_repeats": "1"}, session))

    assert result.success is False
    assert result.message == "Max repeats must be at least 2"
    assert result.name == command.name


def test_execute_updates_loop_config_with_valid_value(session: Session) -> None:
    """A valid value updates the session state via a new ``SessionStateAdapter``."""
    command = ToolLoopMaxRepeatsCommand()

    result = asyncio.run(command.execute({"max_repeats": "7"}, session))

    assert result.success is True
    assert result.message == "Tool loop max repeats set to 7"
    assert result.data == {"max_repeats": 7}
    assert isinstance(result.new_state, SessionStateAdapter)
    assert result.new_state.loop_config.tool_loop_max_repeats == 7
    assert session.state.loop_config.tool_loop_max_repeats is None


def test_execute_reports_errors_from_loop_config(
    monkeypatch: pytest.MonkeyPatch, session: Session
) -> None:
    """Exceptions while updating the configuration are surfaced to the caller."""
    command = ToolLoopMaxRepeatsCommand()

    def raise_error(
        _: LoopDetectionConfiguration, __: int
    ) -> LoopDetectionConfiguration:
        raise RuntimeError("boom")

    monkeypatch.setattr(
        LoopDetectionConfiguration,
        "with_tool_loop_max_repeats",
        raise_error,
    )

    result = asyncio.run(command.execute({"max_repeats": 4}, session))

    assert result.success is False
    assert result.message.startswith("Error setting tool loop max repeats: boom")
    assert result.name == command.name
    assert result.new_state is None
