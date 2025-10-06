"""Test fixtures for command handling tests.

This module provides fixtures for setting up command handling tests.
"""

from collections.abc import Callable, Coroutine
from typing import Any, cast
from unittest.mock import Mock, PropertyMock

import pytest
from fastapi import FastAPI
from src.core.commands.service import NewCommandService
from src.core.domain.chat import ChatMessage
from src.core.domain.configuration.backend_config import BackendConfiguration
from src.core.domain.multimodal import ContentPart, ContentType
from src.core.domain.session import Session, SessionStateAdapter
from src.core.interfaces.command_processor_interface import ICommandProcessor


@pytest.fixture
def command_parser_config(
    test_session_state: SessionStateAdapter, app: FastAPI
) -> NewCommandService:
    """Return a DI-based NewCommandService for testing (replacement for legacy config)."""

    # Provide a minimal session service for DI
    class _SessionSvc:
        async def get_session(self, session_id: str) -> Session:
            return Session(session_id=session_id, state=test_session_state)

        async def update_session(self, session: Session) -> None:  # type: ignore[override]
            return None

    # Import CommandParser from new architecture
    from src.core.commands.parser import CommandParser

    # Empty registry by default; tests can register commands as needed
    return NewCommandService(
        _SessionSvc(), CommandParser(), strict_command_detection=False
    )


@pytest.fixture
async def command_parser_from_app_with_commands(app: FastAPI) -> ICommandProcessor:
    """Create a CommandParser for testing.

    Args:
        app: The FastAPI test application

    Returns:
        ICommandProcessor: An instance of the ICommandProcessor
    """
    # Retrieve the real CommandParser from the application's service provider
    # This ensures that the command parser is initialized with the actual command registry
    service_provider = app.state.service_provider
    parser = service_provider.get_service(ICommandProcessor)

    # In this test, we are primarily testing the command processing, not the internal state
    return cast(ICommandProcessor, parser)


@pytest.fixture
def mock_app() -> Mock:
    """Create a mock app for testing.

    Returns:
        Mock: A mock app with functional_backends and api_key_redaction_enabled
    """
    mock_app = Mock()
    mock_app.state = Mock()

    # Set up functional backends
    mock_app.state.functional_backends = {"openai", "anthropic", "openrouter", "gemini"}

    # Set up api_key_redaction_enabled
    type(mock_app.state).api_key_redaction_enabled = PropertyMock(return_value=True)
    type(mock_app.state).default_api_key_redaction_enabled = PropertyMock(
        return_value=True
    )

    # Set up mock backends
    mock_openrouter_backend = Mock()
    mock_openrouter_backend.get_available_models.return_value = [
        "gpt-4-turbo",
        "my/model-v1",
        "gpt-4",
        "claude-2",
        "test-model",
        "another-model",
        "command-only-model",
        "multi",
        "foo",
    ]
    mock_app.state.backends = {"openrouter": mock_openrouter_backend}

    return mock_app


@pytest.fixture
async def process_command(
    command_parser: ICommandProcessor,
    test_session: Session,
) -> Callable[
    [str, bool], Coroutine[Any, Any, tuple[list[ChatMessage], list[str], str]]
]:
    """Process a command in a message.

    This fixture returns a function that can be used to process a command in a message.

    Args:
        command_parser: The command parser fixture
        test_session: A test session

    Returns:
        callable: A function that processes a command in a message
    """

    async def _process_command(
        text: str, preserve_unknown: bool = False
    ) -> tuple[list[ChatMessage], list[str], str]:
        """Process a command in a message.

        Args:
            text: The message text containing the command
            preserve_unknown: Whether to preserve unknown commands

        Returns:
            tuple: A tuple of (processed_messages, commands_found, processed_text)
        """
        messages = [ChatMessage(role="user", content=text)]
        result = await command_parser.process_messages(
            messages,
            session_id=test_session.session_id,
        )
        processed_messages = result.modified_messages
        commands_found = [res.name for res in result.command_results]
        processed_text = ""
        if processed_messages and processed_messages[0].content:
            if isinstance(processed_messages[0].content, str):
                processed_text = processed_messages[0].content
            elif isinstance(processed_messages[0].content, list):
                # Concatenate text content parts
                processed_text = "".join(
                    cast(ContentPart, part).data
                    for part in processed_messages[0].content
                    if cast(ContentPart, part).type == ContentType.TEXT
                )
        return processed_messages, commands_found, processed_text

    return _process_command


@pytest.fixture
def session_with_model(
    test_session: Session,
    model_name: str = "test-model",
    backend_type: str = "openrouter",
) -> Session:
    """Create a session with a model and backend.

    Args:
        test_session: A test session
        model_name: The model name
        backend_type: The backend type

    Returns:
        Session: A session with the model and backend set
    """
    current_state = test_session.state
    new_backend_config = current_state.backend_config.with_model(model_name)
    new_backend_config = new_backend_config.with_backend(backend_type)
    test_session.state = current_state.with_backend_config(
        cast(BackendConfiguration, new_backend_config)
    )
    return test_session


@pytest.fixture
def session_with_project(
    test_session: Session, project_name: str = "test-project"
) -> Session:
    """Create a session with a project.

    Args:
        test_session: A test session
        project_name: The project name

    Returns:
        Session: A session with the project set
    """
    current_state = test_session.state
    test_session.state = current_state.with_project(project_name)
    return test_session


@pytest.fixture
def session_with_hello(test_session: Session) -> Session:
    """Create a session with hello_requested set to True.

    Args:
        test_session: A test session
    Returns:
        Session: A session with hello_requested set to True
    """
    current_state = test_session.state
    test_session.state = current_state.with_hello_requested(True)
    return test_session
