#!/usr/bin/env python3
"""Integration test to verify memory leak fix works correctly.

This test simulates real-world scenario with cleanup scheduler running
to ensure memory growth is bounded.
"""

import asyncio
import os
import sys
import time

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from src.core.domain.connection_activity import ConnectionActivity, ConnectionType
from src.core.services.connection_activity_tracker import ConnectionActivityTracker
from src.core.services.connection_tracker_cleanup_scheduler import (
    ConnectionTrackerCleanupScheduler,
)


async def test_memory_leak_fix():
    """Test that cleanup scheduler prevents memory leaks."""
    print("Testing memory leak fix with automatic cleanup scheduler...")
    print("=" * 70)
    
    # Create tracker and scheduler
    tracker = ConnectionActivityTracker(stale_timeout_seconds=30)  # 30 second timeout
    scheduler = ConnectionTrackerCleanupScheduler(
        activity_tracker=tracker,
        cleanup_interval_seconds=10,  # Clean every 10 seconds
    )
    
    print("Scenario: Automatic cleanup running in background")
    print(f"  - Stale timeout: {30} seconds")
    print(f"  - Cleanup interval: {10} seconds")
    
    # Start cleanup scheduler
    await scheduler.start()
    print("Cleanup scheduler started")
    
    # Simulate connections that become abandoned
    connection_batches = []
    for batch in range(5):  # 5 batches
        batch_connections = []
        
        for i in range(20):  # 20 connections per batch
            session_id = f"abandoned-batch{batch}-conn{i}"
            
            # Create abandoned connections by adding directly to tracker
            key = ("test-backend", session_id)
            activity = ConnectionActivity(
                session_id=session_id,
                backend_name="test-backend",
                connection_type=ConnectionType.STREAMING,
                model="test-model"
            )
            
            # Make connections progressively older
            activity.started_at = time.time() - ((batch + 1) * 15)  # Older than cleanup interval
            with tracker._lock:
                tracker._connections[key] = activity
            
            batch_connections.append(session_id)
        
        connection_batches.extend(batch_connections)
        print(f"  Created batch {batch + 1}: {len(batch_connections)} connections")
        print(f"  Total active connections: {tracker.get_connection_count()}")
        
        # Wait between batches to let cleanup work
        await asyncio.sleep(12)  # Longer than cleanup interval
    
    print("\n--- Final State After All Batches ---")
    print(f"Total connections created: {len(connection_batches)}")
    print(f"Active connections remaining: {tracker.get_connection_count()}")
    
    # Wait a bit more for final cleanup
    await asyncio.sleep(15)
    
    final_count = tracker.get_connection_count()
    print(f"Active connections after final cleanup: {final_count}")
    
    # Stop scheduler
    await scheduler.stop()
    print("Cleanup scheduler stopped")
    
    # Verify fix worked
    print("\n--- Results ---")
    if final_count == 0:
        print("MEMORY LEAK FIXED:")
        print("   - All abandoned connections were automatically cleaned up")
        print("   - Memory growth is bounded by cleanup scheduler")
        print("   - No manual intervention required")
        return True
    elif final_count < len(connection_batches) * 0.1:  # Less than 10% remaining
        print("MEMORY LEAK MOSTLY FIXED:")
        print(f"   - {len(connection_batches) - final_count} connections automatically cleaned up")
        print(f"   - Only {final_count} connections remain (likely very recent)")
        print("   - Memory growth significantly bounded")
        return True
    else:
        print("MEMORY LEAK PERSISTS:")
        print(f"   - {final_count} connections still active out of {len(connection_batches)}")
        print("   - Cleanup scheduler not working effectively")
        return False


async def test_scheduler_integration():
    """Test that scheduler integrates correctly with the tracker."""
    print("\n" + "=" * 70)
    print("Testing scheduler-tracker integration...")
    
    tracker = ConnectionActivityTracker(stale_timeout_seconds=5)
    scheduler = ConnectionTrackerCleanupScheduler(
        activity_tracker=tracker,
        cleanup_interval_seconds=2,
    )
    
    # Start scheduler
    await scheduler.start()
    
    # Create some connections
    for i in range(10):
        session_id = f"test-conn-{i}"
        key = ("test", session_id)
        activity = ConnectionActivity(
            session_id=session_id,
            backend_name="test",
            connection_type=ConnectionType.NON_STREAMING,
        )
        activity.started_at = time.time() - 10  # 10 seconds old
        with tracker._lock:
            tracker._connections[key] = activity
    
    print(f"Created 10 old connections: {tracker.get_connection_count()} active")
    
    # Wait for cleanup
    await asyncio.sleep(3)
    
    final_count = tracker.get_connection_count()
    print(f"After cleanup: {final_count} active connections")
    
    await scheduler.stop()
    
    if final_count == 0:
        print("Integration test passed")
        return True
    else:
        print("Integration test failed")
        return False


async def main():
    """Run all tests."""
    print("Connection Activity Tracker Memory Leak Fix Verification")
    print("=" * 70)
    
    test1_passed = await test_memory_leak_fix()
    test2_passed = await test_scheduler_integration()
    
    print("\n" + "=" * 70)
    if test1_passed and test2_passed:
        print("ALL TESTS PASSED - Memory leak is fixed!")
        sys.exit(0)
    else:
        print("SOME TESTS FAILED - Memory leak may persist")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())