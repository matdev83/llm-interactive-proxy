"""Repro script for ServiceCollection cleanup tasks leak.

This script demonstrates that if ServiceCollection.add_instance() creates cleanup
tasks but ServiceCollection is destroyed before tasks complete, tasks may leak
because there's no dispose() method to await them.

Attack vector: A remote actor could repeatedly trigger backend reconfiguration
that replaces httpx.AsyncClient instances, creating many cleanup tasks. If the
ServiceCollection is destroyed (e.g., during app restart or stage failure), tasks
may not be properly awaited, leading to resource leaks.
"""

import asyncio
import gc
import sys
import time
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import httpx
from src.core.di.container import ServiceCollection


async def test_cleanup_tasks_leak_scenario():
    """Test scenario where cleanup tasks might leak."""
    print("=" * 60)
    print("Testing ServiceCollection cleanup tasks leak scenario...")
    print("=" * 60)
    
    # Track tasks created outside ServiceCollection to verify they're still running
    tracked_tasks: list[asyncio.Task[None]] = []
    clients_created: list[httpx.AsyncClient] = []
    
    try:
        # Simulate scenario: repeatedly replacing httpx.AsyncClient instances
        # This could happen during backend reconfiguration or app restart
        for i in range(5):
            print(f"\n--- Iteration {i+1} ---")
            services = ServiceCollection()
            
            # Create first client
            client1 = httpx.AsyncClient(
                timeout=httpx.Timeout(connect=10.0, read=60.0, write=60.0, pool=60.0),
                limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
            )
            clients_created.append(client1)
            print(f"Created client1: {client1}, closed: {client1.is_closed}")
            
            # Add first client
            services.add_instance(httpx.AsyncClient, client1)
            
            # Create second client (replacing first)
            client2 = httpx.AsyncClient(
                timeout=httpx.Timeout(connect=10.0, read=60.0, write=60.0, pool=60.0),
                limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
            )
            clients_created.append(client2)
            print(f"Created client2: {client2}, closed: {client2.is_closed}")
            
            # Replace first client with second - this should create a cleanup task
            services.add_instance(httpx.AsyncClient, client2)
            
            # Check cleanup tasks
            cleanup_tasks = list(services._cleanup_tasks)
            print(f"Cleanup tasks in set: {len(cleanup_tasks)}")
            if cleanup_tasks:
                for task in cleanup_tasks:
                    print(f"  Task: {task}, done: {task.done()}")
                    tracked_tasks.append(task)
            
            # Simulate ServiceCollection being destroyed before tasks complete
            # (e.g., during app restart or stage failure)
            print("Simulating ServiceCollection destruction...")
            # Test: Call dispose() to await cleanup tasks (this is the fix)
            await services.dispose()
            # Now ServiceCollection can be safely destroyed
            del services
            
            # Force garbage collection to see if WeakSet allows GC of tasks
            gc.collect()
            await asyncio.sleep(0.1)  # Small delay
            
            # Check if tasks are still running
            running_tasks = [t for t in tracked_tasks if not t.done()]
            print(f"Tasks still running after GC: {len(running_tasks)}")
            
            # Small delay to allow some tasks to complete
            await asyncio.sleep(0.2)
        
        print("\n" + "=" * 60)
        print("Final state check...")
        print("=" * 60)
        
        # Check final state of all tracked tasks
        final_running = [t for t in tracked_tasks if not t.done()]
        final_done = [t for t in tracked_tasks if t.done()]
        
        print(f"Total tasks created: {len(tracked_tasks)}")
        print(f"Tasks completed: {len(final_done)}")
        print(f"Tasks still running: {len(final_running)}")
        
        # Check if clients are closed
        closed_clients = [c for c in clients_created if c.is_closed]
        open_clients = [c for c in clients_created if not c.is_closed]
        
        print(f"\nTotal clients created: {len(clients_created)}")
        print(f"Clients closed: {len(closed_clients)}")
        print(f"Clients still open: {len(open_clients)}")
        
        if final_running:
            print("\n[LEAK DETECTED] Some cleanup tasks are still running!")
            print("   This indicates tasks were not properly awaited before ServiceCollection destruction")
            for task in final_running:
                print(f"   - Task: {task}, done: {task.done()}")
        
        if open_clients:
            print("\n[LEAK DETECTED] Some clients are still open!")
            print("   This indicates cleanup tasks did not complete")
            for client in open_clients:
                print(f"   - Client: {client}, closed: {client.is_closed}")
        
        # Clean up any remaining tasks and clients
        print("\nCleaning up...")
        for task in final_running:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        
        for client in open_clients:
            if not client.is_closed:
                try:
                    await client.aclose()
                except Exception:
                    pass
        
        # Note: open_clients includes the final client which is expected to be open
        # The real issue is if cleanup tasks for replaced clients don't complete
        if final_running:
            print("\n[LEAK CONFIRMED] Tasks leaked - Fix needed!")
            return False
        else:
            print("\n[OK] All cleanup tasks completed")
            # Note: Some clients are expected to be open (the final ones)
            return True
        
        return True
        
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_attack_scenario():
    """Test attack scenario: rapid client replacement."""
    print("\n" + "=" * 60)
    print("Testing attack scenario: rapid client replacement...")
    print("=" * 60)
    
    # Simulate an attacker rapidly triggering backend reconfiguration
    services = ServiceCollection()
    clients = []
    
    try:
        for i in range(20):
            new_client = httpx.AsyncClient(
                timeout=httpx.Timeout(10.0),
                limits=httpx.Limits(max_connections=10),
            )
            clients.append(new_client)
            services.add_instance(httpx.AsyncClient, new_client)
            
            # Don't wait for cleanup tasks to complete
            if i > 0:
                cleanup_tasks = list(services._cleanup_tasks)
                if cleanup_tasks:
                    print(f"Iteration {i}: {len(cleanup_tasks)} cleanup tasks pending")
        
        # Simulate ServiceCollection being destroyed (e.g., app restart)
        print("\nSimulating ServiceCollection destruction...")
        cleanup_tasks_before = list(services._cleanup_tasks)
        print(f"Cleanup tasks before destruction: {len(cleanup_tasks_before)}")
        
        # Test: Call dispose() to await cleanup tasks (this is the fix)
        await services.dispose()
        print(f"Cleanup tasks after dispose(): {len(services._cleanup_tasks)}")
        
        del services
        gc.collect()
        
        # Wait a bit
        await asyncio.sleep(0.5)
        
        # Check if tasks completed
        running_after = [t for t in cleanup_tasks_before if not t.done()]
        print(f"Tasks still running after destruction: {len(running_after)}")
        
        if running_after:
            print("[LEAK DETECTED] Tasks leaked after ServiceCollection destruction")
            for task in running_after:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            return False
        
        # Clean up final client
        final_client = clients[-1] if clients else None
        if final_client and not final_client.is_closed:
            await final_client.aclose()
        
        print("[OK] No leak detected")
        return True
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    print("=" * 60)
    print("ServiceCollection Cleanup Tasks Leak Repro")
    print("=" * 60)
    
    result1 = asyncio.run(test_cleanup_tasks_leak_scenario())
    result2 = asyncio.run(test_attack_scenario())
    
    print("\n" + "=" * 60)
    if result1 and result2:
        print("All tests passed - no leak detected")
    else:
        print("LEAK CONFIRMED - Fix needed!")
    print("=" * 60)

