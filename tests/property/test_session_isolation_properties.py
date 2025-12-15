"""Property-based tests for session isolation in test execution reminder system.

**Feature: test-execution-reminder, Property 7: Session Isolation**

This module tests that tool calls processed in one session do not affect
the state of other sessions, ensuring complete session independence.
"""

from __future__ import annotations

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

# Strategy for generating file modification tool names
file_modification_tools = st.sampled_from(
    [
        "write_file",
        "str_replace",
        "apply_diff",
        "replace_lines",
        "patch_file",
    ]
)


@settings(max_examples=100)
@given(
    session1_id=session_ids,
    session2_id=session_ids,
    tool_name=file_modification_tools,
)
def test_session_isolation_file_modifications(
    session1_id: str,
    session2_id: str,
    tool_name: str,
) -> None:
    """Test that file modifications in one session don't affect another session.

    **Property 7: Session Isolation**
    **Validates: Requirements 8.3**

    For any two different sessions with different session IDs, tool calls
    processed in one session should not affect the state of the other session.
    """
    # Skip if session IDs are the same (not testing isolation in that case)
    if session1_id == session2_id:
        return

    # Create handler
    handler = TestExecutionReminderHandler(enabled=True)

    # Mark session 1 as dirty
    handler._mark_session_dirty(session1_id)

    # Get state for both sessions
    state1 = handler._get_session_state(session1_id)
    state2 = handler._get_session_state(session2_id)

    # Session 1 should be dirty
    assert state1 is not None
    assert state1.is_dirty is True
    assert state1.modification_count == 1

    # Session 2 should either not exist or be clean
    if state2 is not None:
        assert state2.is_dirty is False
        assert state2.modification_count == 0


@settings(max_examples=100)
@given(
    session1_id=session_ids,
    session2_id=session_ids,
    session3_id=session_ids,
)
def test_session_isolation_multiple_sessions(
    session1_id: str,
    session2_id: str,
    session3_id: str,
) -> None:
    """Test isolation across multiple sessions with different operations.

    **Property 7: Session Isolation**
    **Validates: Requirements 8.3**

    For any set of sessions, operations in one session should not affect
    the state of other sessions.
    """
    # Skip if any session IDs are the same
    if len({session1_id, session2_id, session3_id}) < 3:
        return

    # Create handler
    handler = TestExecutionReminderHandler(enabled=True)

    # Session 1: mark dirty
    handler._mark_session_dirty(session1_id)

    # Session 2: mark dirty then clean
    handler._mark_session_dirty(session2_id)
    handler._mark_session_clean(session2_id, "pytest", "python", "pytest")

    # Session 3: don't touch

    # Get states
    state1 = handler._get_session_state(session1_id)
    state2 = handler._get_session_state(session2_id)
    state3 = handler._get_session_state(session3_id)

    # Verify session 1 is dirty
    assert state1 is not None
    assert state1.is_dirty is True
    assert state1.modification_count == 1

    # Verify session 2 is clean
    assert state2 is not None
    assert state2.is_dirty is False
    assert state2.modification_count == 0

    # Verify session 3 is either not created or clean
    if state3 is not None:
        assert state3.is_dirty is False
        assert state3.modification_count == 0


@settings(max_examples=100)
@given(
    session1_id=session_ids,
    session2_id=session_ids,
    modifications1=st.integers(min_value=1, max_value=10),
    modifications2=st.integers(min_value=1, max_value=10),
)
def test_session_isolation_modification_counts(
    session1_id: str,
    session2_id: str,
    modifications1: int,
    modifications2: int,
) -> None:
    """Test that modification counts are independent per session.

    **Property 7: Session Isolation**
    **Validates: Requirements 8.3**

    For any two different sessions, the modification count in one session
    should not affect the modification count in another session.
    """
    # Skip if session IDs are the same
    if session1_id == session2_id:
        return

    # Create handler
    handler = TestExecutionReminderHandler(enabled=True)

    # Mark session 1 dirty multiple times
    for _ in range(modifications1):
        handler._mark_session_dirty(session1_id)

    # Mark session 2 dirty multiple times
    for _ in range(modifications2):
        handler._mark_session_dirty(session2_id)

    # Get states
    state1 = handler._get_session_state(session1_id)
    state2 = handler._get_session_state(session2_id)

    # Verify each session has its own modification count
    assert state1 is not None
    assert state1.modification_count == modifications1

    assert state2 is not None
    assert state2.modification_count == modifications2


@settings(max_examples=100)
@given(
    session1_id=session_ids,
    session2_id=session_ids,
)
def test_session_isolation_clean_dirty_transitions(
    session1_id: str,
    session2_id: str,
) -> None:
    """Test that state transitions in one session don't affect another.

    **Property 7: Session Isolation**
    **Validates: Requirements 8.3**

    For any two different sessions, transitioning one session from dirty to
    clean should not affect the state of the other session.
    """
    # Skip if session IDs are the same
    if session1_id == session2_id:
        return

    # Create handler
    handler = TestExecutionReminderHandler(enabled=True)

    # Both sessions start dirty
    handler._mark_session_dirty(session1_id)
    handler._mark_session_dirty(session2_id)

    # Verify both are dirty
    state1 = handler._get_session_state(session1_id)
    state2 = handler._get_session_state(session2_id)
    assert state1 is not None and state1.is_dirty is True
    assert state2 is not None and state2.is_dirty is True

    # Clean session 1
    handler._mark_session_clean(session1_id, "pytest", "python", "pytest")

    # Get states again
    state1 = handler._get_session_state(session1_id)
    state2 = handler._get_session_state(session2_id)

    # Session 1 should be clean
    assert state1 is not None
    assert state1.is_dirty is False
    assert state1.modification_count == 0

    # Session 2 should still be dirty
    assert state2 is not None
    assert state2.is_dirty is True
    assert state2.modification_count == 1
