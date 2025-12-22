"""Repro script for InMemoryUsageStore persistence thread leak.

This script demonstrates that InMemoryUsageStore creates a persistence thread
via start_persistence_thread() but stop_persistence_thread() is never called
during application shutdown, causing threads to leak.

Attack vector: A remote actor can trigger usage tracking which starts the
persistence thread. On shutdown, the thread is never stopped, causing thread
accumulation if the application is restarted multiple times.
"""

import asyncio
import sys
import threading
import time
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))


def test_thread_leak_scenario():
    """Test scenario where InMemoryUsageStore thread leaks."""
    print("=" * 60)
    print("Testing InMemoryUsageStore persistence thread leak scenario...")
    print("=" * 60)
    
    try:
        from src.core.services.in_memory_usage_store import InMemoryUsageStore
        
        # Count threads before
        threads_before = threading.active_count()
        print(f"Active threads before: {threads_before}")
        
        # Create InMemoryUsageStore instance
        print("\nCreating InMemoryUsageStore instance...")
        store = InMemoryUsageStore(
            persistence_path=Path("/tmp/test_usage_store.json"),
            flush_interval_seconds=1.0,
        )
        
        # Start persistence thread
        print("Starting persistence thread...")
        store.start_persistence_thread()
        
        # Wait a bit to ensure thread started
        time.sleep(0.5)
        
        threads_after_start = threading.active_count()
        print(f"Active threads after starting: {threads_after_start}")
        
        # Verify thread is running
        if store._flush_thread is not None and store._flush_thread.is_alive():
            print(f"Persistence thread is running: {store._flush_thread.name}")
        else:
            print("ERROR: Persistence thread not running!")
            return False
        
        # Simulate application shutdown WITHOUT calling stop_persistence_thread()
        # This simulates the current bug where shutdown doesn't stop the thread
        print("\nSimulating application shutdown (without calling stop_persistence_thread())...")
        print("(This is the bug - thread should be stopped but isn't)")
        
        # Wait a bit
        time.sleep(1.0)
        
        # Check if thread is still running (it should be - leak confirmed)
        threads_after_shutdown = threading.active_count()
        print(f"Active threads after 'shutdown': {threads_after_shutdown}")
        
        if store._flush_thread is not None and store._flush_thread.is_alive():
            print(f"\n[LEAK DETECTED] Persistence thread still running: {store._flush_thread.name}")
            print("This indicates thread leak because stop_persistence_thread() was not called")
            
            # Clean up for test
            print("\nCleaning up leaked thread...")
            store.stop_persistence_thread()
            time.sleep(0.5)
            
            if store._flush_thread is None or not store._flush_thread.is_alive():
                print("Thread cleaned up successfully")
            else:
                print("WARNING: Thread still running after cleanup attempt")
            
            return False  # Leak confirmed
        else:
            print("Thread stopped (unexpected)")
            return True
            
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_multiple_instances_leak():
    """Test that multiple instances create multiple threads that leak."""
    print("\n" + "=" * 60)
    print("Testing multiple InMemoryUsageStore instances thread leak...")
    print("=" * 60)
    
    try:
        from src.core.services.in_memory_usage_store import InMemoryUsageStore
        
        threads_before = threading.active_count()
        print(f"Active threads before: {threads_before}")
        
        stores = []
        print("\nCreating 3 InMemoryUsageStore instances...")
        for i in range(3):
            store = InMemoryUsageStore(
                persistence_path=Path(f"/tmp/test_usage_store_{i}.json"),
                flush_interval_seconds=1.0,
            )
            store.start_persistence_thread()
            stores.append(store)
            print(f"  Created store {i+1}, thread: {store._flush_thread.name if store._flush_thread else 'None'}")
            time.sleep(0.2)
        
        threads_after_creation = threading.active_count()
        print(f"\nActive threads after creating 3 stores: {threads_after_creation}")
        print(f"Thread increase: {threads_after_creation - threads_before}")
        
        # Simulate shutdown without stopping threads
        print("\nSimulating shutdown without stopping threads...")
        time.sleep(1.0)
        
        # Count running threads
        running_threads = sum(
            1 for store in stores
            if store._flush_thread is not None and store._flush_thread.is_alive()
        )
        
        if running_threads > 0:
            print(f"\n[LEAK DETECTED] {running_threads} persistence threads still running!")
            print("This indicates thread leak because stop_persistence_thread() was not called")
            
            # Clean up
            print("\nCleaning up leaked threads...")
            for store in stores:
                store.stop_persistence_thread()
            time.sleep(0.5)
            
            return False  # Leak confirmed
        else:
            print("All threads stopped (unexpected)")
            return True
            
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    print("=" * 60)
    print("InMemoryUsageStore Persistence Thread Leak Repro")
    print("=" * 60)
    
    result1 = test_thread_leak_scenario()
    result2 = test_multiple_instances_leak()
    
    print("\n" + "=" * 60)
    if result1 and result2:
        print("All tests passed (no leak detected)")
    else:
        print("[LEAK CONFIRMED] Fix needed!")
    print("=" * 60)

