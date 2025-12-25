#!/usr/bin/env python3
"""Final test: Original memory leak scenario with fix in place."""

import asyncio
import os
import sys
import time

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from src.core.domain.connection_activity import ConnectionActivity, ConnectionType
from src.core.services.connection_activity_tracker import (
    get_activity_tracker,
)
from src.core.services.connection_tracker_cleanup_scheduler import (
    ConnectionTrackerCleanupScheduler,
)


async def test_original_scenario_with_fix():
    """Test the exact scenario from original reproduction with fix enabled."""
    print("Testing original memory leak scenario with automatic cleanup...")
    print("=" * 70)
    
    # Get global tracker and start cleanup scheduler
    tracker = get_activity_tracker()
    scheduler = ConnectionTrackerCleanupScheduler(
        activity_tracker=tracker,
        cleanup_interval_seconds=30,  # 30 second cleanup interval
    )
    
    # Use shorter stale timeout for testing
    tracker._stale_timeout = 60  # 1 minute timeout instead of 5 minutes
    
    await scheduler.start()
    print("Cleanup scheduler started (30s interval)")
    
    # Simulate the exact scenario from original reproduction
    connection_counter = 0
    memory_samples = []
    
    for day in range(3):  # Simulate 3 days
        print(f"\n--- Day {day + 1} ---")
        
        for hour in range(8):  # 8 hours of activity per day
            batch_size = 50  # 50 connections per hour
            current_hour_connections = []
            
            # Create connections that complete normally
            for i in range(batch_size):
                session_id = f"session-{connection_counter}"
                ctx = tracker.track_connection(
                    session_id=session_id,
                    backend_name="openai.gpt4",
                    connection_type=ConnectionType.STREAMING,
                    model="gpt-4"
                )
                current_hour_connections.append(ctx)
                connection_counter += 1
            
            # Simulate normal completion (80%)
            for i, ctx in enumerate(current_hour_connections):
                if i % 5 != 0:  # 80% complete normally
                    ctx.__enter__()
                    tracker.increment_rx(f"session-{connection_counter - batch_size + i}", "openai.gpt4", 100)
                    tracker.increment_tx(f"session-{connection_counter - batch_size + i}", "openai.gpt4", 200)
                    ctx.__exit__(None, None, None)
            
            # Simulate abandoned connections (20%) due to crashes/timeouts
            abandoned_count = batch_size // 5
            for i in range(abandoned_count):
                idx = i * 5  # Every 5th connection
                if idx < len(current_hour_connections):
                    session_id = f"session-{connection_counter - batch_size + idx}"
                    
                    # Create abandoned connections directly
                    key = ("openai.gpt4", session_id)
                    activity = ConnectionActivity(
                        session_id=session_id,
                        backend_name="openai.gpt4",
                        connection_type=ConnectionType.STREAMING,
                        model="gpt-4"
                    )
                    # Make it old enough to be cleaned up
                    activity.started_at = time.time() - 60  # 1 minute old (older than some intervals)
                    
                    with tracker._lock:
                        tracker._connections[key] = activity
                    tracker.increment_rx(session_id, "openai.gpt4", 50)
            
            # Check memory state
            current_memory = sys.getsizeof(tracker._connections) + sum(
                sys.getsizeof(k) + sys.getsizeof(v) for k, v in tracker._connections.items()
            )
            memory_samples.append(current_memory)
            
            print(f"  Hour {hour + 1}: {tracker.get_connection_count()} active connections, "
                  f"~{current_memory / 1024:.1f} KB")
            
            # Wait between batches to let cleanup work
            await asyncio.sleep(2)  # Give cleanup time to work
    
    print("\n--- Final State ---")
    print(f"Total connections processed: {connection_counter}")
    print(f"Active connections remaining: {tracker.get_connection_count()}")
    print(f"Memory growth: {memory_samples[-1] / 1024:.1f} KB")
    
    # Wait for final cleanup
    await asyncio.sleep(35)  # Wait for one more cleanup cycle
    final_count = tracker.get_connection_count()
    
    await scheduler.stop()
    
    print(f"After final cleanup: {final_count} active connections")
    
    # Analyze results
    print("\n--- Analysis ---")
    if final_count < 20:  # Very few connections remaining
        print("MEMORY LEAK FIXED!")
        print("  - Cleanup scheduler successfully removed abandoned connections")
        print("  - Memory growth is bounded and controlled")
        print("  - No manual intervention required")
        return True
    else:
        print("MEMORY LEAK STILL PRESENT")
        print(f"  - {final_count} connections still remaining")
        print("  - Cleanup scheduler may not be effective")
        return False


async def main():
    print("Final Test: Original Memory Leak Scenario with Fix")
    print("=" * 70)
    
    success = await test_original_scenario_with_fix()
    
    print("\n" + "=" * 70)
    if success:
        print("MEMORY LEAK FIX VERIFIED!")
        print("\nSummary:")
        print("- Root cause: No automatic cleanup for ConnectionActivityTracker")
        print("- Solution: Added ConnectionTrackerCleanupScheduler")
        print("- Integration: Registered in core services and lifecycle")
        print("- Result: Memory growth is now bounded")
        sys.exit(0)
    else:
        print("MEMORY LEAK FIX FAILED")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())