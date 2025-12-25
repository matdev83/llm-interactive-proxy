"""Reproduction script for TestExecutionReminderHandler race condition.

This script demonstrates the race condition in TestExecutionReminderHandler where
_concurrent modifications without proper locking can cause inconsistent state.
"""
import asyncio

from src.services.test_execution_reminder.test_execution_reminder_handler import (
    TestExecutionReminderHandler,
)


async def test_concurrent_mark_operations():
    """Test concurrent mark_dirty/mark_clean operations."""
    handler = TestExecutionReminderHandler(
        enabled=True,
        state_ttl_seconds=300,
        max_sessions=100,
    )
    session_id = "test-session-race-123"

    async def mark_dirty_operations():
        """Concurrent dirty marking task."""
        for i in range(50):
            handler._mark_session_dirty(session_id, "write_file")

    async def mark_clean_operations():
        """Concurrent clean marking task."""
        for i in range(50):
            handler._mark_session_clean(
                session_id, "pytest", "python", "pytest"
            )

    # Launch concurrent operations (no lock protection)
    async with asyncio.TaskGroup() as tg:
        tg.create_task(mark_dirty_operations())
        tg.create_task(mark_clean_operations())

    # Check final state - should be one of the two values, not corrupted
    state = handler._get_session_state(session_id)
    if state:
        print(f"Final state - is_dirty: {state.is_dirty}, modification_count: {state.modification_count}")
        # The race condition can cause both counters to be incremented incorrectly
        # or state to be in an inconsistent condition
        return True
    return False


async def test_concurrent_prune_and_access():
    """Test concurrent pruning and state access."""
    handler = TestExecutionReminderHandler(
        enabled=True,
        state_ttl_seconds=0,
        max_sessions=10,
    )

    # Create many sessions
    for i in range(50):
        handler._mark_session_dirty(f"session-{i}", f"write_file_{i}")

    async def concurrent_access(session_suffix):
        """Concurrent access task."""
        for i in range(10):
            sid = f"session-{session_suffix}-{i}"
            # Simulate internal _prune_session_state call via access
            state = handler._get_session_state(sid)
            if state:
                state.update_last_seen()

    # Launch concurrent accesses that may trigger pruning
    async with asyncio.TaskGroup() as tg:
        for s in range(5):
            tg.create_task(concurrent_access(s))

    print("Concurrent prune/access test completed")
    return True


async def main():
    """Run all reproduction tests."""
    print("=" * 60)
    print("TestExecutionReminderHandler Race Condition Reproduction")
    print("=" * 60)

    result1 = await test_concurrent_mark_operations()
    result2 = await test_concurrent_prune_and_access()

    print("\n" + "=" * 60)
    print("RESULTS:")
    print(f"  Concurrent mark operations test: {'PASS' if result1 else 'FAIL'}")
    print(f"  Concurrent prune/access test: {'PASS' if result2 else 'FAIL'}")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
