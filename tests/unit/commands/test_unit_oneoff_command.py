from unittest.mock import Mock

import pytest
from src.core.domain.commands.oneoff_command import OneoffCommand
from src.core.domain.session import BackendConfiguration, Session, SessionState


@pytest.fixture
def command() -> OneoffCommand:
    return OneoffCommand()


@pytest.fixture
def mock_session() -> Mock:
    mock = Mock(spec=Session)
    mock.state = SessionState(backend_config=BackendConfiguration())
    return mock


@pytest.mark.asyncio
async def test_oneoff_success_backend_model_format(
    command: OneoffCommand, mock_session: Mock
):
    # Arrange
    args = {"openrouter:openai/gpt-4": True}

    # Act
    result = await command.execute(args, mock_session)

    # Assert
    assert result.success is True
    assert result.message == "One-off route set to openrouter:openai/gpt-4."
    # The command modifies session.state directly
    assert mock_session.state.backend_config.oneoff_backend == "openrouter"
    assert mock_session.state.backend_config.oneoff_model == "openai/gpt-4"


@pytest.mark.asyncio
async def test_oneoff_success_colon_format(command: OneoffCommand, mock_session: Mock):
    # Arrange
    args = {"gemini:gemini-pro": True}

    # Act
    result = await command.execute(args, mock_session)

    # Assert
    assert result.success is True
    assert result.message == "One-off route set to gemini:gemini-pro."
    assert mock_session.state.backend_config.oneoff_backend == "gemini"
    assert mock_session.state.backend_config.oneoff_model == "gemini-pro"


@pytest.mark.asyncio
async def test_oneoff_failure_no_args(command: OneoffCommand, mock_session: Mock):
    # Arrange
    args = {}

    # Act
    result = await command.execute(args, mock_session)

    # Assert
    assert result.success is False
    assert "requires a backend:model argument" in result.message


@pytest.mark.asyncio
async def test_oneoff_failure_invalid_format(
    command: OneoffCommand, mock_session: Mock
):
    # Arrange
    args = {"invalid-format": True}

    # Act
    result = await command.execute(args, mock_session)

    # Assert
    assert result.success is False
    assert "Invalid format" in result.message


@pytest.mark.asyncio
async def test_oneoff_rejects_model_only_selector_with_colon_suffix(
    command: OneoffCommand, mock_session: Mock
):
    # Arrange
    args = {"openrouter/anthropic/claude-3-haiku:free": True}

    # Act
    result = await command.execute(args, mock_session)

    # Assert
    assert result.success is False
    assert "backend:model" in result.message
    assert "model-only selector" in result.message.lower()
    assert result.data is not None
    assert result.data.get("error_code") == "invalid_explicit_backend_selector"
