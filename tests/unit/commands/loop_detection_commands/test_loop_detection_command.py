from unittest.mock import Mock

import pytest

from src.core.domain.commands.loop_detection_commands.loop_detection_command import (
    LoopDetectionCommand,
)
from src.core.domain.configuration.loop_detection_config import (
    LoopDetectionConfiguration,
)
from src.core.domain.session import Session, SessionState


@pytest.fixture
def session() -> Session:
    return Session(
        session_id="test-session",
        state=SessionState(loop_config=LoopDetectionConfiguration()),
    )


@pytest.mark.asyncio
async def test_loop_detection_command_metadata() -> None:
    command = LoopDetectionCommand()

    assert command.name == "loop-detection"
    assert command.format == "loop-detection(enabled=true|false)"
    assert (
        command.description
        == "Enable or disable loop detection for the current session"
    )
    assert command.examples == [
        "!/loop-detection(enabled=true)",
        "!/loop-detection(enabled=false)",
    ]


@pytest.mark.asyncio
async def test_execute_defaults_to_enabling_loop_detection(session: Session) -> None:
    command = LoopDetectionCommand()

    result = await command.execute({}, session)

    assert result.success is True
    assert result.data == {"enabled": True}
    assert result.message == "Loop detection enabled"
    assert result.new_state.loop_config.loop_detection_enabled is True


@pytest.mark.asyncio
async def test_execute_disables_loop_detection_when_false(session: Session) -> None:
    command = LoopDetectionCommand()

    result = await command.execute({"enabled": "false"}, session)

    assert result.success is True
    assert result.data == {"enabled": False}
    assert result.message == "Loop detection disabled"
    assert result.new_state.loop_config.loop_detection_enabled is False


@pytest.mark.asyncio
async def test_execute_handles_loop_detection_errors() -> None:
    command = LoopDetectionCommand()
    session_mock = Mock(spec=Session)

    loop_config = Mock()
    loop_config.with_loop_detection_enabled.side_effect = RuntimeError("boom")

    state = Mock()
    state.loop_config = loop_config
    state.with_loop_config = Mock()
    session_mock.state = state

    result = await command.execute({"enabled": "true"}, session_mock)

    assert result.success is False
    assert result.name == command.name
    assert "Error toggling loop detection" in result.message
    state.with_loop_config.assert_not_called()
