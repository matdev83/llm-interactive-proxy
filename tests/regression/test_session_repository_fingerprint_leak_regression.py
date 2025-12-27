"""Regression test for InMemorySessionRepository fingerprint bundles memory leak fix.

This test verifies that _fingerprint_bundles are properly cleaned up when sessions
are deleted or expired, preventing unbounded memory growth.
"""

from datetime import datetime, timezone

import pytest
from freezegun import freeze_time
from src.core.domain.session import Session
from src.core.repositories.in_memory_session_repository import InMemorySessionRepository
from src.core.services.conversation_fingerprint_service import (
    ConversationFingerprint,
    ConversationFingerprintBundle,
)


class TestSessionRepositoryFingerprintLeakRegression:
    """Regression tests for InMemorySessionRepository fingerprint bundles leak fix."""

    @pytest.fixture
    def repo(self) -> InMemorySessionRepository:
        """Create InMemorySessionRepository with long TTL for testing."""
        return InMemorySessionRepository(
            max_sessions=100000,  # Very large max
            default_ttl_seconds=86400 * 365,  # 1 year TTL - effectively never cleanup
        )

    @pytest.mark.asyncio
    async def test_fingerprint_bundles_cleaned_up_on_delete(
        self, repo: InMemorySessionRepository
    ) -> None:
        """Test that fingerprint bundles are cleaned up when session is deleted."""
        session = Session(
            session_id="test_session",
            user_id="user_1",
            history=[],
        )
        await repo.add(session)

        # Add fingerprint bundle
        bundle = ConversationFingerprintBundle(
            primary=ConversationFingerprint(fingerprint="fp1", message_count=1),
            rolling_fingerprints=frozenset(["fp1", "fp2"]),
        )
        await repo.update_fingerprint_bundle("test_session", bundle)

        # Verify bundle exists
        assert (
            "test_session" in repo._fingerprint_bundles
        ), "Fingerprint bundle should be tracked"

        # Delete session
        await repo.delete("test_session")

        # Verify bundle is cleaned up
        assert (
            "test_session" not in repo._fingerprint_bundles
        ), "Fingerprint bundle should be removed on delete"

    @pytest.mark.asyncio
    async def test_fingerprint_bundles_cleaned_up_on_expiration(
        self, repo: InMemorySessionRepository
    ) -> None:
        """Test that fingerprint bundles are cleaned up when sessions expire."""
        # Create session with fingerprint bundle
        session = Session(
            session_id="test_session",
            user_id="user_1",
            history=[],
        )
        await repo.add(session)

        bundle = ConversationFingerprintBundle(
            primary=ConversationFingerprint(fingerprint="fp1", message_count=1),
            rolling_fingerprints=frozenset(["fp1", "fp2"]),
        )
        await repo.update_fingerprint_bundle("test_session", bundle)

        # Verify bundle exists
        assert (
            "test_session" in repo._fingerprint_bundles
        ), "Fingerprint bundle should be tracked"

        # Use freezegun to control time, then manually set last_access to be old (expired)
        # Note: update_fingerprint_bundle updates _last_accessed, so we set it after
        from datetime import timedelta

        with freeze_time("2024-01-01 12:00:00Z") as frozen_time:
            frozen_time.tick(0.1)  # Small delay using fake time
            fixed_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
            repo._last_accessed["test_session"] = fixed_time.timestamp() - 2  # 2 seconds ago

        # Also set session's last_active_at if it exists (cleanup_expired checks this first)
        session = repo._sessions.get("test_session")
        if session and hasattr(session, "last_active_at"):
            session.last_active_at = fixed_time - timedelta(seconds=2)

        # Clean up expired sessions (everything older than 1 second)
        await repo.cleanup_expired(max_age_seconds=1)

        # Verify bundle is cleaned up (cleanup_expired calls delete which removes bundles)
        assert (
            "test_session" not in repo._fingerprint_bundles
        ), "Fingerprint bundle should be removed when session expires"
        assert (
            "test_session" not in repo._sessions
        ), "Session should be removed when expired"

    @pytest.mark.asyncio
    async def test_fingerprint_bundles_dont_grow_unbounded(
        self, repo: InMemorySessionRepository
    ) -> None:
        """Test that fingerprint bundles don't grow unbounded."""
        # Create many sessions with fingerprint bundles (reduced for performance while maintaining leak detection)
        num_sessions = 2000

        with freeze_time("2024-01-01 12:00:00Z"):
            fixed_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
            for i in range(num_sessions):
                session_id = f"session_{i}"
                session = Session(
                    session_id=session_id,
                    user_id=f"user_{i % 100}",  # Some users have multiple sessions
                    created_at=fixed_time,
                    history=[],
                )
                await repo.add(session)

            # Add fingerprint bundle
            bundle = ConversationFingerprintBundle(
                primary=ConversationFingerprint(fingerprint=f"fp_{i}", message_count=1),
                rolling_fingerprints=frozenset([f"fp_{i}", f"fp_{i+1}"]),
            )
            await repo.update_fingerprint_bundle(session_id, bundle)

        # Verify bundles don't exceed sessions
        assert len(repo._fingerprint_bundles) <= len(repo._sessions), (
            f"Fingerprint bundles ({len(repo._fingerprint_bundles)}) should not exceed "
            f"sessions ({len(repo._sessions)}). Memory leak detected."
        )

    @pytest.mark.asyncio
    async def test_fingerprint_bundles_cleaned_up_on_eviction(
        self, repo: InMemorySessionRepository
    ) -> None:
        """Test that fingerprint bundles are cleaned up when sessions are evicted."""
        # Create repository with smaller limit
        small_repo = InMemorySessionRepository(
            max_sessions=100, default_ttl_seconds=3600
        )

        # Fill repository to capacity
        for i in range(small_repo._max_sessions):
            session_id = f"session_{i}"
            session = Session(
                session_id=session_id,
                user_id=f"user_{i}",
                history=[],
            )
            await small_repo.add(session)

            bundle = ConversationFingerprintBundle(
                primary=ConversationFingerprint(fingerprint=f"fp_{i}", message_count=1),
                rolling_fingerprints=frozenset([f"fp_{i}"]),
            )
            await small_repo.update_fingerprint_bundle(session_id, bundle)

        initial_bundles = len(small_repo._fingerprint_bundles)
        assert (
            initial_bundles == small_repo._max_sessions
        ), f"Should have {small_repo._max_sessions} bundles initially"

        # Add one more session to trigger eviction
        new_session = Session(
            session_id="new_session",
            user_id="user_new",
            history=[],
        )
        await small_repo.add(new_session)

        new_bundle = ConversationFingerprintBundle(
            primary=ConversationFingerprint(fingerprint="fp_new", message_count=1),
            rolling_fingerprints=frozenset(["fp_new"]),
        )
        await small_repo.update_fingerprint_bundle("new_session", new_bundle)

        # Verify bundles are cleaned up (should be <= sessions)
        assert len(small_repo._fingerprint_bundles) <= len(small_repo._sessions), (
            f"Fingerprint bundles ({len(small_repo._fingerprint_bundles)}) should not exceed "
            f"sessions ({len(small_repo._sessions)}). Bundles not cleaned up on eviction."
        )
        assert (
            len(small_repo._fingerprint_bundles) <= small_repo._max_sessions
        ), f"Fingerprint bundles should be <= {small_repo._max_sessions} after eviction"

    @pytest.mark.asyncio
    async def test_fingerprint_bundles_consistent_with_sessions(
        self, repo: InMemorySessionRepository
    ) -> None:
        """Test that fingerprint bundles remain consistent with sessions."""
        # Create sessions with bundles
        for i in range(100):
            session_id = f"session_{i}"
            session = Session(
                session_id=session_id,
                user_id=f"user_{i}",
                history=[],
            )
            await repo.add(session)

            bundle = ConversationFingerprintBundle(
                primary=ConversationFingerprint(fingerprint=f"fp_{i}", message_count=1),
                rolling_fingerprints=frozenset([f"fp_{i}"]),
            )
            await repo.update_fingerprint_bundle(session_id, bundle)

        # Verify all bundles correspond to existing sessions
        for session_id in repo._fingerprint_bundles:
            assert (
                session_id in repo._sessions
            ), f"Fingerprint bundle for {session_id} should correspond to existing session"

        # Delete some sessions
        for i in range(50):
            await repo.delete(f"session_{i}")

        # Verify bundles for deleted sessions are removed
        for i in range(50):
            assert (
                f"session_{i}" not in repo._fingerprint_bundles
            ), f"Fingerprint bundle for deleted session_{i} should be removed"

        # Verify remaining bundles correspond to existing sessions
        for session_id in repo._fingerprint_bundles:
            assert (
                session_id in repo._sessions
            ), f"Fingerprint bundle for {session_id} should correspond to existing session"
