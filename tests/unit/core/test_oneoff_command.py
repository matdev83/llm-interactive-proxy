"""
Tests for the OneOff command in the new SOLID architecture.
"""

import pytest
from src.core.commands.handlers.oneoff_handler import OneOffCommandHandler
from src.core.domain.configuration.backend_config import BackendConfiguration
from src.core.domain.session import SessionState


@pytest.fixture
def oneoff_handler():
    """Create a OneOffCommandHandler for testing."""
    return OneOffCommandHandler()


@pytest.fixture
def session_state():
    """Create a session state for testing."""
    return SessionState(
        backend_config=BackendConfiguration(
            backend_type="openai", model="gpt-3.5-turbo"
        )
    )


def test_oneoff_handler_initialization(oneoff_handler):
    """Test that the OneOffCommandHandler initializes correctly."""
    assert oneoff_handler.name == "oneoff"
    assert "one-off" in oneoff_handler.aliases
    assert "one-time override" in oneoff_handler.description.lower()


def test_oneoff_handler_can_handle(oneoff_handler):
    """Test that the OneOffCommandHandler can handle the correct parameters."""
    assert oneoff_handler.can_handle("oneoff")
    assert oneoff_handler.can_handle("one-off")
    assert not oneoff_handler.can_handle("other")


def test_oneoff_handler_with_empty_value(oneoff_handler, session_state):
    """Test that the OneOffCommandHandler handles empty values correctly."""
    result = oneoff_handler.handle(None, session_state)
    assert not result.success
    assert "requires a backend/model argument" in result.message


def test_oneoff_handler_with_empty_dict(oneoff_handler, session_state):
    """Test that the OneOffCommandHandler handles empty dictionaries correctly."""
    result = oneoff_handler.handle({}, session_state)
    assert not result.success
    assert "requires a backend/model argument" in result.message


def test_oneoff_handler_with_invalid_format(oneoff_handler, session_state):
    """Test that the OneOffCommandHandler handles invalid formats correctly."""
    result = oneoff_handler.handle("invalid", session_state)
    assert not result.success
    assert "Invalid format" in result.message


def test_oneoff_handler_with_empty_backend(oneoff_handler, session_state):
    """Test that the OneOffCommandHandler handles empty backends correctly."""
    result = oneoff_handler.handle("/model", session_state)
    assert not result.success
    assert "Backend and model cannot be empty" in result.message


def test_oneoff_handler_with_empty_model(oneoff_handler, session_state):
    """Test that the OneOffCommandHandler handles empty models correctly."""
    result = oneoff_handler.handle("backend/", session_state)
    assert not result.success
    assert "Backend and model cannot be empty" in result.message


def test_oneoff_handler_with_valid_value_slash_format(oneoff_handler, session_state):
    """Test that the OneOffCommandHandler handles valid values with slash format correctly."""
    result = oneoff_handler.handle("openai/gpt-4", session_state)
    assert result.success
    assert "One-off route set to openai/gpt-4" in result.message
    assert result.new_state is not None
    assert result.new_state.backend_config.oneoff_backend == "openai"
    assert result.new_state.backend_config.oneoff_model == "gpt-4"


def test_oneoff_handler_with_valid_value_colon_format(oneoff_handler, session_state):
    """Test that the OneOffCommandHandler handles valid values with colon format correctly."""
    result = oneoff_handler.handle("anthropic:claude-3-opus", session_state)
    assert result.success
    assert "One-off route set to anthropic/claude-3-opus" in result.message
    assert result.new_state is not None
    assert result.new_state.backend_config.oneoff_backend == "anthropic"
    assert result.new_state.backend_config.oneoff_model == "claude-3-opus"


def test_oneoff_handler_with_valid_value_dict_format(oneoff_handler, session_state):
    """Test that the OneOffCommandHandler handles valid values with dictionary format correctly."""
    result = oneoff_handler.handle({"gemini/gemini-pro": ""}, session_state)
    assert result.success
    assert "One-off route set to gemini/gemini-pro" in result.message
    assert result.new_state is not None
    assert result.new_state.backend_config.oneoff_backend == "gemini"
    assert result.new_state.backend_config.oneoff_model == "gemini-pro"
