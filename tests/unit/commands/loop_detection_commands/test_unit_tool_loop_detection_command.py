
from unittest.mock import Mock

import pytest
from src.core.domain.commands.loop_detection_commands.tool_loop_detection_command import (
    ToolLoopDetectionCommand,
)
from src.core.domain.session import LoopDetectionConfiguration, Session, SessionState


@pytest.fixture
def command() -> ToolLoopDetectionCommand:
    return ToolLoopDetectionCommand()

@pytest.fixture
def mock_session() -> Mock:
    mock = Mock(spec=Session)
    mock.state = SessionState(loop_config=LoopDetectionConfiguration(tool_loop_detection_enabled=False))
    return mock

@pytest.mark.asyncio
@pytest.mark.skip(reason="Loop detection is disabled due to legacy/invalid implementation. TODO: Implement gemini-cli inspired fast hash-based loop detection.")
async def test_tool_loop_detection_enable(command: ToolLoopDetectionCommand, mock_session: Mock):
    # Arrange
    args = {"enabled": "true"}

    # Act
    result = await command.execute(args, mock_session)

    # Assert
    assert result.success is True
    assert result.message == "Tool loop detection enabled"
    assert result.new_state.loop_config.tool_loop_detection_enabled is True

@pytest.mark.asyncio
@pytest.mark.skip(reason="Loop detection is disabled due to legacy/invalid implementation. TODO: Implement gemini-cli inspired fast hash-based loop detection.")
async def test_tool_loop_detection_disable(command: ToolLoopDetectionCommand, mock_session: Mock):
    # Arrange
    mock_session.state = SessionState(loop_config=LoopDetectionConfiguration(tool_loop_detection_enabled=True)) # Start with it on
    args = {"enabled": "false"}

    # Act
    result = await command.execute(args, mock_session)

    # Assert
    assert result.success is True
    assert result.message == "Tool loop detection disabled"
    assert result.new_state.loop_config.tool_loop_detection_enabled is False

@pytest.mark.asyncio
@pytest.mark.skip(reason="Loop detection is disabled due to legacy/invalid implementation. TODO: Implement gemini-cli inspired fast hash-based loop detection.")
async def test_tool_loop_detection_default_enables(command: ToolLoopDetectionCommand, mock_session: Mock):
    # Arrange
    args = {}

    # Act
    result = await command.execute(args, mock_session)

    # Assert
    assert result.success is True
    assert result.message == "Tool loop detection enabled"
    assert result.new_state.loop_config.tool_loop_detection_enabled is True
