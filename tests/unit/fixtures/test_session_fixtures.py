"""Tests for session fixtures.

This module tests the session fixtures to ensure they work as expected.
"""

import pytest
from src.core.domain.session import Session, SessionStateAdapter

# Mark all tests in this module as isolated
pytestmark = pytest.mark.no_global_mock


def test_test_session_id(test_session_id):
    """Test that test_session_id returns a string that starts with test-session-."""
    assert isinstance(test_session_id, str)
    assert test_session_id.startswith("test-session-")


def test_multiple_session_ids(monkeypatch):
    """Test that multiple calls to generate_test_session_id return different values."""
    import uuid
    from tests.unit.fixtures.session_fixtures import generate_test_session_id
    
    # Mock uuid.uuid4 to return predictable values
    uuids = ["uuid1", "uuid2"]
    monkeypatch.setattr(uuid, "uuid4", lambda: uuids.pop(0))
    
    # Call the helper function directly
    id1 = generate_test_session_id()
    id2 = generate_test_session_id()
    
    assert id1 != id2
    assert id1 == "test-session-uuid1"
    assert id2 == "test-session-uuid2"


def test_test_session(test_session):
    """Test that test_session returns a Session instance."""
    assert isinstance(test_session, Session)
    assert test_session.session_id.startswith("test-session-")


def test_test_session_state(test_session_state):
    """Test that test_session_state returns a SessionStateAdapter instance."""
    assert isinstance(test_session_state, SessionStateAdapter)
    assert test_session_state.backend_config is not None
    assert test_session_state.backend_config.model is None
    assert test_session_state.backend_config.backend_type is None
    assert test_session_state.project is None


def test_test_session_with_model(test_session_with_model):
    """Test that test_session_with_model returns a Session with a model."""
    assert isinstance(test_session_with_model, Session)
    assert test_session_with_model.state.backend_config.model == "test-model"
    assert test_session_with_model.state.backend_config.backend_type == "openrouter"


def test_test_session_with_project(test_session_with_project):
    """Test that test_session_with_project returns a Session with a project."""
    assert isinstance(test_session_with_project, Session)
    assert test_session_with_project.state.project == "test-project"


def test_test_session_with_hello(test_session_with_hello):
    """Test that test_session_with_hello returns a Session with hello_requested."""
    assert isinstance(test_session_with_hello, Session)
    assert test_session_with_hello.state.hello_requested is True


def test_test_mock_app(test_mock_app):
    """Test that test_mock_app returns a FastAPI app."""
    from fastapi import FastAPI
    
    assert isinstance(test_mock_app, FastAPI)
    assert hasattr(test_mock_app, "state")
    assert test_mock_app.state.api_key_redaction_enabled is True
    assert "openrouter" in test_mock_app.state.functional_backends


def test_test_command_registry(test_command_registry):
    """Test that test_command_registry returns a CommandRegistry."""
    from src.core.services.command_service import CommandRegistry
    
    assert isinstance(test_command_registry, CommandRegistry)
    commands = test_command_registry.get_commands()
    assert "set" in commands
    assert "unset" in commands
    assert "hello" in commands