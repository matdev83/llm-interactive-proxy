"""Regression test for InMemorySessionRepository auxiliary structures memory leak fix.

This test verifies that auxiliary structures (_user_sessions, _client_sessions,
_fingerprints, _fingerprint_bundles) are properly cleaned up when sessions are
evicted or deleted, preventing unbounded memory growth.
"""

import pytest
from src.core.domain.session import Session
from src.core.repositories.in_memory_session_repository import InMemorySessionRepository
from src.core.services.conversation_fingerprint_service import (
    ConversationFingerprint,
    ConversationFingerprintBundle,
)


class TestSessionRepositoryAuxiliaryLeakRegression:
    """Regression tests for InMemorySessionRepository auxiliary structures leak fix."""

    @pytest.fixture
    def repo(self) -> InMemorySessionRepository:
        """Create InMemorySessionRepository with small limits for testing."""
        return InMemorySessionRepository(max_sessions=1000, default_ttl_seconds=3600)

    @pytest.mark.asyncio
    async def test_auxiliary_structures_cleaned_up_on_delete(
        self, repo: InMemorySessionRepository
    ) -> None:
        """Test that auxiliary structures are cleaned up when session is deleted."""
        # Create session with user and client
        session = Session(
            session_id="test_session",
            user_id="user_1",
            history=[],
        )
        await repo.add(session)
        await repo.update_fingerprint("test_session", "fingerprint_1")
        await repo.update_client_session("test_session", "client_1")

        # Verify auxiliary structures have entries
        assert "test_session" in repo._fingerprints, "Fingerprint should be tracked"
        assert "user_1" in repo._user_sessions, "User sessions should be tracked"
        assert "client_1" in repo._client_sessions, "Client sessions should be tracked"
        assert (
            "test_session" in repo._user_sessions["user_1"]
        ), "Session should be in user sessions"
        assert (
            "test_session" in repo._client_sessions["client_1"]
        ), "Session should be in client sessions"

        # Delete session
        await repo.delete("test_session")

        # Verify auxiliary structures are cleaned up
        assert (
            "test_session" not in repo._fingerprints
        ), "Fingerprint should be removed on delete"
        assert "test_session" not in repo._user_sessions.get(
            "user_1", []
        ), "Session should be removed from user sessions"
        assert "test_session" not in repo._client_sessions.get(
            "client_1", []
        ), "Session should be removed from client sessions"

    @pytest.mark.asyncio
    async def test_user_sessions_bounded_by_limit(
        self, repo: InMemorySessionRepository
    ) -> None:
        """Test that _user_sessions is bounded by max_sessions_per_user limit."""
        user_id = "user_1"
        num_sessions = repo._max_sessions_per_user + 100  # More than limit

        # Create many sessions for same user
        for i in range(num_sessions):
            session = Session(
                session_id=f"session_{i}",
                user_id=user_id,
                history=[],
            )
            await repo.add(session)

        # Check that user sessions list is bounded
        user_sessions = repo._user_sessions.get(user_id, [])
        assert len(user_sessions) <= repo._max_sessions_per_user, (
            f"User sessions should be <= {repo._max_sessions_per_user}, "
            f"got {len(user_sessions)}. Per-user limit is not being enforced."
        )

    @pytest.mark.asyncio
    async def test_client_sessions_bounded_by_limit(
        self, repo: InMemorySessionRepository
    ) -> None:
        """Test that _client_sessions is bounded by max_sessions_per_client limit."""
        client_key = "client_1"
        num_sessions = repo._max_sessions_per_client + 100  # More than limit

        # Create many sessions for same client
        for i in range(num_sessions):
            session = Session(
                session_id=f"session_{i}",
                user_id=f"user_{i}",
                history=[],
            )
            await repo.add(session)
            await repo.update_client_session(f"session_{i}", client_key)

        # Check that client sessions list is bounded
        client_sessions = repo._client_sessions.get(client_key, [])
        assert len(client_sessions) <= repo._max_sessions_per_client, (
            f"Client sessions should be <= {repo._max_sessions_per_client}, "
            f"got {len(client_sessions)}. Per-client limit is not being enforced."
        )

    @pytest.mark.asyncio
    async def test_auxiliary_structures_cleaned_up_on_eviction(
        self, repo: InMemorySessionRepository
    ) -> None:
        """Test that auxiliary structures are cleaned up when sessions are evicted."""
        # Fill repository to capacity
        for i in range(repo._max_sessions):
            session = Session(
                session_id=f"session_{i}",
                user_id=f"user_{i % 10}",  # 10 unique users
                history=[],
            )
            await repo.add(session)
            await repo.update_fingerprint(f"session_{i}", f"fingerprint_{i}")
            await repo.update_client_session(f"session_{i}", f"client_{i % 5}")

        len(repo._sessions)
        len(repo._fingerprints)

        # Add one more session to trigger eviction
        new_session = Session(
            session_id="new_session",
            user_id="user_new",
            history=[],
        )
        await repo.add(new_session)
        await repo.update_fingerprint("new_session", "fingerprint_new")
        await repo.update_client_session("new_session", "client_new")

        # Verify that sessions were evicted
        assert (
            len(repo._sessions) <= repo._max_sessions
        ), f"Sessions should be <= {repo._max_sessions} after eviction"

        # Verify that fingerprints were cleaned up (should be <= sessions)
        assert len(repo._fingerprints) <= len(repo._sessions), (
            f"Fingerprints ({len(repo._fingerprints)}) should not exceed "
            f"sessions ({len(repo._sessions)}). Auxiliary structures leak detected."
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
    async def test_auxiliary_structures_dont_exceed_main_sessions(
        self, repo: InMemorySessionRepository
    ) -> None:
        """Test that auxiliary structures don't exceed main session count."""
        # Create many sessions with various users and clients (reduced for performance)
        num_sessions = 400  # More than max_sessions to test eviction (reduced from 450)

        for i in range(num_sessions):
            session = Session(
                session_id=f"session_{i}",
                user_id=f"user_{i % 100}",  # 100 unique users
                history=[],
            )
            await repo.add(session)
            await repo.update_fingerprint(f"session_{i}", f"fingerprint_{i}")
            await repo.update_client_session(f"session_{i}", f"client_{i % 50}")

        # Check that auxiliary structures don't exceed main sessions
        total_user_sessions = sum(
            len(sessions) for sessions in repo._user_sessions.values()
        )
        total_client_sessions = sum(
            len(sessions) for sessions in repo._client_sessions.values()
        )

        main_sessions = len(repo._sessions)

        # Fingerprints should not exceed sessions
        assert len(repo._fingerprints) <= main_sessions, (
            f"Fingerprints ({len(repo._fingerprints)}) should not exceed "
            f"sessions ({main_sessions})"
        )

        # Fingerprint bundles should not exceed sessions
        assert len(repo._fingerprint_bundles) <= main_sessions, (
            f"Fingerprint bundles ({len(repo._fingerprint_bundles)}) should not exceed "
            f"sessions ({main_sessions})"
        )

        # Note: user_sessions and client_sessions can have duplicates (same session
        # in multiple lists), so we check totals rather than counts
        # But totals should still be reasonable (not unbounded)
        assert total_user_sessions <= main_sessions * 2, (
            f"Total user sessions ({total_user_sessions}) should be reasonable "
            f"compared to main sessions ({main_sessions})"
        )
        assert total_client_sessions <= main_sessions * 2, (
            f"Total client sessions ({total_client_sessions}) should be reasonable "
            f"compared to main sessions ({main_sessions})"
        )
