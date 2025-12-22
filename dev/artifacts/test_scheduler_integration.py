#!/usr/bin/env python3
"""Test to verify cleanup scheduler integration in core services."""

import asyncio
import os
import sys

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from src.core.domain.connection_activity import ConnectionActivity, ConnectionType
from src.core.services.connection_activity_tracker import get_activity_tracker, reset_activity_tracker


async def test_scheduler_lifecycle_integration():
    """Test that scheduler can be started and stopped correctly."""
    print("Testing scheduler lifecycle integration...")
    
    # Get the global tracker (as would be used in real app)
    tracker = get_activity_tracker()
    
    # Import and create scheduler as would be done in dependency injection
    from src.core.services.connection_tracker_cleanup_scheduler import (
        ConnectionTrackerCleanupScheduler,
    )
    
    scheduler = ConnectionTrackerCleanupScheduler(
        activity_tracker=tracker,
        cleanup_interval_seconds=5,
    )
    
    print(f"Created scheduler: {not scheduler.is_running}")
    
    # Test start
    await scheduler.start()
    print(f"Scheduler started: {scheduler.is_running}")
    
    # Create some abandoned connections
    for i in range(5):
        session_id = f"test-conn-{i}"
        key = ("test", session_id)
        activity = ConnectionActivity(
            session_id=session_id,
            backend_name="test",
            connection_type=ConnectionType.NON_STREAMING,
        )
        activity.started_at = 0  # Very old
        with tracker._lock:
            tracker._connections[key] = activity
    
    print(f"Created abandoned connections: {tracker.get_connection_count()}")
    
    # Wait for cleanup
    await asyncio.sleep(6)  # Longer than cleanup interval
    
    # Verify cleanup happened
    remaining = tracker.get_connection_count()
    print(f"After cleanup: {remaining} connections remaining")
    
    # Test stop
    await scheduler.stop()
    print(f"Scheduler stopped: {not scheduler.is_running}")
    
    # Clean up tracker state
    reset_activity_tracker()
    
    if remaining == 0:
        print("Integration test PASSED")
        return True
    else:
        print("Integration test FAILED")
        return False


async def main():
    print("Connection Tracker Cleanup Scheduler Integration Test")
    print("=" * 60)
    
    success = await test_scheduler_lifecycle_integration()
    
    print("\n" + "=" * 60)
    if success:
        print("INTEGRATION TEST PASSED")
        print("Memory leak fix is working correctly!")
        sys.exit(0)
    else:
        print("INTEGRATION TEST FAILED")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())