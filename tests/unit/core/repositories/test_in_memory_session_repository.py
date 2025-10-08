"""
Tests for InMemorySessionRepository.

This module tests the in-memory session repository implementation.
"""

from datetime import datetime, timedelta, timezone

import pytest
from src.core.domain.configuration.backend_config import BackendConfiguration
from src.core.domain.configuration.loop_detection_config import (
    LoopDetectionConfiguration,
)
from src.core.domain.configuration.reasoning_config import ReasoningConfiguration
from src.core.domain.session import Session, SessionState
from src.core.repositories.session_repository import InMemorySessionRepository


class MockSessionWithUser(Session):
    """Mock Session class that includes user_id for testing."""

    def __init__(
        self,
        session_id: str,
        user_id: str | None = None,
        state: SessionState | None = None,
        created_at: datetime | None = None,
        last_active_at: datetime | None = None,
        agent: str | None = None,
    ):
        super().__init__(session_id, state, None, created_at, last_active_at, agent)
        self.user_id = user_id


class TestInMemorySessionRepository:
    """Tests for InMemorySessionRepository class."""

    @pytest.fixture
    def repository(self) -> InMemorySessionRepository:
        """Create a fresh InMemorySessionRepository for each test."""
        return InMemorySessionRepository()

    @pytest.fixture
    def sample_session(self) -> MockSessionWithUser:
        """Create a sample session for testing."""
        backend_config = BackendConfiguration(backend_type="openai", model="gpt-4")
        reasoning_config = ReasoningConfiguration(temperature=0.7)
        loop_config = LoopDetectionConfiguration()

        session_state = SessionState(
            backend_config=backend_config,
            reasoning_config=reasoning_config,
            loop_config=loop_config,
            project="test-project",
            project_dir="/test/path",
        )

        return MockSessionWithUser(
            session_id="test-session-123", user_id="user-456", state=session_state
        )

    @pytest.fixture
    def sample_session_no_user(self) -> Session:
        """Create a sample session without a user ID."""
        backend_config = BackendConfiguration(
            backend_type="anthropic", model="claude-3"
        )
        reasoning_config = ReasoningConfiguration(temperature=0.5)
        loop_config = LoopDetectionConfiguration()

        session_state = SessionState(
            backend_config=backend_config,
            reasoning_config=reasoning_config,
            loop_config=loop_config,
        )

        return Session(session_id="test-session-no-user", state=session_state)

    def test_initialization(self, repository: InMemorySessionRepository) -> None:
        """Test repository initialization."""
        assert repository._sessions == {}
        assert repository._user_sessions == {}

    @pytest.mark.asyncio
    async def test_get_by_id_empty_repository(
        self, repository: InMemorySessionRepository
    ) -> None:
        """Test get_by_id on empty repository."""
        result = await repository.get_by_id("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_all_empty_repository(
        self, repository: InMemorySessionRepository
    ) -> None:
        """Test get_all on empty repository."""
        result = await repository.get_all()
        assert result == []

    @pytest.mark.asyncio
    async def test_add_session(
        self, repository: InMemorySessionRepository, sample_session: Session
    ) -> None:
        """Test adding a session."""
        result = await repository.add(sample_session)

        assert result is sample_session
        assert sample_session.session_id in repository._sessions
        assert repository._sessions[sample_session.session_id] is sample_session

        # Check user tracking
        assert "user-456" in repository._user_sessions
        assert sample_session.session_id in repository._user_sessions["user-456"]

    @pytest.mark.asyncio
    async def test_add_session_without_user_id(
        self, repository: InMemorySessionRepository, sample_session_no_user: Session
    ) -> None:
        """Test adding a session without user ID."""
        result = await repository.add(sample_session_no_user)

        assert result is sample_session_no_user
        assert sample_session_no_user.session_id in repository._sessions

        # Should not create user tracking for sessions without user_id
        assert repository._user_sessions == {}

    @pytest.mark.asyncio
    async def test_get_by_id_existing_session(
        self, repository: InMemorySessionRepository, sample_session: Session
    ) -> None:
        """Test get_by_id for existing session."""
        await repository.add(sample_session)

        result = await repository.get_by_id(sample_session.session_id)
        assert result is sample_session

    @pytest.mark.asyncio
    async def test_get_all_with_sessions(
        self,
        repository: InMemorySessionRepository,
        sample_session: Session,
        sample_session_no_user: Session,
    ) -> None:
        """Test get_all with multiple sessions."""
        await repository.add(sample_session)
        await repository.add(sample_session_no_user)

        result = await repository.get_all()
        assert len(result) == 2
        assert sample_session in result
        assert sample_session_no_user in result

    @pytest.mark.asyncio
    async def test_update_existing_session(
        self, repository: InMemorySessionRepository, sample_session: Session
    ) -> None:
        """Test updating an existing session."""
        await repository.add(sample_session)

        # Modify the session
        sample_session.last_active_at = datetime.now(timezone.utc)
        result = await repository.update(sample_session)

        assert result is sample_session
        assert repository._sessions[sample_session.session_id] is sample_session

    @pytest.mark.asyncio
    async def test_update_session_changes_user_tracking(
        self, repository: InMemorySessionRepository, sample_session: MockSessionWithUser
    ) -> None:
        """Updating a session with a new user should update tracking tables."""
        await repository.add(sample_session)

        sample_session.user_id = "user-789"
        await repository.update(sample_session)

        assert sample_session.session_id not in repository._user_sessions.get(
            "user-456", []
        )
        assert repository._user_sessions.get("user-789") == [sample_session.session_id]

    @pytest.mark.asyncio
    async def test_update_session_removes_user_tracking_when_user_cleared(
        self, repository: InMemorySessionRepository, sample_session: MockSessionWithUser
    ) -> None:
        """Clearing the user_id should remove the session from user tracking."""
        await repository.add(sample_session)

        sample_session.user_id = None
        await repository.update(sample_session)

        assert sample_session.session_id not in repository._user_sessions.get(
            "user-456", []
        )
        assert all(
            sample_session.session_id not in sessions
            for sessions in repository._user_sessions.values()
        )

    @pytest.mark.asyncio
    async def test_update_nonexistent_session(
        self, repository: InMemorySessionRepository, sample_session: Session
    ) -> None:
        """Test updating a nonexistent session (should add it)."""
        result = await repository.update(sample_session)

        assert result is sample_session
        assert sample_session.session_id in repository._sessions

    @pytest.mark.asyncio
    async def test_delete_existing_session(
        self, repository: InMemorySessionRepository, sample_session: Session
    ) -> None:
        """Test deleting an existing session."""
        await repository.add(sample_session)

        result = await repository.delete(sample_session.session_id)
        assert result is True
        assert sample_session.session_id not in repository._sessions

        # Check user tracking cleanup
        assert sample_session.session_id not in repository._user_sessions["user-456"]

    @pytest.mark.asyncio
    async def test_delete_nonexistent_session(
        self, repository: InMemorySessionRepository
    ) -> None:
        """Test deleting a nonexistent session."""
        result = await repository.delete("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_get_by_user_id_existing_user(
        self,
        repository: InMemorySessionRepository,
        sample_session: Session,
        sample_session_no_user: Session,
    ) -> None:
        """Test get_by_user_id for existing user."""
        await repository.add(sample_session)
        await repository.add(sample_session_no_user)

        # Create another session for the same user
        session2 = MockSessionWithUser(
            session_id="test-session-789",
            user_id="user-456",
            state=sample_session.state,
        )
        await repository.add(session2)

        result = await repository.get_by_user_id("user-456")
        assert len(result) == 2
        assert sample_session in result
        assert session2 in result

    @pytest.mark.asyncio
    async def test_get_by_user_id_nonexistent_user(
        self, repository: InMemorySessionRepository
    ) -> None:
        """Test get_by_user_id for nonexistent user."""
        result = await repository.get_by_user_id("nonexistent")
        assert result == []

    @pytest.mark.asyncio
    async def test_cleanup_expired_sessions(
        self, repository: InMemorySessionRepository, sample_session: Session
    ) -> None:
        """Test cleanup_expired functionality."""
        # Add a session
        await repository.add(sample_session)

        # Create an expired session
        expired_session = MockSessionWithUser(
            session_id="expired-session", user_id="user-456", state=sample_session.state
        )
        expired_session.last_active_at = datetime.now(timezone.utc) - timedelta(
            seconds=1000
        )
        await repository.add(expired_session)

        # Clean up sessions older than 500 seconds
        deleted_count = await repository.cleanup_expired(500)

        assert deleted_count == 1
        assert expired_session.session_id not in repository._sessions
        assert sample_session.session_id in repository._sessions

    @pytest.mark.asyncio
    async def test_cleanup_handles_naive_last_active_timestamp(
        self, repository: InMemorySessionRepository, sample_session: Session
    ) -> None:
        """Ensure cleanup_expired handles sessions with naive timestamps."""

        await repository.add(sample_session)

        naive_session = MockSessionWithUser(
            session_id="naive-session",
            user_id="user-789",
            state=sample_session.state,
        )
        naive_session.last_active_at = datetime.now() - timedelta(seconds=1000)
        await repository.add(naive_session)

        deleted_count = await repository.cleanup_expired(500)

        assert deleted_count == 1
        assert naive_session.session_id not in repository._sessions
        assert sample_session.session_id in repository._sessions

    @pytest.mark.asyncio
    async def test_cleanup_no_expired_sessions(
        self, repository: InMemorySessionRepository, sample_session: Session
    ) -> None:
        """Test cleanup_expired when no sessions are expired."""
        await repository.add(sample_session)

        # Clean up sessions older than 1 hour (should not affect our session)
        deleted_count = await repository.cleanup_expired(3600)

        assert deleted_count == 0
        assert sample_session.session_id in repository._sessions

    @pytest.mark.asyncio
    async def test_multiple_sessions_same_user(
        self, repository: InMemorySessionRepository, sample_session: Session
    ) -> None:
        """Test multiple sessions for the same user."""
        await repository.add(sample_session)

        # Add another session for the same user
        session2 = MockSessionWithUser(
            session_id="session-2", user_id="user-456", state=sample_session.state
        )
        await repository.add(session2)

        # Verify both sessions are tracked
        user_sessions = await repository.get_by_user_id("user-456")
        assert len(user_sessions) == 2

        # Delete one session
        await repository.delete(sample_session.session_id)

        # Verify only one session remains for the user
        user_sessions = await repository.get_by_user_id("user-456")
        assert len(user_sessions) == 1
        assert user_sessions[0].session_id == "session-2"

    @pytest.mark.asyncio
    async def test_session_without_user_id_not_tracked(
        self, repository: InMemorySessionRepository, sample_session_no_user: Session
    ) -> None:
        """Test that sessions without user_id are not tracked by user."""
        await repository.add(sample_session_no_user)

        # Should not appear in any user queries
        for user_id in repository._user_sessions:
            assert (
                sample_session_no_user.session_id
                not in repository._user_sessions[user_id]
            )

        # Should still be retrievable by ID
        result = await repository.get_by_user_id("any-user")
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_user_tracking_cleanup_on_delete(
        self, repository: InMemorySessionRepository, sample_session: Session
    ) -> None:
        """Test that user tracking is cleaned up when session is deleted."""
        await repository.add(sample_session)

        # Verify user tracking exists
        assert "user-456" in repository._user_sessions
        assert sample_session.session_id in repository._user_sessions["user-456"]

        # Delete the session
        await repository.delete(sample_session.session_id)

        # Verify user tracking is cleaned up
        assert sample_session.session_id not in repository._user_sessions["user-456"]

    @pytest.mark.asyncio
    async def test_get_all_returns_copy(
        self, repository: InMemorySessionRepository, sample_session: Session
    ) -> None:
        """Test that get_all returns a copy of the sessions list."""
        await repository.add(sample_session)

        result1 = await repository.get_all()
        result2 = await repository.get_all()

        # Should be different list objects
        assert result1 is not result2
        # But should contain the same sessions
        assert result1 == result2

    @pytest.mark.asyncio
    async def test_empty_repository_operations(
        self, repository: InMemorySessionRepository
    ) -> None:
        """Test various operations on an empty repository."""
        # All operations should work without errors
        assert await repository.get_all() == []
        assert await repository.get_by_id("any") is None
        assert await repository.delete("any") is False
        assert await repository.get_by_user_id("any") == []
        assert await repository.cleanup_expired(0) == 0
