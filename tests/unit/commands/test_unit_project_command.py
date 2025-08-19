
import pytest
from unittest.mock import Mock
import asyncio

from src.core.domain.commands.project_command import ProjectCommand
from src.core.domain.session import Session, SessionState

@pytest.fixture
def command() -> ProjectCommand:
    return ProjectCommand()

@pytest.fixture
def mock_session() -> Mock:
    mock = Mock(spec=Session)
    mock.state = SessionState()
    return mock

@pytest.mark.asyncio
async def test_project_command_success(command: ProjectCommand, mock_session: Mock):
    # Arrange
    args = {"name": "my-new-project"}

    # Act
    result = await command.execute(args, mock_session)

    # Assert
    assert result.success is True
    assert result.message == "Project changed to my-new-project"
    assert result.new_state is not None
    assert result.new_state.project == "my-new-project"

@pytest.mark.asyncio
async def test_project_command_failure_no_name(command: ProjectCommand, mock_session: Mock):
    # Arrange
    args = {"name": ""} # Empty name

    # Act
    result = await command.execute(args, mock_session)

    # Assert
    assert result.success is False
    assert "Project name must be specified" in result.message
