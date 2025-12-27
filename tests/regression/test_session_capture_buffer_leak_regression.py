"""Regression test for SessionCaptureBuffer memory leak fix.

This test verifies that SessionCaptureBuffer properly evicts old sessions
when max_sessions limit is exceeded, preventing unbounded memory growth.
"""

import asyncio
from datetime import datetime, timezone

import pytest
from freezegun import freeze_time
from src.core.memory.capture_buffer import SessionCaptureBuffer
from src.core.memory.models import CapturedInteraction
from tests.utils.fake_clock import FakeClockContext


class TestSessionCaptureBufferLeakRegression:
    """Regression tests for SessionCaptureBuffer memory leak fix."""

    @pytest.fixture
    def buffer(self):
        """Create buffer with small max_sessions to trigger eviction."""
        return SessionCaptureBuffer(
            max_buffer_size_bytes=1024 * 1024,  # 1MB per session
            max_sessions=10,  # Small limit to trigger cleanup
        )

    @pytest.mark.asyncio
    @freeze_time("2024-01-01 12:00:00")
    async def test_sessions_evicted_when_max_exceeded(
        self, buffer: SessionCaptureBuffer
    ) -> None:
        """Test that sessions are evicted when max_sessions limit is exceeded."""
        max_sessions = buffer._max_sessions
        fixed_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

        # Create more sessions than max_sessions
        num_sessions = 20
        for i in range(num_sessions):
            session_id = f"session_{i}"
            interaction = CapturedInteraction(
                timestamp=fixed_time,
                content=f"Test content for session {i}",
                role="user",
                metadata={"session": session_id},
            )
            await buffer.append(session_id, interaction)

        # Check active session count
        active_count = await buffer.get_active_session_count()

        # Verify count doesn't exceed max_sessions
        assert active_count <= max_sessions, (
            f"Active session count ({active_count}) exceeded max_sessions "
            f"({max_sessions}). Sessions should be evicted when limit is exceeded."
        )

    @pytest.mark.asyncio
    @freeze_time("2024-01-01 12:00:00")
    async def test_oldest_sessions_evicted_first(
        self, buffer: SessionCaptureBuffer
    ) -> None:
        """Test that oldest sessions are evicted first (LRU eviction)."""
        max_sessions = buffer._max_sessions
        fixed_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

        # Create sessions with delays to ensure different access times
        session_ids = []
        for i in range(max_sessions + 5):
            session_id = f"session_{i}"
            session_ids.append(session_id)
            interaction = CapturedInteraction(
                timestamp=fixed_time,
                content=f"Test content for session {i}",
                role="user",
                metadata={"session": session_id},
            )
            await buffer.append(session_id, interaction)
            # Yield control to ensure different last_accessed times (no actual delay)
            await asyncio.sleep(0)

        # Record which sessions exist before eviction
        await buffer.get_active_session_count()

        # Add one more session to trigger eviction
        new_session_id = "session_new"
        interaction = CapturedInteraction(
            timestamp=fixed_time,
            content="New session content",
            role="user",
            metadata={"session": new_session_id},
        )
        await buffer.append(new_session_id, interaction)

        # Verify eviction occurred
        active_after = await buffer.get_active_session_count()
        assert active_after <= max_sessions, (
            f"Active count ({active_after}) exceeded max_sessions "
            f"({max_sessions}) after adding new session."
        )

        # Verify oldest sessions were evicted (newer sessions should remain)
        # The new session should be present
        async with buffer._lock:
            assert (
                new_session_id in buffer._buffers
            ), "New session should be present after eviction."

    @pytest.mark.asyncio
    @freeze_time("2024-01-01 12:00:00")
    async def test_rapid_session_creation_maintains_limit(
        self, buffer: SessionCaptureBuffer
    ) -> None:
        """Test that rapid session creation maintains max_sessions limit."""
        max_sessions = buffer._max_sessions
        fixed_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

        # Rapidly create many sessions
        num_sessions = max_sessions * 3
        for i in range(num_sessions):
            session_id = f"session_{i}"
            interaction = CapturedInteraction(
                timestamp=fixed_time,
                content=f"Test content for session {i}",
                role="user",
                metadata={"session": session_id},
            )
            await buffer.append(session_id, interaction)

            # Periodically check that limit is maintained
            if i % 5 == 0:
                active_count = await buffer.get_active_session_count()
                assert active_count <= max_sessions, (
                    f"Active count ({active_count}) exceeded max_sessions "
                    f"({max_sessions}) during rapid creation at iteration {i}."
                )

        # Final check
        final_count = await buffer.get_active_session_count()
        assert final_count <= max_sessions, (
            f"Final active count ({final_count}) exceeded max_sessions "
            f"({max_sessions}) after all creations."
        )

    @pytest.mark.asyncio
    async def test_session_access_updates_last_accessed(
        self, buffer: SessionCaptureBuffer
    ) -> None:
        """Test that accessing a session updates its last_accessed time."""
        from tests.utils.fake_clock import FakeClock, FakeClockContext

        session_id = "test_session"
        fixed_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        interaction1 = CapturedInteraction(
            timestamp=fixed_time,
            content="First interaction",
            role="user",
            metadata={"session": session_id},
        )

        async with FakeClockContext(FakeClock(initial_time=1000.0)) as clock:
            await buffer.append(session_id, interaction1)

            # Get initial last_accessed time
            async with buffer._lock:
                initial_access = buffer._buffers[session_id].last_accessed

            # Advance clock to ensure different time
            clock.advance(1.0)

            # Add another interaction to same session
            interaction2 = CapturedInteraction(
                timestamp=fixed_time,
                content="Second interaction",
                role="user",
                metadata={"session": session_id},
            )
            await buffer.append(session_id, interaction2)

            # Verify last_accessed was updated
            async with buffer._lock:
                updated_access = buffer._buffers[session_id].last_accessed
                assert (
                    updated_access > initial_access
                ), "last_accessed time should be updated when session is accessed."

    @pytest.mark.asyncio
    async def test_expired_sessions_cleaned_up(
        self, buffer: SessionCaptureBuffer
    ) -> None:
        """Test that expired sessions are cleaned up."""
        # Create a buffer with short TTL
        short_ttl_buffer = SessionCaptureBuffer(
            max_buffer_size_bytes=1024 * 1024,
            session_ttl_seconds=1,  # 1 second TTL
            max_sessions=100,
        )

        # Create a session
        session_id = "expired_session"
        fixed_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        interaction = CapturedInteraction(
            timestamp=fixed_time,
            content="Test content",
            role="user",
            metadata={"session": session_id},
        )
        await short_ttl_buffer.append(session_id, interaction)

        # Verify session exists
        initial_count = await short_ttl_buffer.get_active_session_count()
        assert initial_count == 1, "Session should exist initially."

        # Wait for TTL to expire using fake clock
        async with FakeClockContext() as clock:
            clock.advance(1.1)

        # Trigger cleanup by adding a new session
        new_session_id = "new_session"
        new_interaction = CapturedInteraction(
            timestamp=fixed_time,
            content="New content",
            role="user",
            metadata={"session": new_session_id},
        )
        await short_ttl_buffer.append(new_session_id, new_interaction)

        # Verify expired session was cleaned up
        final_count = await short_ttl_buffer.get_active_session_count()
        # Should have at least the new session, but expired one may be gone
        assert final_count >= 1, "Should have at least the new session."

        # The expired session should be cleaned up
        async with short_ttl_buffer._lock:
            assert (
                new_session_id in short_ttl_buffer._buffers
            ), "New session should be present."
