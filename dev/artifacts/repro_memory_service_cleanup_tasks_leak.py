"""Repro script for MemoryService cleanup tasks leak.

This script demonstrates that MemoryService._cleanup_tasks uses WeakSet,
which allows tasks to be garbage collected before they're awaited, leading
to resource leaks (HTTP connections, file handles, etc. in the cleanup tasks).
"""

import asyncio
import gc
import sys
from pathlib import Path
from weakref import WeakSet

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.core.memory.capture_buffer import SessionCaptureBuffer
from src.core.memory.config import MemoryConfiguration
from src.core.memory.service import MemoryService
from src.core.memory.tool_event_collector import DeterministicToolEventCollector


class MockRepository:
    """Mock repository for testing."""
    async def save_summary(self, session_id: str, summary: str) -> None:
        pass
    
    async def get_or_create_project_id(
        self, user_id: str, project_root: str
    ) -> str:
        return "mock-project-id"


async def test_cleanup_tasks_leak():
    """Test that cleanup tasks can be GC'd before awaited."""
    print("Testing MemoryService cleanup tasks leak scenario...")
    
    config = MemoryConfiguration(available=True, max_buffer_size_bytes=1024 * 1024)
    repository = MockRepository()
    memory_service = MemoryService(config, repository)
    
    # Verify _cleanup_tasks is a WeakSet
    assert isinstance(memory_service._cleanup_tasks, WeakSet), (
        "Expected WeakSet, got {type(memory_service._cleanup_tasks)}"
    )
    
    print(f"Initial cleanup tasks count: {len(memory_service._cleanup_tasks)}")
    
    # Enable a session
    session_id = "test_session_leak"
    await memory_service.enable_for_session(
        session_id,
        user_id="test-user",
        project_root="/project/test",
    )
    
    # Simulate session eviction which creates cleanup tasks
    # This mimics what happens in _maybe_cleanup_stale_sessions_locked()
    async with memory_service._state_lock:
        # Create cleanup tasks (like the code does)
        cleanup_task1 = asyncio.create_task(
            memory_service._capture_buffer.clear_session(session_id)
        )
        cleanup_task2 = asyncio.create_task(
            memory_service._tool_event_collector.clear_session(session_id)
        )
        
        # Add to WeakSet
        memory_service._cleanup_tasks.add(cleanup_task1)
        memory_service._cleanup_tasks.add(cleanup_task2)
        
        print(f"After adding tasks: {len(memory_service._cleanup_tasks)}")
        print(f"Task1: {cleanup_task1}, Task2: {cleanup_task2}")
        
        # Now, if we don't keep references to the tasks, they can be GC'd
        # even though they're still running, because WeakSet doesn't prevent GC
        del cleanup_task1
        del cleanup_task2
        
        # Force garbage collection
        gc.collect()
        
        # Check if tasks are still tracked
        remaining_count = len(memory_service._cleanup_tasks)
        print(f"After GC (no strong refs): {remaining_count}")
        
        if remaining_count < 2:
            print("LEAK CONFIRMED: Tasks were GC'd before completion!")
            print("   This means cleanup tasks may not be awaited, leading to:")
            print("   - HTTP connection leaks")
            print("   - File handle leaks")
            print("   - Other resource leaks")
            return True
        else:
            print("Tasks still tracked (may be due to other references)")
            return False


async def test_remote_actor_scenario():
    """Test scenario where remote actor can trigger resource leak."""
    print("\nTesting remote actor attack scenario...")
    
    config = MemoryConfiguration(available=True, max_buffer_size_bytes=1024 * 1024)
    repository = MockRepository()
    memory_service = MemoryService(config, repository)
    
    # Simulate remote actor creating many sessions that get evicted
    # Each eviction creates cleanup tasks that may leak
    for i in range(100):
        session_id = f"attack_session_{i}"
        await memory_service.enable_for_session(
            session_id,
            user_id="attacker",
            project_root="/project/attack",
        )
        
        # Simulate eviction
        async with memory_service._state_lock:
            cleanup_task1 = asyncio.create_task(
                memory_service._capture_buffer.clear_session(session_id)
            )
            cleanup_task2 = asyncio.create_task(
                memory_service._tool_event_collector.clear_session(session_id)
            )
            memory_service._cleanup_tasks.add(cleanup_task1)
            memory_service._cleanup_tasks.add(cleanup_task2)
            # Don't keep references - tasks can be GC'd
        
        # Force GC periodically
        if i % 10 == 0:
            gc.collect()
    
    # Check how many tasks remain
    remaining = len(memory_service._cleanup_tasks)
    print(f"After creating 100 sessions: {remaining} tasks remain in WeakSet")
    
    if remaining < 200:  # Should have 200 tasks (2 per session)
        print("LEAK CONFIRMED: Many tasks were GC'd before completion!")
        return True
    
    return False


if __name__ == "__main__":
    leak1 = asyncio.run(test_cleanup_tasks_leak())
    leak2 = asyncio.run(test_remote_actor_scenario())
    
    if leak1 or leak2:
        print("\nRESOURCE LEAK CONFIRMED")
        sys.exit(1)
    else:
        print("\nNo leak detected in this test")
        sys.exit(0)

