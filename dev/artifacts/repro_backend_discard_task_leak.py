"""Repro script for BackendLifecycleManager.discard() task leak.

This script demonstrates that when backends are discarded, shutdown tasks
are created but never awaited or tracked, causing task accumulation.
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.core.services.backend_lifecycle_manager import BackendLifecycleManager


class MockBackend:
    """Mock backend for testing."""
    
    def __init__(self, backend_type: str):
        self.backend_type = backend_type
        self.shutdown_called = False
    
    async def shutdown(self):
        """Simulate slow shutdown."""
        await asyncio.sleep(0.1)  # Simulate cleanup work
        self.shutdown_called = True


async def test_discard_task_leak():
    """Test that discard() creates untracked tasks."""
    print("Creating BackendLifecycleManager...")
    manager = BackendLifecycleManager()
    
    # Add some mock backends
    backend1 = MockBackend("test-backend-1")
    backend2 = MockBackend("test-backend-2")
    backend3 = MockBackend("test-backend-3")
    
    manager._backends["test-backend-1"] = backend1
    manager._backends["test-backend-2"] = backend2
    manager._per_session_backends["test-backend-3:session-1"] = backend3
    
    print(f"Added 3 backends to cache")
    print(f"Global backends: {len(manager._backends)}")
    print(f"Per-session backends: {len(manager._per_session_backends)}")
    
    # Count tasks before discard
    loop = asyncio.get_running_loop()
    tasks_before = [t for t in asyncio.all_tasks(loop) if not t.done()]
    print(f"\nTasks before discard: {len(tasks_before)}")
    
    # Discard backends (creates fire-and-forget tasks)
    print("\nDiscarding backends...")
    manager.discard("test-backend-1", None, "test")
    manager.discard("test-backend-2", None, "test")
    manager.discard("test-backend-3", "session-1", "test")
    
    # Count tasks after discard
    tasks_after = [t for t in asyncio.all_tasks(loop) if not t.done()]
    print(f"Tasks after discard: {len(tasks_after)}")
    print(f"New tasks created: {len(tasks_after) - len(tasks_before)}")
    
    # Wait a bit for tasks to complete
    await asyncio.sleep(0.2)
    
    # Check if tasks completed
    tasks_final = [t for t in asyncio.all_tasks(loop) if not t.done()]
    print(f"\nTasks after 0.2s wait: {len(tasks_final)}")
    
    # Verify backends were shut down
    print(f"\nBackend shutdown status:")
    print(f"  backend1.shutdown_called: {backend1.shutdown_called}")
    print(f"  backend2.shutdown_called: {backend2.shutdown_called}")
    print(f"  backend3.shutdown_called: {backend3.shutdown_called}")
    
    # Simulate many discards (attack scenario)
    print("\n" + "="*60)
    print("Simulating attack: Many rapid discards...")
    print("="*60)
    
    # Create many backends
    for i in range(100):
        backend = MockBackend(f"attack-backend-{i}")
        manager._backends[f"attack-backend-{i}"] = backend
    
    tasks_before_attack = [t for t in asyncio.all_tasks(loop) if not t.done()]
    print(f"Tasks before attack: {len(tasks_before_attack)}")
    
    # Rapidly discard all backends
    for i in range(100):
        manager.discard(f"attack-backend-{i}", None, "attack")
    
    tasks_after_attack = [t for t in asyncio.all_tasks(loop) if not t.done()]
    print(f"Tasks after attack: {len(tasks_after_attack)}")
    print(f"New tasks created: {len(tasks_after_attack) - len(tasks_before_attack)}")
    
    # Wait for tasks to complete
    await asyncio.sleep(0.5)
    
    tasks_final_attack = [t for t in asyncio.all_tasks(loop) if not t.done()]
    print(f"Tasks after 0.5s wait: {len(tasks_final_attack)}")
    print(f"Tasks still pending: {len(tasks_final_attack) - len(tasks_before_attack)}")
    
    # Test the fix: call await_pending_shutdown_tasks()
    print("\nTesting fix: calling await_pending_shutdown_tasks()...")
    await manager.await_pending_shutdown_tasks(timeout=5.0)
    
    # Check if tasks are tracked
    tracked_tasks = len(manager._shutdown_tasks)
    print(f"Tracked shutdown tasks after await: {tracked_tasks}")
    
    if len(tasks_final_attack) > len(tasks_before_attack):
        print("\nWARNING: Tasks still accumulating (but should be tracked now)")
        return False
    else:
        print("\nSUCCESS: Tasks completed and are now properly tracked")
        if tracked_tasks == 0:
            print("All shutdown tasks were properly awaited and cleaned up")
        return True


if __name__ == "__main__":
    result = asyncio.run(test_discard_task_leak())
    sys.exit(0 if result else 1)

