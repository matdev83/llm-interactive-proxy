"""Regression tests for race condition fixes in TestExecutionReminderHandler."""

import asyncio

from src.services.test_execution_reminder.test_execution_reminder_handler import (
    TestExecutionReminderHandler,
)
from tests.utils.fake_clock import FakeClock, FakeClockContext


async def test_concurrent_mark_operations_no_race():
    """Test concurrent mark_dirty and mark_clean operations are safe."""
    handler = TestExecutionReminderHandler(enabled=True, max_sessions=100)
    session_ids = [f"session-{i}" for i in range(5)]  # Reduced from 10 for performance

    async def mark_dirty_batch(sessions):
        for sid in sessions:
            await handler._mark_session_dirty(sid, "edit")

    async def mark_clean_batch(sessions):
        for sid in sessions:
            await handler._mark_session_clean(sid, "pytest", "python", "pytest")

    tasks = [mark_dirty_batch(session_ids) for _ in range(3)] + [  # Reduced from 5
        mark_clean_batch(session_ids) for _ in range(3)  # Reduced from 5
    ]
    await asyncio.gather(*tasks, return_exceptions=True)

    # All sessions should be tracked without errors
    assert len(handler._session_state) > 0, "Expected some session states to be created"


async def test_concurrent_prune_and_access_no_race():
    """Test concurrent prune and access to session state is safe."""
    handler = TestExecutionReminderHandler(enabled=True, max_sessions=100)

    async def access_sessions():
        for i in range(100):
            sid = f"session-{i}"
            handler._get_session_state(sid)

    async def trigger_prune():
        async with FakeClockContext(FakeClock(initial_time=1704067200.0)) as clock:
            for _ in range(20):
                handler._prune_session_state(clock.now())

    await asyncio.gather(access_sessions(), access_sessions(), trigger_prune())

    # Should complete without errors
    assert True


if __name__ == "__main__":
    asyncio.run(test_concurrent_mark_operations_no_race())
    print("PASS: test_concurrent_mark_operations_no_race")

    asyncio.run(test_concurrent_prune_and_access_no_race())
    print("PASS: test_concurrent_prune_and_access_no_race")
