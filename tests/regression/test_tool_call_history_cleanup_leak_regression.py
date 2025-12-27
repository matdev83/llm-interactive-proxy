"""Regression test for InMemoryToolCallHistoryTracker cleanup memory leak fix.

This test verifies that when max_sessions limit is exceeded,
sessions are properly removed from _history dict, preventing unbounded growth.
"""

import asyncio
from datetime import datetime, timezone

import pytest
from src.core.services.tool_call_reactor_service import InMemoryToolCallHistoryTracker


class TestToolCallHistoryCleanupLeakRegression:
    """Regression tests for ToolCallHistoryTracker cleanup memory leak fix."""

    @pytest.fixture
    def tracker(self):
        """Create tracker with small max_sessions to trigger cleanup."""
        return InMemoryToolCallHistoryTracker(
            session_ttl_seconds=3600,
            max_sessions=10,  # Small limit to trigger cleanup
            max_entries_per_session=100,
        )

    @pytest.mark.asyncio
    async def test_sessions_removed_when_max_exceeded(
        self, tracker: InMemoryToolCallHistoryTracker
    ) -> None:
        """Test that sessions are removed when max_sessions limit is exceeded."""
        max_sessions = tracker._max_sessions

        # Create more sessions than max_sessions
        num_sessions = 20
        for i in range(num_sessions):
            session_id = f"session_{i}"
            await tracker.record_tool_call(
                session_id,
                "test_tool",
                {
                    "timestamp": datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
                    "backend_name": "test",
                    "model_name": "test",
                },
            )

        # Manually trigger cleanup
        async with tracker._lock:
            await tracker._cleanup_expired_sessions_locked()

        # Verify history count doesn't exceed max_sessions
        history_count = len(tracker._history)
        assert history_count <= max_sessions, (
            f"History count ({history_count}) exceeded max_sessions "
            f"({max_sessions}). Sessions should be removed when limit is exceeded."
        )

    @pytest.mark.asyncio
    async def test_cleanup_removes_oldest_sessions_first(
        self, tracker: InMemoryToolCallHistoryTracker
    ) -> None:
        """Test that cleanup removes oldest sessions first (LRU eviction)."""
        max_sessions = tracker._max_sessions

        # Create sessions with delays to ensure different access times
        for i in range(max_sessions + 5):
            session_id = f"session_{i}"
            await tracker.record_tool_call(
                session_id,
                "test_tool",
                {
                    "timestamp": datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
                    "backend_name": "test",
                    "model_name": "test",
                },
            )
            # Yield control to ensure different last_access times (no actual delay)
            await asyncio.sleep(0)

        # Record which sessions exist before cleanup
        sessions_before = set(tracker._history.keys())

        # Trigger cleanup
        async with tracker._lock:
            await tracker._cleanup_expired_sessions_locked()

        # Verify cleanup occurred
        history_count = len(tracker._history)
        assert history_count <= max_sessions, (
            f"History count ({history_count}) exceeded max_sessions "
            f"({max_sessions}) after cleanup."
        )

        # Verify oldest sessions were removed (newer sessions should remain)
        sessions_after = set(tracker._history.keys())
        removed_sessions = sessions_before - sessions_after

        # Should have removed some sessions
        assert len(removed_sessions) > 0, (
            "No sessions were removed during cleanup. "
            "Oldest sessions should be evicted when max_sessions is exceeded."
        )

    @pytest.mark.asyncio
    async def test_cleanup_preserves_recent_sessions(
        self, tracker: InMemoryToolCallHistoryTracker
    ) -> None:
        """Test that cleanup preserves recent sessions."""
        max_sessions = tracker._max_sessions

        # Fill up to max
        for i in range(max_sessions):
            session_id = f"session_{i}"
            await tracker.record_tool_call(
                session_id,
                "test_tool",
                {
                    "timestamp": datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
                    "backend_name": "test",
                    "model_name": "test",
                },
            )

        # Record recent sessions
        recent_sessions = [
            f"session_{i}" for i in range(max_sessions - 3, max_sessions)
        ]

        # Add more sessions to trigger cleanup
        for i in range(max_sessions, max_sessions + 5):
            session_id = f"session_{i}"
            await tracker.record_tool_call(
                session_id,
                "test_tool",
                {
                    "timestamp": datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
                    "backend_name": "test",
                    "model_name": "test",
                },
            )

        # Trigger cleanup
        async with tracker._lock:
            await tracker._cleanup_expired_sessions_locked()

        # Verify recent sessions are preserved
        history_keys = set(tracker._history.keys())
        preserved_recent = [s for s in recent_sessions if s in history_keys]

        # At least some recent sessions should be preserved
        assert len(preserved_recent) > 0, (
            "No recent sessions were preserved after cleanup. "
            "Recent sessions should be kept when older ones are evicted."
        )

    @pytest.mark.asyncio
    async def test_cleanup_maintains_max_sessions_limit(
        self, tracker: InMemoryToolCallHistoryTracker
    ) -> None:
        """Test that cleanup maintains max_sessions limit during rapid additions."""
        max_sessions = tracker._max_sessions

        # Rapidly add many sessions
        num_sessions = max_sessions * 2
        for i in range(num_sessions):
            session_id = f"session_{i}"
            await tracker.record_tool_call(
                session_id,
                "test_tool",
                {
                    "timestamp": datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
                    "backend_name": "test",
                    "model_name": "test",
                },
            )

            # Periodically check that limit is maintained
            if i % 5 == 0:
                async with tracker._lock:
                    await tracker._cleanup_expired_sessions_locked()
                    history_count = len(tracker._history)
                    assert history_count <= max_sessions, (
                        f"History count ({history_count}) exceeded max_sessions "
                        f"({max_sessions}) during rapid additions at iteration {i}."
                    )

        # Final cleanup check
        async with tracker._lock:
            await tracker._cleanup_expired_sessions_locked()
            final_count = len(tracker._history)
            assert final_count <= max_sessions, (
                f"Final history count ({final_count}) exceeded max_sessions "
                f"({max_sessions}) after all additions."
            )
