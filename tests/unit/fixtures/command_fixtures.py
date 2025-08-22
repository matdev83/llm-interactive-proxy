"""Test fixtures for command handling tests.

This module provides fixtures for setting up command handling tests.
"""

import pytest
from typing import Any, Dict, Optional, cast
from unittest.mock import Mock, PropertyMock

from src.core.domain.chat import ChatMessage
from src.core.domain.configuration.backend_config import BackendConfiguration
from src.core.domain.session import Session, SessionStateAdapter
from src.command_parser import CommandParser, CommandParserConfig

from tests.unit.mock_commands import process_commands_in_messages_test, setup_test_command_registry_for_unit_tests


@pytest.fixture
def mock_app():
    """Create a mock app for testing.
    
    Returns:
        Mock: A mock app with functional_backends and api_key_redaction_enabled
    """
    mock_app = Mock()
    mock_app.state = Mock()
    
    # Set up functional backends
    mock_app.state.functional_backends = {
        "openai", "anthropic", "openrouter", "gemini"
    }
    
    # Set up api_key_redaction_enabled
    type(mock_app.state).api_key_redaction_enabled = PropertyMock(return_value=True)
    type(mock_app.state).default_api_key_redaction_enabled = PropertyMock(return_value=True)
    
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
def command_parser_config(test_session_state, mock_app):
    """Create a CommandParserConfig for testing.
    
    Args:
        test_session_state: A test session state
        mock_app: A mock app
        
    Returns:
        CommandParserConfig: A command parser config
    """
    return CommandParserConfig(
        proxy_state=test_session_state,
        app=mock_app,
        preserve_unknown=False,
        functional_backends=mock_app.state.functional_backends,
    )


@pytest.fixture
def command_parser(command_parser_config, command_prefix="!/"):
    """Create a CommandParser for testing.
    
    Args:
        command_parser_config: A command parser config
        command_prefix: The command prefix to use
        
    Returns:
        CommandParser: A command parser
    """
    # Reset the command registry
    from tests.unit.utils.isolation_utils import reset_command_registry
    reset_command_registry()
    
    # Set up the command registry with mock commands
    setup_test_command_registry_for_unit_tests()
    
    # Create a parser with the command registry
    parser = CommandParser(command_parser_config, command_prefix=command_prefix)
    
    # Initialize command_results
    parser.command_results = []
    
    return parser


@pytest.fixture
async def process_command(test_session, mock_app, command_prefix="!/", strip_commands=True):
    """Process a command in a message.
    
    This fixture returns a function that can be used to process a command in a message.
    
    Args:
        test_session: A test session
        mock_app: A mock app
        command_prefix: The command prefix to use
        strip_commands: Whether to strip commands from messages
        
    Returns:
        callable: A function that processes a command in a message
    """
    async def _process_command(text, preserve_unknown=False):
        """Process a command in a message.
        
        Args:
            text: The message text containing the command
            preserve_unknown: Whether to preserve unknown commands
            
        Returns:
            tuple: A tuple of (processed_messages, commands_found, processed_text)
        """
        messages = [ChatMessage(role="user", content=text)]
        processed_messages, commands_found = await process_commands_in_messages_test(
            messages,
            cast(SessionStateAdapter, test_session.state),
            app=mock_app,
            command_prefix=command_prefix,
            strip_commands=strip_commands,
            preserve_unknown=preserve_unknown,
        )
        processed_text = processed_messages[0].content if processed_messages else ""
        return processed_messages, commands_found, processed_text
    
    return _process_command


@pytest.fixture
def session_with_model(test_session, model_name="test-model", backend_type="openrouter"):
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
def session_with_project(test_session, project_name="test-project"):
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
def session_with_hello(test_session):
    """Create a session with hello_requested set to True.
    
    Args:
        test_session: A test session
        
    Returns:
        Session: A session with hello_requested set to True
    """
    current_state = test_session.state
    test_session.state = current_state.with_hello_requested(True)
    return test_session
