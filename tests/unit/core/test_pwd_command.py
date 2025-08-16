"""
Tests for the PWD command in the new SOLID architecture.
"""

import pytest
from src.core.commands.handlers.pwd_handler import PwdCommandHandler
from src.core.domain.session import SessionState


@pytest.fixture
def pwd_handler():
    """Create a PwdCommandHandler for testing."""
    return PwdCommandHandler()


@pytest.fixture
def session_state():
    """Create a session state for testing."""
    return SessionState()


def test_pwd_handler_initialization(pwd_handler):
    """Test that the PwdCommandHandler initializes correctly."""
    assert pwd_handler.name == "pwd"
    assert "project directory" in pwd_handler.description.lower()


def test_pwd_handler_can_handle(pwd_handler):
    """Test that the PwdCommandHandler can handle the correct parameters."""
    assert pwd_handler.can_handle("pwd")
    assert pwd_handler.can_handle("PWD")
    assert not pwd_handler.can_handle("other")


def test_pwd_handler_with_project_dir_set(pwd_handler):
    """Test that the PwdCommandHandler handles project directories correctly."""
    state = SessionState(project_dir="/test/project/dir")
    result = pwd_handler.handle(None, state)
    assert result.success
    assert result.message == "/test/project/dir"


def test_pwd_handler_without_project_dir(pwd_handler, session_state):
    """Test that the PwdCommandHandler handles missing project directories correctly."""
    result = pwd_handler.handle(None, session_state)
    assert not result.success
    assert "Project directory not set" in result.message
