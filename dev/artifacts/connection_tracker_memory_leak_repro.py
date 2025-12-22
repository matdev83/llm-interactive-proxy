#!/usr/bin/env python3
"""Memory leak reproduction script for ConnectionActivityTracker.

This script simulates rapid connection creation/destruction cycles
to test if the global tracker accumulates memory over time.
"""

import gc
import os
import sys
import threading
import time
import tracemalloc
from typing import List

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from src.core.domain.connection_activity import ConnectionType
from src.core.services.connection_activity_tracker import get_activity_tracker, reset_activity_tracker


def simulate_connection_burst(num_connections: int = 1000) -> None:
    """Simulate a burst of connections being created and destroyed."""
    tracker = get_activity_tracker()
    
    # Create many connections quickly
    connections = []
    for i in range(num_connections):
        ctx = tracker.track_connection(
            session_id=f"test-session-{i}",
            backend_name="test-backend",
            connection_type=ConnectionType.STREAMING,
            model="test-model"
        )
        connections.append(ctx)
    
    # Increment some counters
    for i in range(num_connections):
        tracker.increment_rx(f"test-session-{i}", "test-backend", 100)
        tracker.increment_tx(f"test-session-{i}", "test-backend", 200)
    
    # Close all connections (proper cleanup)
    for ctx in connections:
        ctx.__enter__()
        # Simulate some work
        time.sleep(0.001)
        ctx.__exit__(None, None, None)


def simulate_abandoned_connections(num_connections: int = 500) -> None:
    """Simulate connections that are created but never properly closed."""
    # We need to bypass the context manager to create orphaned connections
    tracker = get_activity_tracker()
    
    # Directly manipulate the internal tracker to simulate abandoned connections
    for i in range(num_connections):
        # Access the internal dict directly to create orphaned entries
        key = ("test-backend", f"abandoned-session-{i}")
        
        # Simulate what happens when a context manager starts but never ends
        from src.core.domain.connection_activity import ConnectionActivity
        activity = ConnectionActivity(
            session_id=f"abandoned-session-{i}",
            backend_name="test-backend", 
            connection_type=ConnectionType.NON_STREAMING,
            model="test-model"
        )
        # Make it look like it started 10 minutes ago to ensure cleanup picks it up
        activity.started_at = time.time() - 600  # 10 minutes ago
        
        # Directly add to the internal dict (simulating abandoned connections)
        with tracker._lock:
            tracker._connections[key] = activity
        tracker.increment_rx(f"abandoned-session-{i}", "test-backend", 50)


def measure_memory_usage() -> tuple[int, int]:
    """Get current memory usage in bytes."""
    gc.collect()  # Force garbage collection
    snapshot = tracemalloc.take_snapshot()
    total = sum(stat.size for stat in snapshot.statistics('lineno'))
    count = len(snapshot.statistics('lineno'))
    return total, count


def test_memory_growth() -> None:
    """Test memory growth over multiple connection cycles."""
    print("Testing memory growth in ConnectionActivityTracker...")
    print("=" * 60)
    
    # Reset tracker to start clean
    reset_activity_tracker()
    
    # Start memory tracking
    tracemalloc.start()
    
    # Baseline measurement
    baseline_memory, baseline_count = measure_memory_usage()
    print(f"Baseline memory: {baseline_memory / 1024 / 1024:.2f} MB ({baseline_count} allocations)")
    
    # Test 1: Normal connection lifecycle
    print("\nTest 1: Normal connection lifecycle...")
    for cycle in range(5):
        simulate_connection_burst(1000)
        current_memory, current_count = measure_memory_usage()
        tracker = get_activity_tracker()
        connection_count = tracker.get_connection_count()
        
        print(f"  Cycle {cycle + 1}: {current_memory / 1024 / 1024:.2f} MB, "
              f"{current_count} allocations, {connection_count} active connections")
    
    # Check for orphaned connections
    tracker = get_activity_tracker()
    if tracker.get_connection_count() > 0:
        print(f"  WARNING: {tracker.get_connection_count()} orphaned connections found!")
    
    # Test 2: Abandoned connections (memory leak scenario)
    print("\nTest 2: Simulating abandoned connections...")
    simulate_abandoned_connections(500)
    
    leak_memory, leak_count = measure_memory_usage()
    tracker = get_activity_tracker()
    connection_count = tracker.get_connection_count()
    
    print(f"  After abandoned connections: {leak_memory / 1024 / 1024:.2f} MB, "
          f"{leak_count} allocations, {connection_count} active connections")
    
    # Test 3: Cleanup functionality
    print("\nTest 3: Testing cleanup functionality...")
    before_cleanup = tracker.get_connection_count()
    cleaned = tracker.cleanup_stale_connections()  # Clean with default timeout (5 minutes)
    after_cleanup = tracker.get_connection_count()
    
    print(f"  Connections before cleanup: {before_cleanup}")
    print(f"  Connections cleaned: {cleaned}")
    print(f"  Connections after cleanup: {after_cleanup}")
    
    # Final memory check
    final_memory, final_count = measure_memory_usage()
    memory_growth = final_memory - baseline_memory
    
    print(f"\nFinal Results:")
    print(f"  Memory growth: {memory_growth / 1024 / 1024:.2f} MB")
    print(f"  Remaining active connections: {tracker.get_connection_count()}")
    
    # Determine if memory leak is present
    if tracker.get_connection_count() > 0 and memory_growth > 1024 * 1024:  # 1MB
        print(f"\nMEMORY LEAK CONFIRMED:")
        print(f"   - Connections remain active: {tracker.get_connection_count()}")
        print(f"   - Memory growth: {memory_growth / 1024 / 1024:.2f} MB")
        print(f"   - Issue: Abandoned connections not cleaned up automatically")
        return True
    elif tracker.get_connection_count() > 0:
        print(f"\nPOTENTIAL LEAK:")
        print(f"   - Connections remain active: {tracker.get_connection_count()}")
        print(f"   - Memory growth minimal: {memory_growth / 1024 / 1024:.2f} MB")
        print(f"   - Issue: Connections accumulate but memory impact small")
        return True
    else:
        print(f"\nNO LEAK DETECTED:")
        print(f"   - All connections properly cleaned up")
        print(f"   - Memory growth minimal: {memory_growth / 1024 / 1024:.2f} MB")
        return False


if __name__ == "__main__":
    # Run test multiple times to ensure consistency
    leak_detected = False
    
    for run in range(3):
        print(f"\n{'='*60}")
        print(f"Memory Leak Test Run {run + 1}")
        print(f"{'='*60}")
        
        if test_memory_growth():
            leak_detected = True
        
        # Wait between runs
        time.sleep(2)
    
    print(f"\n{'='*60}")
    if leak_detected:
        print("MEMORY LEAK CONFIRMED - See details above")
        sys.exit(1)
    else:
        print("NO MEMORY LEAK DETECTED")
        sys.exit(0)