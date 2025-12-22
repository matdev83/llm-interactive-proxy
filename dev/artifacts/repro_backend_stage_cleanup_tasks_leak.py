"""Repro script for BackendStage validation HTTP client cleanup tasks leak.

This script demonstrates that BackendStage creates cleanup tasks for HTTP clients
in exception handlers, but these tasks may not be awaited if the stage fails early,
causing async task accumulation.

Attack vector: A remote actor can trigger backend validation failures repeatedly,
causing cleanup tasks to accumulate without being awaited, preventing garbage
collection of HTTP client resources.
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))


async def test_cleanup_tasks_leak_scenario():
    """Test scenario where BackendStage cleanup tasks leak."""
    print("=" * 60)
    print("Testing BackendStage cleanup tasks leak scenario...")
    print("=" * 60)
    
    try:
        import httpx
        from src.core.app.stages.backend import BackendStage
        from src.core.di.container import ServiceCollection
        
        # Count tasks before
        tasks_before = len(asyncio.all_tasks())
        print(f"Active tasks before: {tasks_before}")
        
        # Create BackendStage instance
        print("\nCreating BackendStage instance...")
        stage = BackendStage()
        
        # Create services collection
        services = ServiceCollection()
        
        # Simulate creating HTTP client that will need cleanup
        print("Creating HTTP client for validation...")
        client = httpx.AsyncClient(
            http2=False,
            timeout=httpx.Timeout(connect=10.0, read=60.0, write=60.0, pool=60.0),
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
            trust_env=False,
        )
        
        # Simulate the exception path in _register_validation_http_client
        # where cleanup task is created but may not be awaited
        print("\nSimulating exception during client registration...")
        try:
            # This simulates the code path where client is created but exception occurs
            # before it's registered, triggering cleanup task creation
            loop = asyncio.get_running_loop()
            if loop.is_running():
                # Schedule cleanup task (this is what happens in the exception handler)
                cleanup_task = asyncio.create_task(client.aclose())
                stage._cleanup_tasks.add(cleanup_task)
                print(f"Created cleanup task: {cleanup_task}")
                
                # Simulate stage failure before cleanup tasks are awaited
                # This is the bug - tasks are created but not awaited
                print("Simulating stage failure (cleanup tasks not awaited)...")
                
                # Check if cleanup task is still pending
                await asyncio.sleep(0.1)
                
                tasks_after = len(asyncio.all_tasks())
                print(f"Active tasks after: {tasks_after}")
                
                # Check cleanup tasks set
                pending_tasks = [t for t in stage._cleanup_tasks if not t.done()]
                print(f"Pending cleanup tasks: {len(pending_tasks)}")
                
                if len(pending_tasks) > 0:
                    print(f"\n[LEAK DETECTED] {len(pending_tasks)} cleanup tasks not awaited!")
                    print("This indicates task leak because cleanup tasks were created")
                    print("but not awaited during stage failure")
                    
                    # Clean up for test
                    print("\nCleaning up leaked tasks...")
                    await stage._cleanup_validation_client()
                    
                    # Verify cleanup
                    remaining_tasks = [t for t in stage._cleanup_tasks if not t.done()]
                    if len(remaining_tasks) == 0:
                        print("Tasks cleaned up successfully")
                    else:
                        print(f"WARNING: {len(remaining_tasks)} tasks still pending")
                    
                    # Close client if still open
                    if not client.is_closed:
                        await client.aclose()
                    
                    return False  # Leak confirmed
                else:
                    print("All tasks completed (unexpected)")
                    if not client.is_closed:
                        await client.aclose()
                    return True
        except Exception as e:
            print(f"Exception during test: {e}")
            # Ensure client is closed
            if not client.is_closed:
                await client.aclose()
            raise
            
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_multiple_failures_leak():
    """Test that multiple stage failures create multiple cleanup tasks that leak."""
    print("\n" + "=" * 60)
    print("Testing multiple BackendStage failures cleanup tasks leak...")
    print("=" * 60)
    
    try:
        import httpx
        from src.core.app.stages.backend import BackendStage
        
        tasks_before = len(asyncio.all_tasks())
        print(f"Active tasks before: {tasks_before}")
        
        stage = BackendStage()
        
        # Simulate multiple failures
        print("\nSimulating 3 stage failures...")
        for i in range(3):
            client = httpx.AsyncClient(
                http2=False,
                timeout=httpx.Timeout(connect=10.0, read=60.0, write=60.0, pool=60.0),
                limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
                trust_env=False,
            )
            
            # Create cleanup task
            loop = asyncio.get_running_loop()
            if loop.is_running():
                cleanup_task = asyncio.create_task(client.aclose())
                stage._cleanup_tasks.add(cleanup_task)
                print(f"  Created cleanup task {i+1}: {cleanup_task}")
            
            await asyncio.sleep(0.1)
        
        # Simulate shutdown without awaiting cleanup tasks
        print("\nSimulating shutdown without awaiting cleanup tasks...")
        await asyncio.sleep(0.2)
        
        pending_tasks = [t for t in stage._cleanup_tasks if not t.done()]
        print(f"Pending cleanup tasks: {len(pending_tasks)}")
        
        if len(pending_tasks) > 0:
            print(f"\n[LEAK DETECTED] {len(pending_tasks)} cleanup tasks not awaited!")
            print("This indicates task leak because cleanup tasks accumulate")
            print("without being awaited during shutdown")
            
            # Clean up
            print("\nCleaning up leaked tasks...")
            await stage._cleanup_validation_client()
            
            remaining_tasks = [t for t in stage._cleanup_tasks if not t.done()]
            if len(remaining_tasks) == 0:
                print("Tasks cleaned up successfully")
            else:
                print(f"WARNING: {len(remaining_tasks)} tasks still pending")
            
            return False  # Leak confirmed
        else:
            print("All tasks completed (unexpected)")
            return True
            
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    print("=" * 60)
    print("BackendStage Cleanup Tasks Leak Repro")
    print("=" * 60)
    
    result1 = asyncio.run(test_cleanup_tasks_leak_scenario())
    result2 = asyncio.run(test_multiple_failures_leak())
    
    print("\n" + "=" * 60)
    if result1 and result2:
        print("All tests passed (no leak detected)")
    else:
        print("[LEAK CONFIRMED] Fix needed!")
    print("=" * 60)

