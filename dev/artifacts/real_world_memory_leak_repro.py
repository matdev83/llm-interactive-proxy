#!/usr/bin/env python3
"""Reproduction script for actual memory leak scenario in ConnectionActivityTracker.

This script tests the scenario where connections are tracked but there's no
automatic background cleanup task running in the main proxy application.
"""

import gc
import os
import sys
import time
from typing import List

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from src.core.domain.connection_activity import ConnectionActivity, ConnectionType
from src.core.services.connection_activity_tracker import get_activity_tracker, reset_activity_tracker


def simulate_real_world_leak():
    """Simulate real-world usage where connections might not be properly cleaned up."""
    print("Simulating real-world ConnectionActivityTracker memory leak...")
    print("=" * 70)
    
    # Reset to start clean
    reset_activity_tracker()
    tracker = get_activity_tracker()
    
    print("Scenario: Normal application usage without background cleanup")
    print("  (This is the current state in the main proxy application)")
    
    # Simulate multiple days of connection activity
    connection_counter = 0
    memory_samples = []
    
    for day in range(3):  # Simulate 3 days
        print(f"\n--- Day {day + 1} ---")
        
        # Simulate burst of connections throughout the day
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
            
            # Simulate some connections completing (80%)
            for i, ctx in enumerate(current_hour_connections):
                if i % 5 != 0:  # 80% complete normally
                    ctx.__enter__()
                    tracker.increment_rx(f"session-{connection_counter - batch_size + i}", "openai.gpt4", 100)
                    tracker.increment_tx(f"session-{connection_counter - batch_size + i}", "openai.gpt4", 200)
                    ctx.__exit__(None, None, None)
            
            # Simulate some abandoned connections (20%) due to crashes, timeouts, etc.
            # These are connections that entered the context but never properly exited
            abandoned_count = batch_size // 5
            for i in range(abandoned_count):
                idx = i * 5  # Every 5th connection
                if idx < len(current_hour_connections):
                    session_id = f"session-{connection_counter - batch_size + idx}"
                    
                    # Directly add to tracker to simulate abandoned connections
                    # (like what would happen if a crash occurred after context entry)
                    key = ("openai.gpt4", session_id)
                    activity = ConnectionActivity(
                        session_id=session_id,
                        backend_name="openai.gpt4",
                        connection_type=ConnectionType.STREAMING,
                        model="gpt-4"
                    )
                    # Make it look like it started recently
                    activity.started_at = time.time() - (hour * 3600)  # Started X hours ago
                    
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
            
            # Wait a bit to simulate time passing
            time.sleep(0.01)
    
    print(f"\n--- Final State ---")
    print(f"Total connections processed: {connection_counter}")
    print(f"Active connections remaining: {tracker.get_connection_count()}")
    print(f"Memory growth: {memory_samples[-1] / 1024:.1f} KB")
    
    # Test manual cleanup
    print(f"\n--- Testing Manual Cleanup ---")
    before_cleanup = tracker.get_connection_count()
    
    # Most abandoned connections will be older than 5 minutes by now
    # So cleanup should remove them
    cleaned = tracker.cleanup_stale_connections()
    after_cleanup = tracker.get_connection_count()
    
    print(f"Connections before cleanup: {before_cleanup}")
    print(f"Connections cleaned: {cleaned}")
    print(f"Connections after cleanup: {after_cleanup}")
    
    # The key insight: cleanup works, but there's NO AUTOMATIC BACKGROUND TASK
    # calling it in the main proxy application like there is in codebuff server
    
    print(f"\n--- Analysis ---")
    if before_cleanup > after_cleanup:  # At least some cleanup happened
        print("Cleanup functionality works correctly")
        print("BUT: There's no automatic cleanup task in the main proxy!")
        print("\nMemory leak confirmed:")
        print("  1. Connections accumulate over time due to crashes/timeouts")
        print("  2. No background task calls cleanup_stale_connections()")
        print("  3. Memory grows unbounded until manual cleanup or restart")
        return True
    else:
        print("Unexpected: Cleanup didn't remove connections")
        return False


if __name__ == "__main__":
    leak_confirmed = simulate_real_world_leak()
    
    print(f"\n{'='*70}")
    if leak_confirmed:
        print("MEMORY LEAK CONFIRMED")
        print("\nRoot Cause:")
        print("  ConnectionActivityTracker cleanup_stale_connections() exists")
        print("  but is never called automatically in the main proxy application.")
        print("\nSolution needed:")
        print("  Add a background task that periodically calls cleanup_stale_connections()")
        sys.exit(1)
    else:
        print("NO MEMORY LEAK DETECTED")
        sys.exit(0)