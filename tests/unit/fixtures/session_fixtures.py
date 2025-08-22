"""Test fixtures for session state.

This module provides fixtures for creating and managing session state in tests.
These fixtures help ensure test isolation by providing a fresh session state
for each test.
"""

import uuid
from typing import Any, Optional, cast

import pytest
from fastapi import FastAPI

from src.core.domain.configuration.backend_config import BackendConfiguration
from src.core.domain.session import Session, SessionState, SessionStateAdapter


def generate_test_session_id() -> str:
    """Generate a unique session ID for testing.
    
    This is a helper function that can be called directly in tests.
    
    Returns:
        str: A unique session ID
    """
    return f"test-session-{uuid.uuid4()}"


@pytest.fixture
def test_session_id() -> str:
    """Generate a unique session ID for each test.
    
    Returns:
        str: A unique session ID
    """
    return generate_test_session_id()


@pytest.fixture
def test_session(test_session_id: str) -> Session:
    """Create a test session with a unique ID.
    
    Args:
        test_session_id: A unique session ID from the test_session_id fixture
        
    Returns:
        Session: A fresh session instance with a unique ID
    """
    return Session(session_id=test_session_id)


@pytest.fixture
def test_session_state(test_session: Session) -> SessionStateAdapter:
    """Get the session state from a test session.
    
    Args:
        test_session: A test session from the test_session fixture
        
    Returns:
        SessionStateAdapter: The session state adapter from the test session
    """
    return test_session.state


@pytest.fixture
def test_session_with_model(test_session: Session, model_name: str = "test-model", backend_type: str = "openrouter") -> Session:
    """Create a test session with a specific model and backend.
    
    Args:
        test_session: A test session from the test_session fixture
        model_name: The name of the model to set
        backend_type: The type of backend to set
        
    Returns:
        Session: A session with the specified model and backend
    """
    current_state = test_session.state
    new_backend_config = current_state.backend_config.with_model(model_name)
    new_backend_config = new_backend_config.with_backend(backend_type)
    test_session.state = current_state.with_backend_config(cast(BackendConfiguration, new_backend_config))
    return test_session


@pytest.fixture
def test_session_with_project(test_session: Session, project_name: str = "test-project") -> Session:
    """Create a test session with a specific project.
    
    Args:
        test_session: A test session from the test_session fixture
        project_name: The name of the project to set
        
    Returns:
        Session: A session with the specified project
    """
    current_state = test_session.state
    test_session.state = current_state.with_project(project_name)
    return test_session


@pytest.fixture
def test_session_with_hello(test_session: Session) -> Session:
    """Create a test session with hello_requested set to True.
    
    Args:
        test_session: A test session from the test_session fixture
        
    Returns:
        Session: A session with hello_requested set to True
    """
    current_state = test_session.state
    test_session.state = current_state.with_hello_requested(True)
    return test_session


@pytest.fixture
def test_mock_app() -> FastAPI:
    """Create a mock FastAPI app for testing.
    
    Returns:
        FastAPI: A mock FastAPI app
    """
    from unittest.mock import MagicMock, PropertyMock
    
    app = FastAPI()
    app.state = MagicMock()
    type(app.state).api_key_redaction_enabled = PropertyMock(return_value=True)
    app.state.functional_backends = set(["openai", "anthropic", "openrouter", "gemini"])
    return app


@pytest.fixture
def test_command_registry():
    """Set up a test command registry for testing.
    
    Returns:
        CommandRegistry: A command registry with mock commands
    """
    from tests.unit.mock_commands import setup_test_command_registry_for_unit_tests
    return setup_test_command_registry_for_unit_tests()
