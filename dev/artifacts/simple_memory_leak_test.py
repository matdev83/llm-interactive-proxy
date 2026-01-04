#!/usr/bin/env python3
"""Simplified memory leak test for ConnectionActivityTracker."""

import os
import sys
import time

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.core.domain.connection_activity import ConnectionActivity, ConnectionType
from src.core.services.connection_activity_tracker import (
    get_activity_tracker,
    reset_activity_tracker,
)


def test_memory_leak():
    print("Testing memory leak in ConnectionActivityTracker...")

    # Reset to start clean
    reset_activity_tracker()
    tracker = get_activity_tracker()

    # Check initial state
    print(f"Initial connections: {tracker.get_connection_count()}")

    # Create abandoned connections by directly manipulating internal state
    print("Creating 500 abandoned connections...")

    for i in range(500):
        key = ("test-backend", f"abandoned-session-{i}")
        activity = ConnectionActivity(
            session_id=f"abandoned-session-{i}",
            backend_name="test-backend",
            connection_type=ConnectionType.NON_STREAMING,
            model="test-model",
        )
        # Make it old enough to be considered stale
        activity.started_at = time.time() - 600  # 10 minutes ago

        with tracker._lock:
            tracker._connections[key] = activity

    print(f"Connections after creation: {tracker.get_connection_count()}")

    # Test cleanup - this should remove the stale connections
    print("Running cleanup...")
    cleaned = tracker.cleanup_stale_connections()
    print(f"Connections cleaned: {cleaned}")
    print(f"Connections after cleanup: {tracker.get_connection_count()}")

    # Determine if leak exists
    if tracker.get_connection_count() > 0:
        print("MEMORY LEAK CONFIRMED: Connections not cleaned up properly")
        return True
    else:
        print("NO LEAK: Cleanup worked correctly")
        return False


if __name__ == "__main__":
    leak_detected = test_memory_leak()
    sys.exit(1 if leak_detected else 0)
