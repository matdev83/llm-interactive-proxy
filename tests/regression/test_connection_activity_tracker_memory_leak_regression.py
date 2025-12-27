"""Regression test for ConnectionActivityTracker memory leak fix.

This test verifies that abandoned connections are properly cleaned up
and don't accumulate over multiple connection cycles.
"""

from freezegun import freeze_time

from src.core.domain.connection_activity import ConnectionActivity, ConnectionType
from src.core.services.connection_activity_tracker import (
    ConnectionActivityTracker,
    reset_activity_tracker,
)


class TestConnectionActivityTrackerMemoryLeakRegression:
    """Regression tests for ConnectionActivityTracker memory leak fix."""

    def setup_method(self) -> None:
        """Reset tracker before each test."""
        reset_activity_tracker()

    def teardown_method(self) -> None:
        """Reset tracker after each test."""
        reset_activity_tracker()

    def test_abandoned_connections_are_cleaned_up(self) -> None:
        """Test that abandoned connections are cleaned up by cleanup_stale_connections."""
        import time
        
        with freeze_time() as frozen_time:
            tracker = ConnectionActivityTracker(stale_timeout_seconds=0.1)

            # Manually add abandoned connections (simulating orphaned connections)
            num_abandoned = 10
            for i in range(num_abandoned):
                stale_conn = ConnectionActivity(
                    session_id=f"abandoned-session-{i}",
                    backend_name="test-backend",
                    connection_type=ConnectionType.NON_STREAMING,
                    started_at=time.time() - 1.0,  # Started 1 second ago
                )
                with tracker._lock:
                    tracker._connections[("test-backend", f"abandoned-session-{i}")] = (
                        stale_conn
                    )

            assert tracker.get_connection_count() == num_abandoned

            # Advance time to expire timeout
            frozen_time.tick(0.15)

            # Cleanup should remove all stale connections
            removed = tracker.cleanup_stale_connections()
            assert removed == num_abandoned, (
                f"Expected {num_abandoned} connections to be cleaned up, "
                f"but only {removed} were removed."
            )
            assert tracker.get_connection_count() == 0, (
                f"Expected 0 connections after cleanup, "
                f"but {tracker.get_connection_count()} remain."
            )

    def test_multiple_cycles_dont_accumulate_connections(self) -> None:
        """Test that multiple connection cycles don't accumulate connections."""
        tracker = ConnectionActivityTracker()

        # Simulate multiple connection cycles
        num_cycles = 5
        connections_per_cycle = 100

        for cycle in range(num_cycles):
            # Create connections properly using context manager
            contexts = []
            for i in range(connections_per_cycle):
                ctx = tracker.track_connection(
                    session_id=f"cycle-{cycle}-session-{i}",
                    backend_name="test-backend",
                    connection_type=ConnectionType.STREAMING,
                    model="test-model",
                )
                contexts.append(ctx)

            # Increment some counters
            for i in range(connections_per_cycle):
                tracker.increment_rx(f"cycle-{cycle}-session-{i}", "test-backend", 100)
                tracker.increment_tx(f"cycle-{cycle}-session-{i}", "test-backend", 200)

            # Properly close all connections
            for ctx in contexts:
                ctx.__enter__()
                ctx.__exit__(None, None, None)

            # Verify all connections are cleaned up after each cycle
            assert tracker.get_connection_count() == 0, (
                f"Cycle {cycle + 1}: Expected 0 connections after cleanup, "
                f"but {tracker.get_connection_count()} remain. "
                "Connections are accumulating across cycles."
            )

    def test_mixed_normal_and_abandoned_connections(self) -> None:
        """Test cleanup with mix of normal and abandoned connections."""
        import time
        
        with freeze_time() as frozen_time:
            tracker = ConnectionActivityTracker(stale_timeout_seconds=0.1)

            # Create some normal connections (enter context to track them)
            normal_contexts = []
            for i in range(5):
                ctx = tracker.track_connection(
                    session_id=f"normal-session-{i}",
                    backend_name="test-backend",
                    connection_type=ConnectionType.STREAMING,
                )
                ctx.__enter__()  # Enter context to actually track the connection
                normal_contexts.append(ctx)

            # Create some abandoned connections
            for i in range(5):
                stale_conn = ConnectionActivity(
                    session_id=f"abandoned-session-{i}",
                    backend_name="test-backend",
                    connection_type=ConnectionType.NON_STREAMING,
                    started_at=time.time() - 1.0,  # Started 1 second ago
                )
                with tracker._lock:
                    tracker._connections[("test-backend", f"abandoned-session-{i}")] = (
                        stale_conn
                    )

            assert tracker.get_connection_count() == 10

            # Close normal connections
            for ctx in normal_contexts:
                ctx.__exit__(None, None, None)

            assert (
                tracker.get_connection_count() == 5
            ), "Normal connections were not properly cleaned up."

            # Advance time to expire timeout
            frozen_time.tick(0.15)

            # Cleanup should remove abandoned connections
            removed = tracker.cleanup_stale_connections()
            assert removed == 5, (
                f"Expected 5 abandoned connections to be cleaned up, "
                f"but only {removed} were removed."
            )
            assert tracker.get_connection_count() == 0, (
                f"Expected 0 connections after cleanup, "
                f"but {tracker.get_connection_count()} remain."
            )

    def test_cleanup_preserves_recent_connections(self) -> None:
        """Test that cleanup doesn't remove recently created connections."""
        tracker = ConnectionActivityTracker(stale_timeout_seconds=0.5)

        # Create old abandoned connections first (started 1 second ago)
        old_start_time = time.time() - 1.0
        for i in range(3):
            stale_conn = ConnectionActivity(
                session_id=f"old-session-{i}",
                backend_name="test-backend",
                connection_type=ConnectionType.NON_STREAMING,
                started_at=old_start_time,
            )
            with tracker._lock:
                tracker._connections[("test-backend", f"old-session-{i}")] = stale_conn

        # Create recent connections AFTER old ones (enter context to track them)
        recent_contexts = []
        for i in range(3):
            ctx = tracker.track_connection(
                session_id=f"recent-session-{i}",
                backend_name="test-backend",
                connection_type=ConnectionType.STREAMING,
            )
            ctx.__enter__()  # Enter context to actually track the connection
            recent_contexts.append(ctx)

        assert tracker.get_connection_count() == 6

        # Don't wait - cleanup immediately
        # Old connections (1s old) should be removed, recent ones (< 0.1s old) should remain
        removed = tracker.cleanup_stale_connections()
        assert removed == 3, (
            f"Expected 3 old connections to be cleaned up, "
            f"but {removed} were removed."
        )
        assert tracker.get_connection_count() == 3, (
            f"Expected 3 recent connections to remain, "
            f"but {tracker.get_connection_count()} connections found."
        )

        # Clean up recent connections properly
        for ctx in recent_contexts:
            ctx.__exit__(None, None, None)

        assert tracker.get_connection_count() == 0
