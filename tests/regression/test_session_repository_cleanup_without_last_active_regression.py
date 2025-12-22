"""Regression test for InMemorySessionRepository cleanup with sessions without last_active_at.

This test verifies that InMemorySessionRepository properly cleans up sessions
even when they don't have last_active_at set, falling back to _last_accessed tracking.

Fixed: InMemorySessionRepository.cleanup_expired() now properly falls back to
_last_accessed timestamp when session.last_active_at is None or not set.
"""

import asyncio
import time
from datetime import datetime, timezone

import pytest

from src.core.repositories.in_memory_session_repository import InMemorySessionRepository


class MockSession:
    """Mock session for testing."""

    def __init__(self, session_id: str, last_active_at: datetime | None = None):
        self.id = session_id
        self.history = []
        self.last_active_at = last_active_at


class TestSessionRepositoryCleanupWithoutLastActiveRegression:
    """Regression tests for InMemorySessionRepository cleanup fix."""

    @pytest.fixture
    def repo(self) -> InMemorySessionRepository:
        """Create InMemorySessionRepository for testing."""
        return InMemorySessionRepository()

    @pytest.mark.asyncio
    async def test_cleanup_sessions_without_last_active_at(
        self, repo: InMemorySessionRepository
    ) -> None:
        """Test that sessions without last_active_at are cleaned up using _last_accessed."""
        # Add sessions WITHOUT last_active_at set
        for i in range(100):
            session = MockSession(f"session_{i}", last_active_at=None)
            await repo.add(session)

        assert len(await repo.get_all()) == 100, "All sessions should be added"

        # Wait a bit to ensure _last_accessed timestamps are set
        await asyncio.sleep(0.1)

        # Run cleanup with very short TTL (should clean all sessions)
        cleaned = await repo.cleanup_expired(max_age_seconds=0)

        remaining = len(await repo.get_all())

        assert cleaned > 0, "Should have cleaned some sessions"
        assert remaining == 0, (
            f"All sessions should be cleaned up, but {remaining} remain. "
            "Sessions without last_active_at should use _last_accessed fallback."
        )

    @pytest.mark.asyncio
    async def test_cleanup_mixed_sessions_with_and_without_last_active(
        self, repo: InMemorySessionRepository
    ) -> None:
        """Test cleanup with mix of sessions with and without last_active_at."""
        # Add sessions with last_active_at
        old_time = datetime.now(timezone.utc).replace(
            year=2020, month=1, day=1
        )  # Very old
        for i in range(50):
            session = MockSession(
                f"old_session_{i}", last_active_at=old_time
            )
            await repo.add(session)

        # Add sessions without last_active_at
        for i in range(50):
            session = MockSession(f"new_session_{i}", last_active_at=None)
            await repo.add(session)

        # Wait a bit
        await asyncio.sleep(0.1)

        # Run cleanup with TTL that should clean old sessions
        # Sessions with old last_active_at should be cleaned
        # Sessions without last_active_at should use _last_accessed (which is recent)
        cleaned = await repo.cleanup_expired(max_age_seconds=1)

        remaining = len(await repo.get_all())

        # Old sessions should be cleaned, new sessions without last_active_at
        # should use _last_accessed (recent) and not be cleaned
        assert cleaned > 0, "Should have cleaned old sessions"
        # New sessions should remain (they use _last_accessed which is recent)
        assert remaining > 0, (
            "Sessions without last_active_at should remain "
            "if _last_accessed is recent"
        )

    @pytest.mark.asyncio
    async def test_cleanup_falls_back_to_last_accessed(
        self, repo: InMemorySessionRepository
    ) -> None:
        """Test that cleanup falls back to _last_accessed when last_active_at is None."""
        # Add session without last_active_at
        session = MockSession("test_session", last_active_at=None)
        await repo.add(session)

        # Verify _last_accessed was set
        assert (
            "test_session" in repo._last_accessed
        ), "_last_accessed should be set when adding session"

        initial_timestamp = repo._last_accessed["test_session"]

        # Wait a bit
        await asyncio.sleep(0.1)

        # Run cleanup with TTL that should clean based on _last_accessed
        # Since we just added it, it should not be cleaned
        cleaned = await repo.cleanup_expired(max_age_seconds=0.05)

        # Session should be cleaned because TTL is very short
        remaining = len(await repo.get_all())
        assert remaining == 0, (
            "Session should be cleaned when TTL is shorter than age "
            "based on _last_accessed"
        )

    @pytest.mark.asyncio
    async def test_cleanup_handles_sessions_with_last_active_at(
        self, repo: InMemorySessionRepository
    ) -> None:
        """Test that cleanup properly handles sessions with last_active_at set."""
        # Add session with last_active_at
        old_time = datetime.now(timezone.utc).replace(
            year=2020, month=1, day=1
        )
        session = MockSession("old_session", last_active_at=old_time)
        await repo.add(session)

        # Run cleanup
        cleaned = await repo.cleanup_expired(max_age_seconds=1)

        remaining = len(await repo.get_all())

        assert cleaned == 1, "Should have cleaned old session"
        assert remaining == 0, "Session with old last_active_at should be cleaned"

    @pytest.mark.asyncio
    async def test_cleanup_handles_sessions_with_none_last_active_at(
        self, repo: InMemorySessionRepository
    ) -> None:
        """Test that cleanup handles sessions with explicitly None last_active_at."""
        # Add session with explicitly None last_active_at
        session = MockSession("none_session", last_active_at=None)
        await repo.add(session)

        # Verify _last_accessed was set
        assert (
            "none_session" in repo._last_accessed
        ), "_last_accessed should be set"

        # Wait a bit to ensure timestamp is set
        await asyncio.sleep(0.1)

        # Run cleanup with TTL=0 to clean all sessions
        cleaned = await repo.cleanup_expired(max_age_seconds=0)

        remaining = len(await repo.get_all())

        # Session should be cleaned based on _last_accessed
        assert cleaned == 1, "Should have cleaned session with None last_active_at"
        assert remaining == 0, (
            "Session with None last_active_at should be cleaned "
            "using _last_accessed fallback"
        )
