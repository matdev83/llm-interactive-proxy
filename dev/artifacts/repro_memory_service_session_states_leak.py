"""Repro script to demonstrate memory leak in MemoryService._session_states.

The issue: _session_states dictionary grows unbounded because sessions are only
removed when:
1. disable_for_session() is called manually
2. complete_analysis() is called after analysis completes

If analysis never completes (queue full, worker crashes, etc.), sessions remain
in _session_states forever, causing unbounded memory growth.
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.core.memory.config import MemoryConfiguration
from src.core.memory.repository import IMemoryRepository
from src.core.memory.service import MemoryService


class MockMemoryRepository:
    """Mock repository for testing."""

    async def initialize_schema(self) -> None:
        pass

    async def save_session_summary(self, summary) -> None:
        pass

    async def get_recent_sessions(
        self, user_id: str, limit: int, tenant_id=None, project_id=None, project_root=None
    ) -> list:
        return []

    async def delete_old_sessions(self, before_date) -> int:
        return 0

    async def get_or_create_project_id(self, user_id: str, project_root: str) -> str:
        return f"project-{user_id}-{project_root}"


async def main():
    """Demonstrate the memory leak."""
    print("=" * 80)
    print("Memory Leak Repro: MemoryService._session_states")
    print("=" * 80)
    print()

    # Create memory service with small queue to simulate queue full scenario
    config = MemoryConfiguration(
        available=True,
        analysis_queue_maxsize=2,  # Small queue to simulate backpressure
        summarization_delay_seconds=0,  # Immediate analysis
        require_project_discovery=False,  # Allow sessions without project root
    )
    repository = MockMemoryRepository()
    memory_service = MemoryService(config, repository)

    print(f"Initial session count: {memory_service.get_active_session_count()}")
    print(f"Analysis queue size: {memory_service.get_analysis_queue_size()}")
    print()

    # Enable many sessions (more than queue size)
    num_sessions = 10
    print(f"Enabling {num_sessions} sessions...")
    for i in range(num_sessions):
        session_id = f"session-{i}"
        enabled = await memory_service.enable_for_session(
            session_id,
            user_id="test-user",
            project_root=f"/project/{i}",  # Provide project root
        )
        if not enabled:
            print(f"  WARNING: Failed to enable session {session_id}")
        # Mark sessions as complete (queues for analysis)
        # With queue size=2, only first 2 will be queued, rest will be dropped
        result = await memory_service.mark_session_complete(session_id)
        if not result:
            print(f"  WARNING: Failed to queue session {session_id} (queue full?)")

    print(f"After enabling and marking complete:")
    print(f"  Session count: {memory_service.get_active_session_count()}")
    print(f"  Analysis queue size: {memory_service.get_analysis_queue_size()}")
    print()

    # Simulate analysis worker processing only 2 sessions (queue size)
    print("Simulating analysis worker processing 2 sessions...")
    for _ in range(2):
        session_id = await memory_service.get_pending_analysis_session()
        if session_id:
            # Simulate analysis completion
            await memory_service.complete_analysis(session_id)
            print(f"  Completed analysis for: {session_id}")

    print()
    print(f"After processing 2 sessions:")
    print(f"  Session count: {memory_service.get_active_session_count()}")
    print(f"  Analysis queue size: {memory_service.get_analysis_queue_size()}")
    print()

    # Now simulate analysis worker crash/failure - remaining sessions stay in _session_states
    print("PROBLEM: Analysis worker crashes/fails")
    print("   Remaining sessions are still in _session_states but analysis never completes!")
    print()
    print(f"  Session count: {memory_service.get_active_session_count()}")
    print(f"  Analysis queue size: {memory_service.get_analysis_queue_size()}")
    print()

    # Continue adding more sessions - they all accumulate
    print("Adding 10 more sessions...")
    for i in range(10, 20):
        session_id = f"session-{i}"
        await memory_service.enable_for_session(
            session_id,
            user_id="test-user",
        )
        await memory_service.mark_session_complete(session_id)

    print()
    print(f"After adding 10 more sessions:")
    print(f"  Session count: {memory_service.get_active_session_count()}")
    print(f"  Analysis queue size: {memory_service.get_analysis_queue_size()}")
    print()

    print("=" * 80)
    print("TESTING FIX: Sessions that fail to queue should be cleaned up")
    print("=" * 80)
    print()
    print(f"Final session count: {memory_service.get_active_session_count()}")
    expected_count = 2  # Only sessions that were successfully queued should remain
    actual_count = memory_service.get_active_session_count()
    if actual_count <= expected_count:
        print(f"[FIXED] Session count ({actual_count}) is bounded")
    else:
        print(f"[LEAK] Session count ({actual_count}) exceeds expected ({expected_count})")
    print()


if __name__ == "__main__":
    asyncio.run(main())
