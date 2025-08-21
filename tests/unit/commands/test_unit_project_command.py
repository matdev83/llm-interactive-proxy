from unittest.mock import Mock

import pytest
pytest.skip("Skipping tests for removed legacy handlers", allow_module_level=True)
from src.core.constants.command_output_constants import (
    PROJECT_SET_MESSAGE,
    PROJECT_UNSET_MESSAGE,
)
from src.core.commands.handlers.project_handler import ProjectCommandHandler
from src.core.domain.session import Session, SessionState


@pytest.fixture
def handler() -> ProjectCommandHandler:
    return ProjectCommandHandler()


@pytest.fixture
def mock_session() -> Mock:
    mock = Mock(spec=Session)
    mock.state = SessionState()
    return mock


def test_project_handler_success(handler: ProjectCommandHandler, mock_session: Mock):
    # Arrange
    project_name = "my-new-project"

    # Act
    result = handler.handle(project_name, mock_session.state)

    # Assert
    assert result.success is True
    assert result.message == PROJECT_SET_MESSAGE.format(project=project_name)
    assert result.new_state is not None
    assert result.new_state.project == project_name


def test_project_handler_unset(handler: ProjectCommandHandler, mock_session: Mock):
    # Act
    result = handler.handle(None, mock_session.state)

    # Assert
    assert result.success is True
    assert result.message == PROJECT_UNSET_MESSAGE
    assert result.new_state is not None
    assert result.new_state.project is None


def test_project_handler_failure_empty_name(handler: ProjectCommandHandler, mock_session: Mock):
    # Arrange
    project_name = ""

    # Act
    result = handler.handle(project_name, mock_session.state)

    # Assert
    assert result.success is True  # Empty string is treated as a valid project name
    assert result.message == PROJECT_SET_MESSAGE.format(project=project_name)
    assert result.new_state is not None
    assert result.new_state.project == project_name
