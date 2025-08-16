"""
Tests for the Hello command in the new SOLID architecture.
"""

import pytest

from src.core.commands.handlers.hello_handler import HelloCommandHandler
from src.core.domain.session import SessionState


@pytest.fixture
def hello_handler():
    """Create a HelloCommandHandler for testing."""
    return HelloCommandHandler()


@pytest.fixture
def session_state():
    """Create a session state for testing."""
    return SessionState()


def test_hello_handler_initialization(hello_handler):
    """Test that the HelloCommandHandler initializes correctly."""
    assert hello_handler.name == "hello"
    assert "welcome banner" in hello_handler.description.lower()


def test_hello_handler_can_handle(hello_handler):
    """Test that the HelloCommandHandler can handle the correct parameters."""
    assert hello_handler.can_handle("hello")
    assert hello_handler.can_handle("HELLO")
    assert not hello_handler.can_handle("other")


def test_hello_handler_execution(hello_handler, session_state):
    """Test that the HelloCommandHandler sets the hello_requested flag."""
    result = hello_handler.handle(None, session_state)
    assert result.success
    assert "hello acknowledged" in result.message
    assert result.new_state is not None
    assert result.new_state.hello_requested
