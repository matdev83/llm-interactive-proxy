"""Unit tests for :mod:`src.core.domain.commands.loop_detection_commands.loop_detection_command`."""

from __future__ import annotations

import asyncio

import pytest
from pytest import MonkeyPatch
from src.core.domain.commands.loop_detection_commands.loop_detection_command import (
    LoopDetectionCommand,
)
from src.core.domain.configuration.loop_detection_config import (
    LoopDetectionConfiguration,
)
from src.core.domain.session import Session, SessionState, SessionStateAdapter


def test_execute_defaults_to_enabling_loop_detection() -> None:
    """The command enables loop detection when no argument is provided."""
    session = Session(
        "session-id",
        state=SessionState(
            loop_config=LoopDetectionConfiguration(loop_detection_enabled=False)
        ),
    )
    command = LoopDetectionCommand()

    result = asyncio.run(command.execute({}, session))

    assert result.success is True
    assert result.message == "Loop detection enabled"
    assert result.data == {"enabled": True}
    assert isinstance(result.new_state, SessionStateAdapter)
    assert result.new_state.loop_config.loop_detection_enabled is True
    # Ensure that the command does not mutate the original session state directly.
    assert session.state.loop_config.loop_detection_enabled is False


def test_execute_disables_loop_detection_with_falsey_argument() -> None:
    """The command disables loop detection when supplied a false-like value."""
    session = Session(
        "session-id",
        state=SessionState(
            loop_config=LoopDetectionConfiguration(loop_detection_enabled=True)
        ),
    )
    command = LoopDetectionCommand()

    result = asyncio.run(command.execute({"enabled": "false"}, session))

    assert result.success is True
    assert result.message == "Loop detection disabled"
    assert result.data == {"enabled": False}
    assert isinstance(result.new_state, SessionStateAdapter)
    assert result.new_state.loop_config.loop_detection_enabled is False


@pytest.mark.parametrize(
    "enabled_value",
    ["true", "True", "YES", "1", "on", True],
)
def test_execute_interprets_various_truthy_values(enabled_value: object) -> None:
    """The command treats multiple truthy representations as enabling the feature."""
    session = Session(
        "session-id",
        state=SessionState(
            loop_config=LoopDetectionConfiguration(loop_detection_enabled=False)
        ),
    )
    command = LoopDetectionCommand()

    result = asyncio.run(command.execute({"enabled": enabled_value}, session))

    assert result.success is True
    assert result.message == "Loop detection enabled"
    assert result.data == {"enabled": True}
    assert isinstance(result.new_state, SessionStateAdapter)
    assert result.new_state.loop_config.loop_detection_enabled is True
    # Verify the original state is not mutated.
    assert session.state.loop_config.loop_detection_enabled is False


@pytest.mark.parametrize(
    "disabled_value",
    ["false", "False", "no", "0", "off", False, 0],
)
def test_execute_interprets_various_falsey_values(disabled_value: object) -> None:
    """The command treats multiple falsey representations as disabling the feature."""
    session = Session(
        "session-id",
        state=SessionState(
            loop_config=LoopDetectionConfiguration(loop_detection_enabled=True)
        ),
    )
    command = LoopDetectionCommand()

    result = asyncio.run(command.execute({"enabled": disabled_value}, session))

    assert result.success is True
    assert result.message == "Loop detection disabled"
    assert result.data == {"enabled": False}
    assert isinstance(result.new_state, SessionStateAdapter)
    assert result.new_state.loop_config.loop_detection_enabled is False
    # Verify the original state is not mutated.
    assert session.state.loop_config.loop_detection_enabled is True


def test_execute_returns_failure_when_loop_update_raises(
    monkeypatch: MonkeyPatch,
) -> None:
    """Any exception raised while updating the loop configuration is reported."""
    session = Session(
        "session-id",
        state=SessionState(loop_config=LoopDetectionConfiguration()),
    )
    command = LoopDetectionCommand()

    def raise_error(
        _self: LoopDetectionConfiguration, _: bool
    ) -> LoopDetectionConfiguration:  # pragma: no cover - exercised via command
        raise RuntimeError("boom")

    monkeypatch.setattr(
        LoopDetectionConfiguration,
        "with_loop_detection_enabled",
        raise_error,
    )

    result = asyncio.run(command.execute({"enabled": "true"}, session))

    assert result.success is False
    assert result.message.startswith("Error toggling loop detection: boom")
    assert result.name == command.name
    assert result.new_state is None
