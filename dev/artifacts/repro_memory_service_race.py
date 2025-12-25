"""Reproduction script for race condition in _analysis_in_progress access.

This script demonstrates that _analysis_in_progress dict in MemoryService
is accessed without proper lock protection in some methods.
"""

import asyncio
import sys

from src.core.memory.config import MemoryConfiguration
from src.core.memory.repository import IMemoryRepository
from src.core.memory.service import MemoryService


class MockRepository(IMemoryRepository):
    """Mock repository for testing."""

    async def get_or_create_project_id(self, user_id: str, project_root: str) -> str:
        return f"{user_id}:{project_root}"

    async def store_session_summary(self, session_id: str, summary: dict) -> bool:
        return True


async def test_race_condition_in_analysis_in_progress():
    """Test race condition when _analysis_in_progress is accessed concurrently."""
    config = MemoryConfiguration(
        available=True,
        analysis_queue_maxsize=100,
    )
    repo = MockRepository()
    service = MemoryService(config, repo)

    # Enable memory for multiple sessions
    session_ids = [f"session_{i}" for i in range(10)]
    for sid in session_ids:
        await service.enable_for_session(sid, "user1", project_root="/tmp/test")

    # Mark sessions as complete (adds to _analysis_in_progress)
    for sid in session_ids:
        await service.mark_session_complete(sid)

    # Now try to get pending sessions from multiple concurrent tasks
    errors = []
    results = []

    async def get_pending_task(task_id):
        """Task that gets pending analysis."""
        try:
            session_id = await service.get_pending_analysis_session()
            if session_id:
                results.append(f"Task {task_id} got session: {session_id}")
            else:
                results.append(f"Task {task_id} got: None")
        except Exception as e:
            errors.append(f"Task {task_id} error: {e}")

    # Run multiple tasks concurrently
    tasks = [asyncio.create_task(get_pending_task(i)) for i in range(20)]
    await asyncio.gather(*tasks, return_exceptions=True)

    if errors:
        print("RACE CONDITION DETECTED:")
        for error in errors:
            print(f"  {error}")
        return False
    else:
        print("No errors detected")
        print(f"Got {len(results)} results from pending analysis queries")
        return True


async def test_analysis_in_progress_eviction_race():
    """Test race condition during eviction of analysis_in_progress entries."""
    config = MemoryConfiguration(
        available=True,
        analysis_queue_maxsize=100,
    )
    repo = MockRepository()
    service = MemoryService(config, repo)

    # Enable many sessions to trigger eviction
    max_limit = 5000
    session_ids = [f"session_{i}" for i in range(max_limit + 10)]

    for sid in session_ids:
        await service.enable_for_session(sid, "user1", project_root="/tmp/test")
        await service.mark_session_complete(sid)

    # Try to get pending sessions concurrently
    errors = []

    async def get_session_task():
        """Task that tries to get a pending session."""
        try:
            session_id = await service.get_pending_analysis_session()
            return session_id
        except Exception as e:
            errors.append(f"Error getting session: {e}")
            return None

    # Create many concurrent tasks
    tasks = [asyncio.create_task(get_session_task()) for _ in range(100)]
    await asyncio.gather(*tasks, return_exceptions=True)

    if errors:
        print("EVOCATION RACE CONDITION DETECTED:")
        for error in errors[:10]:
            print(f"  {error}")
        return False
    else:
        print("No eviction race errors detected")
        return True


if __name__ == "__main__":
    print("=" * 60)
    print("Test 1: Race condition in _analysis_in_progress access")
    print("=" * 60)
    asyncio.run(test_race_condition_in_analysis_in_progress())

    print("\n" + "=" * 60)
    print("Test 2: Race condition during eviction")
    print("=" * 60)
    asyncio.run(test_analysis_in_progress_eviction_race())
