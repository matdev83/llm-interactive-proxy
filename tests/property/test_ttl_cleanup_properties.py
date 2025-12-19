"""Property-based tests for TTL cleanup in test execution reminder system.

**Feature: test-execution-reminder, Property 11: State TTL Cleanup**

This module tests that session states that haven't been accessed for longer
than the configured TTL period are removed from memory during cleanup cycles.
"""

from __future__ import annotations

from time import time

from hypothesis import given, settings
from hypothesis import strategies as st
from src.services.test_execution_reminder.test_execution_reminder_handler import (
    TestExecutionReminderHandler,
)

# Strategy for generating session IDs
session_ids = st.text(
    min_size=1,
    max_size=50,
    alphabet=st.characters(blacklist_categories=("Cs",), blacklist_characters="\x00"),
)

# Strategy for generating TTL values (in seconds)
ttl_seconds = st.integers(min_value=1, max_value=3600)

# Strategy for generating time offsets
time_offsets = st.integers(min_value=0, max_value=7200)


@settings(max_examples=50)
@given(
    session_id=session_ids,
    ttl_seconds=ttl_seconds,
    time_offset=time_offsets,
)
def test_ttl_cleanup_removes_expired_sessions(
    session_id: str,
    ttl_seconds: int,
    time_offset: int,
) -> None:
    """Test that sessions older than TTL are removed during cleanup.

    **Property 11: State TTL Cleanup**
    **Validates: Requirements 8.4**

    For any session state that has not been accessed for longer than the
    configured TTL period, the state should be removed from memory during
    the next cleanup cycle.
    """
    # Create handler with specific TTL
    handler = TestExecutionReminderHandler(
        enabled=True,
        state_ttl_seconds=ttl_seconds,
    )

    # Create a session
    handler._mark_session_dirty(session_id)

    # Verify session exists (without updating last_seen)
    assert session_id in handler._session_state
    state = handler._session_state[session_id]
    assert state.is_dirty is True

    # Record the last_seen time when session was created
    session_last_seen = state.last_seen

    # Simulate time passing by calculating future time
    future_time = session_last_seen + time_offset

    # Run cleanup with future time
    handler._prune_session_state(future_time)

    # Check if session should be removed
    if time_offset > ttl_seconds:
        # Session should be removed (expired)
        assert session_id not in handler._session_state
    else:
        # Session should still exist (not expired)
        assert session_id in handler._session_state


@settings(max_examples=50)
@given(
    session_id=session_ids,
    ttl_seconds=st.integers(min_value=10, max_value=100),
)
def test_ttl_cleanup_preserves_recent_sessions(
    session_id: str,
    ttl_seconds: int,
) -> None:
    """Test that recently accessed sessions are not removed.

    **Property 11: State TTL Cleanup**
    **Validates: Requirements 8.4**

    For any session state that has been accessed within the TTL period,
    the state should not be removed during cleanup.
    """
    # Create handler with specific TTL
    handler = TestExecutionReminderHandler(
        enabled=True,
        state_ttl_seconds=ttl_seconds,
    )

    # Create a session
    handler._mark_session_dirty(session_id)

    # Access the session (updates last_seen)
    state = handler._get_session_state(session_id)
    assert state is not None

    # Run cleanup immediately (session was just accessed)
    current_time = time()
    handler._prune_session_state(current_time)

    # Session should still exist
    assert session_id in handler._session_state


@settings(max_examples=50)
@given(
    session1_id=session_ids,
    session2_id=session_ids,
    ttl_seconds=st.integers(min_value=10, max_value=100),
)
def test_ttl_cleanup_selective_removal(
    session1_id: str,
    session2_id: str,
    ttl_seconds: int,
) -> None:
    """Test that only expired sessions are removed, not all sessions.

    **Property 11: State TTL Cleanup**
    **Validates: Requirements 8.4**

    For any set of sessions where some are expired and some are not,
    only the expired sessions should be removed during cleanup.
    """
    # Skip if session IDs are the same
    if session1_id == session2_id:
        return

    # Create handler with specific TTL
    handler = TestExecutionReminderHandler(
        enabled=True,
        state_ttl_seconds=ttl_seconds,
    )

    # Create two sessions
    handler._mark_session_dirty(session1_id)
    handler._mark_session_dirty(session2_id)

    # Verify both exist
    assert session1_id in handler._session_state
    assert session2_id in handler._session_state

    # Manually set session1's last_seen to be expired
    current_time = time()
    handler._session_state[session1_id].last_seen = current_time - ttl_seconds - 10

    # Keep session2 recent by accessing it
    handler._get_session_state(session2_id)

    # Run cleanup
    handler._prune_session_state(current_time)

    # Session 1 should be removed (expired)
    assert session1_id not in handler._session_state

    # Session 2 should still exist (recent)
    assert session2_id in handler._session_state


