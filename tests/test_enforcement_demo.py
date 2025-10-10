"""Behavioral tests for the :mod:`src.core.domain.session` module."""

from datetime import datetime, timezone

from src.core.domain.session import Session, SessionStateAdapter


def test_session_exposes_initialized_identifier() -> None:
    """Session.session_id should return the identifier passed to the constructor."""

    session = Session(session_id="test-123")

    assert session.session_id == "test-123"


def test_session_initializes_state_and_timestamps() -> None:
    """A newly created Session should provide defaults for state and timestamps."""

    timestamp = datetime.now(timezone.utc)

    session = Session(
        session_id="session-1", created_at=timestamp, last_active_at=timestamp
    )

    assert isinstance(session.state, SessionStateAdapter)
    assert session.created_at is timestamp
    assert session.last_active_at is timestamp
    assert session.history == []
