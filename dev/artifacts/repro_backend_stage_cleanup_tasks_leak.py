"""Repro script for BackendStage cleanup tasks leak.

This script demonstrates that if BackendStage._register_validation_http_client()
creates cleanup tasks but an exception occurs during cleanup or cleanup is interrupted,
tasks may not be properly awaited/cancelled, leading to resource leaks.
"""

import asyncio
import gc
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import httpx


async def test_cleanup_tasks_leak_scenario():
    """Test scenario where cleanup tasks might leak."""
    print("Testing BackendStage cleanup tasks leak scenario...")
    
    client: httpx.AsyncClient | None = None
    cleanup_tasks: set[asyncio.Task[None]] = set()
    
    try:
        # Simulate creating client (like in _register_validation_http_client)
        client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=60.0, write=60.0, pool=60.0),
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        )
        print(f"Created client: {client}")
        print(f"Client closed: {client.is_closed}")
        
        # Simulate exception before cleanup (like in exception handler)
        # This mimics the scenario where cleanup_task is added but cleanup fails
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Create cleanup task and add to set (like BackendStage does)
                cleanup_task = asyncio.create_task(client.aclose())
                cleanup_tasks.add(cleanup_task)
                print(f"Created cleanup task: {cleanup_task}")
                print(f"Cleanup tasks count: {len(cleanup_tasks)}")
                
                # Simulate exception during cleanup (like timeout or cancellation error)
                raise ValueError("Simulated exception during cleanup")
        except Exception as e:
            print(f"Exception during cleanup setup: {e}")
            # If cleanup fails here, tasks remain in set but may not be awaited
        
    except Exception as e:
        print(f"Exception occurred: {e}")
    
    # Simulate cleanup attempt (like in _cleanup_validation_client)
    # But simulate a scenario where cleanup is interrupted
    print("\nSimulating cleanup attempt...")
    pending_tasks = [t for t in cleanup_tasks if not t.done()]
    if pending_tasks:
        print(f"Pending cleanup tasks: {len(pending_tasks)}")
        try:
            # Simulate timeout scenario
            await asyncio.wait_for(
                asyncio.gather(*pending_tasks, return_exceptions=True),
                timeout=0.1,  # Very short timeout to trigger TimeoutError
            )
        except asyncio.TimeoutError:
            print("Timeout waiting for cleanup tasks (simulated leak scenario)")
            # In real code, tasks should be cancelled here, but if this fails...
            for task in pending_tasks:
                if not task.done():
                    print(f"Task {task} not done, should be cancelled")
                    # Simulate cancellation failure
                    # task.cancel()  # This should happen but might fail
    
    # Wait a bit to see if cleanup happens
    await asyncio.sleep(1)
    
    # Check if client is closed
    if client is not None:
        print(f"\nClient closed after cleanup: {client.is_closed}")
        if not client.is_closed:
            print("LEAK DETECTED: Client was not closed!")
            await client.aclose()
        else:
            print("Client was properly closed")
    
    # Check if tasks are still pending
    pending_after = [t for t in cleanup_tasks if not t.done()]
    if pending_after:
        print(f"LEAK DETECTED: {len(pending_after)} cleanup tasks still pending!")
        for task in pending_after:
            print(f"  - Task: {task}, done: {task.done()}")
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
    else:
        print("All cleanup tasks completed")


async def test_cleanup_interruption_scenario():
    """Test scenario where cleanup is interrupted by exception."""
    print("\n" + "=" * 60)
    print("Testing cleanup interruption scenario...")
    
    client: httpx.AsyncClient | None = None
    cleanup_tasks: set[asyncio.Task[None]] = set()
    
    try:
        client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=60.0, write=60.0, pool=60.0),
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        )
        
        # Add cleanup task
        loop = asyncio.get_event_loop()
        if loop.is_running():
            cleanup_task = asyncio.create_task(client.aclose())
            cleanup_tasks.add(cleanup_task)
            print(f"Created cleanup task: {cleanup_task}")
        
        # Simulate cleanup attempt that gets interrupted
        pending_tasks = [t for t in cleanup_tasks if not t.done()]
        if pending_tasks:
            try:
                # Simulate exception during gather
                async def failing_cleanup():
                    await asyncio.sleep(0.1)
                    raise RuntimeError("Cleanup failed")
                
                # Replace task with failing one for demonstration
                failing_task = asyncio.create_task(failing_cleanup())
                cleanup_tasks.add(failing_task)
                
                await asyncio.gather(*cleanup_tasks, return_exceptions=True)
            except Exception as e:
                print(f"Exception during cleanup: {e}")
                # If exception occurs, tasks might not be properly handled
    
    except Exception as e:
        print(f"Exception: {e}")
    finally:
        # Ensure cleanup
        if client and not client.is_closed:
            await client.aclose()
        
        # Cancel any remaining tasks
        for task in cleanup_tasks:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass


if __name__ == "__main__":
    print("=" * 60)
    print("BackendStage Cleanup Tasks Leak Repro")
    print("=" * 60)
    
    asyncio.run(test_cleanup_tasks_leak_scenario())
    asyncio.run(test_cleanup_interruption_scenario())
    
    print("\n" + "=" * 60)
    print("Test completed")
    print("=" * 60)

