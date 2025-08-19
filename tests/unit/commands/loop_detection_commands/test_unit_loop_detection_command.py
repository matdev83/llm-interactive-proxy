
import pytest
from unittest.mock import Mock
import asyncio

from src.core.domain.commands.loop_detection_commands.loop_detection_command import LoopDetectionCommand
from src.core.domain.session import Session, SessionState, LoopDetectionConfiguration

@pytest.fixture
def command() -> LoopDetectionCommand:
    return LoopDetectionCommand()

@pytest.fixture
def mock_session() -> Mock:
    mock = Mock(spec=Session)
    mock.state = SessionState(loop_config=LoopDetectionConfiguration(loop_detection_enabled=False))
    return mock

@pytest.mark.asyncio
async def test_loop_detection_enable(command: LoopDetectionCommand, mock_session: Mock):
    # Arrange
    args = {"enabled": "true"}

    # Act
    result = await command.execute(args, mock_session)

    # Assert
    assert result.success is True
    assert result.message == "Loop detection enabled"
    assert result.new_state.loop_config.loop_detection_enabled is True

@pytest.mark.asyncio
async def test_loop_detection_disable(command: LoopDetectionCommand, mock_session: Mock):
    # Arrange
    mock_session.state = SessionState(loop_config=LoopDetectionConfiguration(loop_detection_enabled=True)) # Start with it on
    args = {"enabled": "false"}

    # Act
    result = await command.execute(args, mock_session)

    # Assert
    assert result.success is True
    assert result.message == "Loop detection disabled"
    assert result.new_state.loop_config.loop_detection_enabled is False

@pytest.mark.asyncio
async def test_loop_detection_default_enables(command: LoopDetectionCommand, mock_session: Mock):
    # Arrange
    args = {}

    # Act
    result = await command.execute(args, mock_session)

    # Assert
    assert result.success is True
    assert result.message == "Loop detection enabled"
    assert result.new_state.loop_config.loop_detection_enabled is True
