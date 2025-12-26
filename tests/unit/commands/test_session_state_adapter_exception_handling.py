"""Test exception handling improvements in SessionStateAdapter."""

import logging

import pytest
from src.core.commands.session_state_adapter import SessionStateAdapter
from src.core.domain.session import Session, SessionState


def test_get_command_prefix_logs_on_attribute_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test that get_command_prefix logs when AttributeError occurs."""
    caplog.set_level(logging.DEBUG)

    session = Session(session_id="test", state=SessionState())
    adapter = SessionStateAdapter(session)

    # Verify fallback path works when override is not set
    adapter._local_state["command_prefix"] = "/local"
    result = adapter.get_command_prefix()
    assert result == "/local"


def test_get_command_prefix_returns_override_on_success() -> None:
    """Test that get_command_prefix returns override when successful."""
    session = Session(
        session_id="test",
        state=SessionState().with_command_prefix_override("/test"),
    )
    adapter = SessionStateAdapter(session)

    result = adapter.get_command_prefix()

    assert result == "/test"


def test_get_command_prefix_returns_local_fallback() -> None:
    """Test that get_command_prefix falls back to local state."""
    session = Session(session_id="test", state=SessionState())
    adapter = SessionStateAdapter(session)
    adapter._local_state["command_prefix"] = "/local"

    result = adapter.get_command_prefix()

    assert result == "/local"


def test_get_command_prefix_filters_none_and_empty_strings() -> None:
    """Test that get_command_prefix filters None and empty strings."""
    session = Session(
        session_id="test",
        state=SessionState().with_command_prefix_override(None),
    )
    adapter = SessionStateAdapter(session)

    assert adapter.get_command_prefix() is None

    session = Session(
        session_id="test",
        state=SessionState().with_command_prefix_override(""),
    )
    adapter = SessionStateAdapter(session)
    assert adapter.get_command_prefix() is None

    session = Session(session_id="test", state=SessionState())
    adapter = SessionStateAdapter(session)
    adapter._local_state["command_prefix"] = "/local"
    assert adapter.get_command_prefix() == "/local"
