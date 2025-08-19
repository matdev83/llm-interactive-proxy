
import pytest
from unittest.mock import Mock
import asyncio

from src.core.domain.commands.pwd_command import PwdCommand
from src.core.domain.session import Session, SessionState

@pytest.fixture
def command() -> PwdCommand:
    return PwdCommand()

@pytest.fixture
def mock_session() -> Mock:
    mock = Mock(spec=Session)
    mock.state = SessionState()
    return mock

@pytest.mark.asyncio
async def test_pwd_with_project_dir_set(command: PwdCommand, mock_session: Mock):
    # Arrange
    test_dir = "/path/to/my/project"
    mock_session.state = SessionState(project_dir=test_dir)

    # Act
    result = await command.execute({}, mock_session)

    # Assert
    assert result.success is True
    assert result.message == test_dir

@pytest.mark.asyncio
async def test_pwd_with_project_dir_not_set(command: PwdCommand, mock_session: Mock):
    # Arrange
    mock_session.state = SessionState(project_dir=None)

    # Act
    result = await command.execute({}, mock_session)

    # Assert
    assert result.success is True
    assert result.message == "Project directory not set"
