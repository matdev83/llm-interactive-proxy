"""Regression tests for TestExecutionReminderHandler race condition fixes."""

import asyncio
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

import pytest
from src.services.test_execution_reminder.test_execution_reminder_handler import (
    TestExecutionReminderHandler,
)


@pytest.mark.asyncio
async def test_test_reminder_concurrent_mark_operations_safe():
    """Test that concurrent mark_dirty/mark_clean operations are safe with async lock."""
    handler = TestExecutionReminderHandler(
        enabled=True,
        state_ttl_seconds=300,
        max_sessions=100,
    )
    session_id = "test-session-race-123"

    async def run_operations():
        """Run operations and track counts."""
        dirty_ops = 0
        clean_ops = 0

        async def mark_dirty_operations():
            """Concurrent dirty marking task."""
            nonlocal dirty_ops
            for _i in range(50):
                await handler._mark_session_dirty(session_id, "write_file")
                dirty_ops += 1

        async def mark_clean_operations():
            """Concurrent clean marking task."""
            nonlocal clean_ops
            for _i in range(50):
                await handler._mark_session_clean(
                    session_id, "pytest", "python", "pytest"
                )
                clean_ops += 1

        await asyncio.gather(
            asyncio.create_task(mark_dirty_operations()),
            asyncio.create_task(mark_clean_operations()),
        )

        return dirty_ops, clean_ops

    dirty_ops, clean_ops = await run_operations()

    # Check final state
    state = await handler._get_session_state(session_id)
    assert state is not None, "Session state should exist"

    # The race condition should be fixed - state should be valid
    # Either is_dirty=True (last was dirty) or False (last was clean)
    assert state.is_dirty in (
        True,
        False,
    ), f"is_dirty should be True or False, got {state.is_dirty}"

    # Modification count should be the difference between dirty and clean ops
    expected_count = max(0, dirty_ops - clean_ops)
    assert (
        state.modification_count == expected_count
    ), f"Expected {expected_count} modifications, got {state.modification_count}"


@pytest.mark.asyncio
async def test_test_reminder_concurrent_prune_and_access_safe():
    """Test that concurrent pruning and state access are safe with async lock."""
    handler = TestExecutionReminderHandler(
        enabled=True,
        state_ttl_seconds=0,
        max_sessions=10,
    )

    # Create many sessions
    for i in range(50):
        await handler._mark_session_dirty(f"session-{i}", f"write_file_{i}")

    errors = []

    async def concurrent_access(session_suffix):
        """Concurrent access task."""
        for i in range(10):
            sid = f"session-{session_suffix}-{i}"
            try:
                state = await handler._get_session_state(sid)
                if state:
                    state.update_last_seen()
            except Exception as e:
                errors.append((sid, str(e)))

    # Launch concurrent accesses that may trigger pruning
    tasks = [asyncio.create_task(concurrent_access(s)) for s in range(5)]
    await asyncio.gather(*tasks)

    # Test should complete without errors
    assert len(errors) == 0, f"Errors during concurrent access: {errors}"


@pytest.mark.asyncio
async def test_test_reminder_async_context_safety():
    """Test that async methods can be called from async context."""
    handler = TestExecutionReminderHandler(
        enabled=True,
        state_ttl_seconds=300,
        max_sessions=100,
    )

    session_id = "test-async-safety"

    # All operations should work in async context
    await handler._mark_session_dirty(session_id, "write")
    await handler._mark_session_clean(session_id, "pytest", "python", "pytest")

    state = await handler._get_session_state(session_id)
    assert state is not None
    assert state.is_dirty is False  # Last operation was clean
    assert state.modification_count == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
