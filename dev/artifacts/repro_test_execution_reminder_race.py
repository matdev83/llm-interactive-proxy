"""Reproduce race condition in TestExecutionReminderHandler._session_state"""

import asyncio
import sys
from pathlib import Path
from time import time

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.services.test_execution_reminder.test_execution_reminder_handler import (
    TestExecutionReminderHandler,
)


async def test_concurrent_mark_operations():
    """Test concurrent mark_dirty and mark_clean operations."""
    handler = TestExecutionReminderHandler(enabled=True, max_sessions=100)
    session_ids = [f"session-{i}" for i in range(20)]
    errors = []

    async def mark_dirty_batch(sessions):
        batch_errors = []
        for sid in sessions:
            try:
                handler._mark_session_dirty(sid, "edit")
            except Exception as e:
                batch_errors.append(e)
        return batch_errors

    async def mark_clean_batch(sessions):
        batch_errors = []
        for sid in sessions:
            try:
                handler._mark_session_clean(sid, "pytest", "python", "pytest")
            except Exception as e:
                batch_errors.append(e)
        return batch_errors

    tasks = [mark_dirty_batch(session_ids) for _ in range(10)] + [
        mark_clean_batch(session_ids) for _ in range(10)
    ]
    all_errors = await asyncio.gather(*tasks)
    for batch_errors in all_errors:
        errors.extend(batch_errors)

    print(f"Total errors: {len(errors)}")
    if errors:
        for e in errors[:5]:
            print(f"  Error: {e}")

    return len(errors) == 0


async def test_concurrent_prune_and_access():
    """Test concurrent prune and access to session state."""
    handler = TestExecutionReminderHandler(enabled=True, max_sessions=100)
    errors = []

    async def access_sessions():
        batch_errors = []
        for i in range(50):
            sid = f"session-{i}"
            try:
                handler._get_session_state(sid)
            except Exception as e:
                batch_errors.append(e)
        return batch_errors

    async def trigger_prune():
        batch_errors = []
        for _ in range(10):
            try:
                handler._prune_session_state(time())
            except Exception as e:
                batch_errors.append(e)
        return batch_errors

    all_errors = await asyncio.gather(access_sessions(), access_sessions(), trigger_prune())
    for batch_errors in all_errors:
        errors.extend(batch_errors)

    print(f"Prune/access errors: {len(errors)}")
    if errors:
        for e in errors[:5]:
            print(f"  Error: {e}")

    return len(errors) == 0


if __name__ == "__main__":
    success1 = asyncio.run(test_concurrent_mark_operations())
    success2 = asyncio.run(test_concurrent_prune_and_access())
    if success1 and success2:
        print("PASS: No race condition detected")
    else:
        print("FAIL: Race condition or errors detected")
        sys.exit(1)
