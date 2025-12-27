"""Regression test for InMemorySessionRepository unbounded growth fix.

This test verifies that InMemorySessionRepository doesn't grow unbounded
when many sessions are added without explicit cleanup calls.

Fixed: InMemorySessionRepository now has automatic cleanup via _maybe_cleanup_stale_sessions()
and max_sessions limit to prevent unbounded growth even when cleanup_expired is never called.
"""

from datetime import datetime, timezone

import pytest
from src.core.domain.session import Session, SessionState
from src.core.repositories.in_memory_session_repository import InMemorySessionRepository


class TestInMemorySessionRepositoryUnboundedGrowthRegression:
    """Regression tests for InMemorySessionRepository unbounded growth fix."""

    @pytest.fixture
    def repository(self) -> InMemorySessionRepository:
        """Create an InMemorySessionRepository instance for testing."""
        # Use smaller max_sessions for faster test execution
        return InMemorySessionRepository(max_sessions=100, default_ttl_seconds=3600)

    @pytest.mark.asyncio
    async def test_repository_does_not_grow_unbounded_without_cleanup(
        self, repository: InMemorySessionRepository
    ) -> None:
        """Test that repository doesn't grow unbounded when cleanup_expired is never called."""
        # Create many sessions (more than max_sessions)
        session_count = 200  # More than max_sessions (100)

        for i in range(session_count):
            session = Session(
                session_id=f"session_{i}",
                state=SessionState(),
            )
            session.user_id = f"user_{i % 10}"
            await repository.add(session)

        # Repository should not exceed max_sessions due to automatic eviction
        all_sessions = await repository.get_all()
        final_count = len(all_sessions)

        assert final_count <= repository._max_sessions, (
            f"Repository grew unbounded: {final_count} sessions > max_sessions "
            f"({repository._max_sessions}). Automatic cleanup should prevent unbounded growth."
        )

        # Verify internal structures are also bounded
        assert len(repository._sessions) <= repository._max_sessions, (
            f"Internal _sessions dict grew unbounded: {len(repository._sessions)} > "
            f"max_sessions ({repository._max_sessions})"
        )

        assert len(repository._last_accessed) <= repository._max_sessions, (
            f"Internal _last_accessed dict grew unbounded: {len(repository._last_accessed)} > "
            f"max_sessions ({repository._max_sessions})"
        )

    @pytest.mark.asyncio
    async def test_cleanup_expired_removes_expired_sessions(
        self, repository: InMemorySessionRepository
    ) -> None:
        """Test that cleanup_expired properly removes expired sessions."""
        from datetime import timedelta

        from freezegun import freeze_time

        # Create sessions with old last_active_at timestamps
        with freeze_time("2024-01-01 12:00:00Z"):
            fixed_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
            old_time = fixed_time - timedelta(seconds=1000)
            for i in range(50):
                session = Session(
                    session_id=f"session_{i}",
                    state=SessionState(),
                )
                session.user_id = f"user_{i % 5}"
                session.last_active_at = old_time  # Set to old time
                await repository.add(session)

        initial_count = len(await repository.get_all())
        assert initial_count == 50, "Should have 50 sessions initially"

        # Cleanup with max_age=500 should remove sessions older than 500 seconds
        cleaned = await repository.cleanup_expired(max_age_seconds=500)

        assert cleaned > 0, "cleanup_expired should remove expired sessions"

        final_count = len(await repository.get_all())
        # Verify that cleanup removed sessions
        assert final_count < initial_count, (
            f"cleanup_expired should remove sessions, but count didn't decrease: "
            f"{final_count} >= {initial_count}. Removed {cleaned} sessions."
        )

        # Verify all old sessions were removed
        assert final_count == 0, (
            f"All old sessions should be cleaned up, but {final_count} remain. "
            f"cleanup_expired removed {cleaned} sessions."
        )

    @pytest.mark.asyncio
    async def test_internal_structures_stay_synchronized(
        self, repository: InMemorySessionRepository
    ) -> None:
        """Test that internal structures (_sessions, _last_accessed, etc.) stay synchronized."""
        # Create sessions
        for i in range(150):  # More than max_sessions
            session = Session(
                session_id=f"session_{i}",
                state=SessionState(),
            )
            session.user_id = f"user_{i % 10}"
            await repository.add(session)

        # After automatic eviction, internal structures should be synchronized
        sessions_count = len(repository._sessions)
        last_accessed_count = len(repository._last_accessed)

        assert sessions_count == last_accessed_count, (
            f"Internal structures out of sync: _sessions has {sessions_count} entries, "
            f"_last_accessed has {last_accessed_count} entries. "
            "They should have the same number of entries."
        )

        # Both should be bounded by max_sessions
        assert (
            sessions_count <= repository._max_sessions
        ), f"_sessions exceeds max_sessions: {sessions_count} > {repository._max_sessions}"
        assert last_accessed_count <= repository._max_sessions, (
            f"_last_accessed exceeds max_sessions: {last_accessed_count} > "
            f"{repository._max_sessions}"
        )

    @pytest.mark.asyncio
    async def test_max_sessions_limit_enforced(
        self, repository: InMemorySessionRepository
    ) -> None:
        """Test that max_sessions limit is enforced through automatic eviction."""
        # Create exactly max_sessions + 50 sessions
        excess_sessions = 50
        total_sessions = repository._max_sessions + excess_sessions

        for i in range(total_sessions):
            session = Session(
                session_id=f"session_{i}",
                state=SessionState(),
            )
            session.user_id = f"user_{i % 10}"
            await repository.add(session)

        # Repository should not exceed max_sessions
        final_count = len(await repository.get_all())

        assert final_count <= repository._max_sessions, (
            f"Repository exceeded max_sessions: {final_count} > "
            f"{repository._max_sessions}. Automatic eviction should enforce the limit."
        )

        # Should have evicted at least excess_sessions
        assert final_count <= repository._max_sessions, (
            f"Expected at most {repository._max_sessions} sessions after eviction, "
            f"got {final_count}"
        )
