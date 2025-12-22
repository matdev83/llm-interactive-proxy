"""Repro script for potential memory leak in AppLifecycle._background_tasks.

This script checks if _background_tasks can grow unbounded if cleanup
isn't called frequently enough or if tasks are added repeatedly.
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.core.app.lifecycle import AppLifecycle
from fastapi import FastAPI


async def test_task():
    """A test background task."""
    await asyncio.sleep(0.1)


async def main():
    """Check if _background_tasks can grow unbounded."""
    print("Creating AppLifecycle...")
    app = FastAPI()
    config = {"session_cleanup_enabled": True}
    lifecycle = AppLifecycle(app, config)
    
    print(f"Initial _background_tasks size: {len(lifecycle._background_tasks)}")
    
    # Simulate adding many tasks (if _start_background_tasks is called multiple times)
    print("\nSimulating multiple calls to _start_background_tasks...")
    
    # Note: In real code, _start_background_tasks is only called once during startup,
    # but if there's a bug or if it's called multiple times, tasks could accumulate
    for i in range(10):
        task = asyncio.create_task(test_task(), name=f"test_task_{i}")
        lifecycle._background_tasks.append(task)
        task.add_done_callback(lifecycle._remove_completed_task)
    
    print(f"After adding tasks: _background_tasks size: {len(lifecycle._background_tasks)}")
    
    # Wait for tasks to complete
    await asyncio.sleep(0.5)
    
    print(f"After tasks complete: _background_tasks size: {len(lifecycle._background_tasks)}")
    print("Expected: Should be cleaned up by callbacks")
    
    # Check if cleanup works
    lifecycle._cleanup_completed_tasks()
    print(f"After manual cleanup: _background_tasks size: {len(lifecycle._background_tasks)}")
    
    # Test scenario: What if cleanup is never called?
    print("\nTesting scenario where cleanup is never called...")
    lifecycle2 = AppLifecycle(app, {"session_cleanup_enabled": False})
    
    for i in range(100):
        task = asyncio.create_task(test_task(), name=f"test_task_{i}")
        lifecycle2._background_tasks.append(task)
        # Note: cleanup is only called if session_cleanup_enabled is True
    
    await asyncio.sleep(0.5)
    
    print(f"Without cleanup: _background_tasks size: {len(lifecycle2._background_tasks)}")
    print("Expected: Should still have completed tasks if cleanup not called")
    
    lifecycle2._cleanup_completed_tasks()
    print(f"After manual cleanup: _background_tasks size: {len(lifecycle2._background_tasks)}")
    
    print("\nPOTENTIAL ISSUE: If _start_background_tasks is called multiple times")
    print("or if cleanup isn't called, tasks could accumulate.")


if __name__ == "__main__":
    asyncio.run(main())