@settings(max_examples=50)
@given(
    num_sessions=st.integers(min_value=1, max_value=20),
    ttl_seconds=st.integers(min_value=10, max_value=100),
)
def test_ttl_cleanup_multiple_sessions(
    num_sessions: int,
    ttl_seconds: int,
) -> None:
    """Test TTL cleanup with multiple sessions.

    **Property 11: State TTL Cleanup**
    **Validates: Requirements 8.4**

    For any number of sessions, cleanup should correctly identify and
    remove all expired sessions while preserving recent ones.
    """
    # Create handler with specific TTL
    handler = TestExecutionReminderHandler(
        enabled=True,
        state_ttl_seconds=ttl_seconds,
    )

    # Create multiple sessions with unique IDs
    session_ids = [f"session_{i}" for i in range(num_sessions)]
    for session_id in session_ids:
        handler._mark_session_dirty(session_id)

    # Verify all sessions exist
    assert len(handler._session_state) == num_sessions

    # Make half of them expired
    current_time = time()
    expired_count = num_sessions // 2
    for i in range(expired_count):
        handler._session_state[session_ids[i]].last_seen = (
            current_time - ttl_seconds - 10
        )

    # Run cleanup
    handler._prune_session_state(current_time)

    # Verify correct number of sessions remain
    remaining = len(handler._session_state)
    expected_remaining = num_sessions - expired_count

    assert remaining == expected_remaining

    # Verify the correct sessions were removed
    for i in range(expired_count):
        assert session_ids[i] not in handler._session_state

    for i in range(expired_count, num_sessions):
        assert session_ids[i] in handler._session_state


@settings(max_examples=50)
@given(
    session_id=session_ids,
    ttl_seconds=st.integers(min_value=10, max_value=100),
    max_sessions=st.integers(min_value=5, max_value=50),
)
def test_max_sessions_limit_enforcement(
    session_id: str,
    ttl_seconds: int,
    max_sessions: int,
) -> None:
    """Test that max_sessions limit is enforced during cleanup.

    **Property 11: State TTL Cleanup**
    **Validates: Requirements 8.4**

    For any handler with a max_sessions limit, when the number of sessions
    exceeds the limit, the oldest sessions should be removed to enforce
    the limit.
    """
    # Create handler with specific limits
    handler = TestExecutionReminderHandler(
        enabled=True,
        state_ttl_seconds=ttl_seconds,
        max_sessions=max_sessions,
    )

    # Create more sessions than the limit
    num_sessions = max_sessions + 10
    session_ids = [f"session_{i}" for i in range(num_sessions)]

    for session_id in session_ids:
        handler._mark_session_dirty(session_id)
        # Small delay to ensure different last_seen times
        current_time = time()
        handler._prune_session_state(current_time)

    # Verify the limit is enforced
    assert len(handler._session_state) <= max_sessions


@settings(max_examples=50)
@given(
    ttl_seconds=st.integers(min_value=10, max_value=100),
)
def test_ttl_cleanup_empty_state(
    ttl_seconds: int,
) -> None:
    """Test that cleanup works correctly with no sessions.

    **Property 11: State TTL Cleanup**
    **Validates: Requirements 8.4**

    For any handler with no sessions, cleanup should complete without errors.
    """
    # Create handler with specific TTL
    handler = TestExecutionReminderHandler(
        enabled=True,
        state_ttl_seconds=ttl_seconds,
    )

    # Verify no sessions exist
    assert len(handler._session_state) == 0

    # Run cleanup (should not raise any errors)
    current_time = time()
    handler._prune_session_state(current_time)

    # Verify still no sessions
    assert len(handler._session_state) == 0


@settings(max_examples=50)
@given(
    session_id=session_ids,
    ttl_seconds=st.integers(min_value=10, max_value=100),
)
def test_ttl_cleanup_updates_last_seen(
    session_id: str,
    ttl_seconds: int,
) -> None:
    """Test that accessing a session updates last_seen and prevents removal.

    **Property 11: State TTL Cleanup**
    **Validates: Requirements 8.4**

    For any session, accessing it should update the last_seen timestamp
    and prevent it from being removed during the next cleanup cycle.
    """
    # Create handler with specific TTL
    handler = TestExecutionReminderHandler(
        enabled=True,
        state_ttl_seconds=ttl_seconds,
    )

    # Create a session
    handler._mark_session_dirty(session_id)

    # Get initial last_seen
    state = handler._get_session_state(session_id)
    assert state is not None
    # initial_last_seen = state.last_seen  # Unused

    # Manually set last_seen to be old (but not expired yet)
    current_time = time()
    handler._session_state[session_id].last_seen = current_time - ttl_seconds + 5

    # Access the session (should update last_seen)
    state = handler._get_session_state(session_id)
    assert state is not None

    # Verify last_seen was updated
    assert state.last_seen > current_time - ttl_seconds + 5

    # Run cleanup with time that would have expired the old timestamp
    future_time = current_time + 10
    handler._prune_session_state(future_time)

    # Session should still exist because last_seen was updated
    assert session_id in handler._session_state
