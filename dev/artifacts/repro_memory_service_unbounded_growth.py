"""Repro script to demonstrate memory leak in MemoryService.

Testing scenarios:
1. Sessions enabled but never marked complete - should be cleaned up after TTL
2. Sessions queued but analysis worker crashes - should be cleaned up after TTL
3. Sessions in _analysis_in_progress that never complete - should be cleaned up after TTL
"""

import asyncio
import sys
import time
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
    print("Memory Leak Repro: MemoryService Unbounded Growth")
    print("=" * 80)
    print()

    # Create memory service
    config = MemoryConfiguration(
        available=True,
        analysis_queue_maxsize=100,  # Large queue
        summarization_delay_seconds=0,  # Immediate analysis
        require_project_discovery=False,  # Allow sessions without project root
    )
    repository = MockMemoryRepository()
    memory_service = MemoryService(config, repository)

    print(f"Initial session count: {memory_service.get_active_session_count()}")
    print(f"Analysis queue size: {memory_service.get_analysis_queue_size()}")
    print()

    # Scenario 1: Enable many sessions but never mark them complete
    print("=" * 80)
    print("SCENARIO 1: Sessions enabled but never marked complete")
    print("=" * 80)
    num_sessions = 1000
    print(f"Enabling {num_sessions} sessions (without marking complete)...")
    for i in range(num_sessions):
        session_id = f"enabled-only-{i}"
        await memory_service.enable_for_session(
            session_id,
            user_id="test-user",
            project_root=f"/project/{i}",
        )

    print(f"After enabling {num_sessions} sessions:")
    print(f"  Session count: {memory_service.get_active_session_count()}")
    print(f"  Analysis queue size: {memory_service.get_analysis_queue_size()}")
    print()

    # Scenario 2: Queue sessions but simulate worker crash (never call complete_analysis)
    print("=" * 80)
    print("SCENARIO 2: Sessions queued but analysis worker crashes")
    print("=" * 80)
    num_queued = 50
    print(f"Queuing {num_queued} sessions for analysis...")
    for i in range(num_queued):
        session_id = f"queued-{i}"
        await memory_service.enable_for_session(
            session_id,
            user_id="test-user",
            project_root=f"/project/queued/{i}",
        )
        await memory_service.mark_session_complete(session_id)

    # Simulate worker starting to process but crashing
    print("Simulating worker crash (sessions in _analysis_in_progress)...")
    for i in range(10):
        session_id = await memory_service.get_pending_analysis_session()
        if session_id:
            # Add to _analysis_in_progress but never call complete_analysis
            # (simulating worker crash)
            print(f"  Worker crashed while processing: {session_id}")

    print(f"After queuing and simulating crash:")
    print(f"  Session count: {memory_service.get_active_session_count()}")
    print(f"  Analysis queue size: {memory_service.get_analysis_queue_size()}")
    print()

    # Scenario 3: Continue adding more sessions - they all accumulate
    print("=" * 80)
    print("SCENARIO 3: Adding more sessions (should be bounded)")
    print("=" * 80)
    print("Adding 100 more sessions...")
    for i in range(100):
        session_id = f"additional-{i}"
        await memory_service.enable_for_session(
            session_id,
            user_id="test-user",
        )
        await memory_service.mark_session_complete(session_id)

    print()
    print(f"After adding 100 more sessions:")
    print(f"  Session count: {memory_service.get_active_session_count()}")
    print(f"  Analysis queue size: {memory_service.get_analysis_queue_size()}")
    print()

    # Check if memory is bounded
    total_sessions = memory_service.get_active_session_count()
    print("=" * 80)
    print("MEMORY LEAK ANALYSIS")
    print("=" * 80)
    print(f"Total sessions in _session_states: {total_sessions}")
    print()
    
    # Expected: Should be bounded by some limit (e.g., TTL-based cleanup or max sessions)
    # If unbounded, this will grow indefinitely
    if total_sessions > 1000:
        print(f"[LEAK CONFIRMED] Session count ({total_sessions}) exceeds reasonable limit (1000)")
        print("  Sessions are accumulating without cleanup!")
        print("  Expected: Sessions should be cleaned up after TTL or max limit")
    else:
        print(f"[NO LEAK] Session count ({total_sessions}) is within reasonable bounds")
    
    print()


if __name__ == "__main__":
    asyncio.run(main())
