
from unittest.mock import Mock

import pytest
from src.core.domain.commands.loop_detection_commands.tool_loop_ttl_command import (
    ToolLoopTTLCommand,
)
from src.core.domain.session import LoopDetectionConfiguration, Session, SessionState


@pytest.fixture
def command() -> ToolLoopTTLCommand:
    return ToolLoopTTLCommand()

@pytest.fixture
def mock_session() -> Mock:
    mock = Mock(spec=Session)
    mock.state = SessionState(loop_config=LoopDetectionConfiguration())
    return mock

@pytest.mark.asyncio
@pytest.mark.skip(reason="Loop detection is disabled due to legacy/invalid implementation. TODO: Implement gemini-cli inspired fast hash-based loop detection.")
async def test_ttl_success(command: ToolLoopTTLCommand, mock_session: Mock):
    # Arrange
    args = {"ttl_seconds": "60"}

    # Act
    result = await command.execute(args, mock_session)

    # Assert
    assert result.success is True
    assert result.message == "Tool loop TTL set to 60 seconds"
    assert result.new_state.loop_config.tool_loop_ttl_seconds == 60

@pytest.mark.asyncio
@pytest.mark.skip(reason="Loop detection is disabled due to legacy/invalid implementation. TODO: Implement gemini-cli inspired fast hash-based loop detection.")
async def test_ttl_failure_invalid_int(command: ToolLoopTTLCommand, mock_session: Mock):
    # Arrange
    args = {"ttl_seconds": "abc"}

    # Act
    result = await command.execute(args, mock_session)

    # Assert
    assert result.success is False
    assert result.message == "TTL seconds must be a valid integer"

@pytest.mark.asyncio
@pytest.mark.skip(reason="Loop detection is disabled due to legacy/invalid implementation. TODO: Implement gemini-cli inspired fast hash-based loop detection.")
async def test_ttl_failure_too_low(command: ToolLoopTTLCommand, mock_session: Mock):
    # Arrange
    args = {"ttl_seconds": "0"}

    # Act
    result = await command.execute(args, mock_session)

    # Assert
    assert result.success is False
    assert result.message == "TTL seconds must be at least 1"

@pytest.mark.asyncio
@pytest.mark.skip(reason="Loop detection is disabled due to legacy/invalid implementation. TODO: Implement gemini-cli inspired fast hash-based loop detection.")
async def test_ttl_failure_no_value(command: ToolLoopTTLCommand, mock_session: Mock):
    # Arrange
    args = {"ttl_seconds": None}

    # Act
    result = await command.execute(args, mock_session)

    # Assert
    assert result.success is False
    assert result.message == "TTL seconds must be specified"
