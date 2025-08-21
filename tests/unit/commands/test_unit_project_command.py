import pytest
from unittest.mock import Mock, AsyncMock

from src.core.domain.commands.project_command import ProjectCommand
from src.core.domain.command_results import CommandResult
from src.core.domain.session import Session


@pytest.fixture
def command() -> ProjectCommand:
    """Fixture for ProjectCommand."""
    return ProjectCommand()


@pytest.fixture
def mock_session() -> Mock:
    """Fixture for a mocked session."""
    session = Mock(spec=Session)
    session.state.project = None
    # Mock the with_project method to return a proper mock
    mock_new_state = Mock()
    mock_new_state.project = "my-new-project"
    session.state.with_project.return_value = mock_new_state
    return session


@pytest.mark.asyncio
async def test_project_command_success(command: ProjectCommand, mock_session: Mock):
    # Arrange
    args = {"name": "my-new-project"}

    # Act
    result = await command.execute(args, mock_session)

    # Assert
    assert result.success is True
    assert result.message == "Project changed to my-new-project"
    assert result.new_state.project == "my-new-project"


@pytest.mark.asyncio
async def test_project_command_unset(command: ProjectCommand, mock_session: Mock):
    # Arrange
    mock_session.state.project = "existing-project"
    args = {"name": None}

    # Act
    result = await command.execute(args, mock_session)

    # Assert
    assert result.success is False
    assert result.message == "Project name must be specified"


@pytest.mark.asyncio
async def test_project_command_failure_no_name(command: ProjectCommand, mock_session: Mock):
    # Arrange
    args = {}

    # Act
    result = await command.execute(args, mock_session)

    # Assert
    assert result.success is False
    assert result.message == "Project name must be specified"
