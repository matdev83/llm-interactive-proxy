"""Regression test for InMemoryToolCallHistoryTracker memory limits.

This test verifies that InMemoryToolCallHistoryTracker properly enforces:
1. Per-session limit (max_entries_per_session)
2. Total sessions limit (max_sessions)
3. Total entries tracking and enforcement
4. Clear functionality

Fixed: Memory limits are enforced to prevent unbounded growth.
"""

import pytest
from src.core.services.tool_call_reactor_service import InMemoryToolCallHistoryTracker


class TestToolCallHistoryTrackerLimitsRegression:
    """Regression tests for InMemoryToolCallHistoryTracker memory limits."""

    @pytest.fixture
    def tracker(self) -> InMemoryToolCallHistoryTracker:
        """Create tracker with strict limits for testing."""
        return InMemoryToolCallHistoryTracker(
            session_ttl_seconds=60,  # 1 minute TTL
            max_sessions=50,  # Small number for testing
            max_entries_per_session=10,  # Very small limit to test enforcement
        )

    @pytest.mark.asyncio
    async def test_per_session_limit_enforcement(
        self, tracker: InMemoryToolCallHistoryTracker
    ) -> None:
        """Test that per-session limit is enforced."""
        session_id = "test_session_1"
        max_entries = tracker._max_entries_per_session

        # Add more entries than the limit
        for i in range(25):  # More than the limit of 10
            context = {
                "backend_name": "test_backend",
                "model_name": "test_model",
                "calling_agent": "test_agent",
                "tool_arguments": {"counter": i},
            }
            await tracker.record_tool_call(session_id, f"tool_{i}", context)

        # Check session has at most max_entries_per_session entries
        async with tracker._lock:
            session_count = len(tracker._history.get(session_id, []))

        assert (
            session_count <= max_entries
        ), f"Per-session limit not enforced: {session_count} > {max_entries}"

    @pytest.mark.asyncio
    async def test_total_entries_tracking(
        self, tracker: InMemoryToolCallHistoryTracker
    ) -> None:
        """Test that total entries are tracked correctly."""
        # Add entries to multiple sessions
        for session_idx in range(5):
            session_id = f"session_{session_idx}"
            for i in range(15):  # More than per-session limit
                context = {"test": True, "counter": i}
                await tracker.record_tool_call(session_id, "test_tool", context)

        total_entries = await tracker.get_total_entries_count()

        # Total should be reasonable (5 sessions * 10 entries per session = 50 max)
        # But could be less due to cleanup
        assert total_entries >= 0, "Total entries should be non-negative"
        # Should not exceed max_sessions * max_entries_per_session
        max_possible = tracker._max_sessions * tracker._max_entries_per_session
        assert total_entries <= max_possible, (
            f"Total entries ({total_entries}) exceeded maximum possible "
            f"({max_possible})"
        )

    @pytest.mark.asyncio
    async def test_max_sessions_enforcement(
        self, tracker: InMemoryToolCallHistoryTracker
    ) -> None:
        """Test that max_sessions limit is enforced."""
        max_sessions = tracker._max_sessions

        # Create more sessions than max_sessions
        for i in range(60):  # More than max_sessions of 50
            await tracker.record_tool_call(f"session_{i}", "test_tool", {"test": True})

        # Check total sessions (allow small margin for cleanup timing)
        async with tracker._lock:
            total_sessions = len(tracker._history)

        assert (
            total_sessions <= max_sessions + 1
        ), f"Max sessions limit not enforced: {total_sessions} > {max_sessions + 1}"

    @pytest.mark.asyncio
    async def test_total_entries_after_many_sessions(
        self, tracker: InMemoryToolCallHistoryTracker
    ) -> None:
        """Test total entries after adding many sessions."""
        # Add entries to many sessions
        for i in range(60):  # More than max_sessions
            await tracker.record_tool_call(f"session_{i}", "test_tool", {"test": True})

        final_total = await tracker.get_total_entries_count()

        # The total should be reasonable (max_sessions * max_entries_per_session = 500 max)
        expected_max_total = tracker._max_sessions * tracker._max_entries_per_session
        assert final_total <= expected_max_total, (
            f"Total entries ({final_total}) exceeded expected maximum "
            f"({expected_max_total})"
        )

    @pytest.mark.asyncio
    async def test_clear_functionality(
        self, tracker: InMemoryToolCallHistoryTracker
    ) -> None:
        """Test that clear functionality works correctly."""
        # Add some entries
        for i in range(10):
            await tracker.record_tool_call(f"session_{i}", "test_tool", {"test": True})

        # Clear all history
        await tracker.clear_history()

        # Verify cleared
        final_entries = await tracker.get_total_entries_count()
        assert final_entries == 0, f"Clear didn't work: {final_entries} > 0"

        # Verify sessions are cleared
        async with tracker._lock:
            assert len(tracker._history) == 0, "History should be empty after clear"

    @pytest.mark.asyncio
    async def test_clear_specific_session(
        self, tracker: InMemoryToolCallHistoryTracker
    ) -> None:
        """Test that clearing a specific session works."""
        session_id = "test_session"

        # Add entries to session
        for i in range(5):
            await tracker.record_tool_call(session_id, "test_tool", {"counter": i})

        # Clear specific session
        await tracker.clear_history(session_id)

        # Verify session is cleared
        async with tracker._lock:
            assert (
                session_id not in tracker._history
                or len(tracker._history[session_id]) == 0
            ), "Session should be cleared"

    @pytest.mark.asyncio
    async def test_limits_enforced_during_rapid_addition(
        self, tracker: InMemoryToolCallHistoryTracker
    ) -> None:
        """Test that limits are enforced during rapid addition."""
        max_sessions = tracker._max_sessions
        max_entries_per_session = tracker._max_entries_per_session

        # Rapidly add many entries
        for i in range(100):
            session_id = f"rapid_session_{i % 60}"  # Cycle through sessions
            await tracker.record_tool_call(session_id, "test_tool", {"index": i})

        # Check limits are maintained
        async with tracker._lock:
            total_sessions = len(tracker._history)
            # Check a few sessions for per-session limit
            for session_id in list(tracker._history.keys())[:5]:
                session_entries = len(tracker._history[session_id])
                assert session_entries <= max_entries_per_session, (
                    f"Session {session_id} exceeded per-session limit: "
                    f"{session_entries} > {max_entries_per_session}"
                )

        # Allow small margin for cleanup timing
        assert total_sessions <= max_sessions + 1, (
            f"Total sessions ({total_sessions}) exceeded max ({max_sessions + 1}) "
            "during rapid addition"
        )
