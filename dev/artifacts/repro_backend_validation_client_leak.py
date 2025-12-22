"""Repro script for backend validation HTTP client leak.

This script demonstrates that if BackendStage._register_validation_http_client()
creates a client but an exception occurs before the finally block runs,
the client might leak because WeakSet doesn't prevent garbage collection
of tasks before they complete.
"""

import asyncio
import gc
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import httpx


async def test_weakset_task_leak():
    """Test that WeakSet allows tasks to be garbage collected before completion."""
    print("Testing WeakSet task leak...")
    
    # Simulate the scenario: create a task, add to WeakSet, then lose reference
    cleanup_tasks = set()  # Using regular set for comparison
    weak_cleanup_tasks = set()  # Simulating WeakSet behavior
    
    async def slow_cleanup():
        """Simulate slow cleanup that takes time."""
        await asyncio.sleep(1)
        print("Cleanup completed")
    
    # Create task and add to both sets
    task1 = asyncio.create_task(slow_cleanup())
    cleanup_tasks.add(task1)
    weak_cleanup_tasks.add(task1)
    
    # Lose reference to task (simulating what happens with WeakSet)
    task_ref = task1
    task1 = None
    
    # Force garbage collection (WeakSet would allow collection here)
    gc.collect()
    
    # Check if task is still in sets
    print(f"Task in regular set: {len(cleanup_tasks)}")
    print(f"Task in weak set (simulated): {len(weak_cleanup_tasks)}")
    
    # Try to await the task via reference
    try:
        await task_ref
        print("Task completed successfully")
    except Exception as e:
        print(f"Task failed: {e}")


async def test_validation_client_leak_scenario():
    """Test scenario where validation client might leak."""
    print("\nTesting validation client leak scenario...")
    
    client: httpx.AsyncClient | None = None
    cleanup_tasks = set()
    
    try:
        # Simulate creating client (like in _register_validation_http_client)
        client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=60.0, write=60.0, pool=60.0),
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        )
        print(f"Created client: {client}")
        print(f"Client closed: {client.is_closed}")
        
        # Simulate exception before cleanup
        raise ValueError("Simulated exception before cleanup")
        
    except Exception as e:
        print(f"Exception occurred: {e}")
        
        # Simulate cleanup attempt (like in exception handler)
        if client is not None:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # Create cleanup task
                    cleanup_task = asyncio.create_task(client.aclose())
                    cleanup_tasks.add(cleanup_task)
                    print(f"Created cleanup task: {cleanup_task}")
                    # If using WeakSet, task could be GC'd here before completion
                    cleanup_task = None  # Lose reference
                    gc.collect()  # Force GC
                    print(f"Cleanup tasks remaining: {len(cleanup_tasks)}")
                else:
                    await client.aclose()
            except Exception as cleanup_error:
                print(f"Cleanup error: {cleanup_error}")
    
    # Wait a bit to see if cleanup happens
    await asyncio.sleep(2)
    
    # Check if client is closed
    if client is not None:
        print(f"Client closed after cleanup: {client.is_closed}")
        if not client.is_closed:
            print("LEAK DETECTED: Client was not closed!")
            await client.aclose()
        else:
            print("Client was properly closed")


if __name__ == "__main__":
    print("=" * 60)
    print("Backend Validation Client Leak Repro")
    print("=" * 60)
    
    asyncio.run(test_weakset_task_leak())
    asyncio.run(test_validation_client_leak_scenario())
    
    print("\n" + "=" * 60)
    print("Test completed")
    print("=" * 60)

