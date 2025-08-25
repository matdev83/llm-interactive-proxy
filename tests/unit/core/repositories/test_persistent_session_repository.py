"""
Tests for PersistentSessionRepository.

This module tests the persistent session repository implementation.
"""

from datetime import datetime, timedelta, timezone

import pytest
from src.core.domain.configuration.backend_config import BackendConfiguration
from src.core.domain.configuration.loop_detection_config import (
    LoopDetectionConfiguration,
)
from src.core.domain.configuration.reasoning_config import ReasoningConfiguration
from src.core.domain.session import Session, SessionState
from src.core.repositories.session_repository import PersistentSessionRepository


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


class TestPersistentSessionRepository:
    """Tests for PersistentSessionRepository class."""

    @pytest.fixture
    def repository(self) -> PersistentSessionRepository:
        """Create a fresh PersistentSessionRepository for each test."""
        return PersistentSessionRepository()

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
            session_id="test-session-123",
            user_id="user-456",
            state=session_state,
        )

    def test_initialization(self, repository: PersistentSessionRepository) -> None:
        """Test repository initialization."""
        assert repository._memory_repo is not None
        assert repository._storage_path is None  # No storage path provided

    def test_initialization_with_storage_path(self) -> None:
        """Test repository initialization with storage path."""
        storage_path = "/tmp/sessions"
        repository = PersistentSessionRepository(storage_path)

        assert repository._memory_repo is not None
        assert repository._storage_path == storage_path

    @pytest.mark.asyncio
    async def test_get_by_id_delegates_to_memory_repo(
        self, repository: PersistentSessionRepository, sample_session: Session
    ) -> None:
        """Test that get_by_id delegates to the in-memory repository."""
        # Add to the underlying memory repo
        await repository._memory_repo.add(sample_session)

        # Should find it through the persistent repo
        result = await repository.get_by_id(sample_session.session_id)
        assert result is sample_session

    @pytest.mark.asyncio
    async def test_get_by_id_nonexistent(
        self, repository: PersistentSessionRepository
    ) -> None:
        """Test get_by_id for nonexistent session."""
        result = await repository.get_by_id("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_all_delegates_to_memory_repo(
        self, repository: PersistentSessionRepository, sample_session: Session
    ) -> None:
        """Test that get_all delegates to the in-memory repository."""
        await repository._memory_repo.add(sample_session)

        result = await repository.get_all()
        assert len(result) == 1
        assert result[0] is sample_session

    @pytest.mark.asyncio
    async def test_add_delegates_to_memory_repo(
        self, repository: PersistentSessionRepository, sample_session: Session
    ) -> None:
        """Test that add delegates to the in-memory repository."""
        result = await repository.add(sample_session)

        assert result is sample_session
        assert sample_session.session_id in repository._memory_repo._sessions

    @pytest.mark.asyncio
    async def test_update_delegates_to_memory_repo(
        self, repository: PersistentSessionRepository, sample_session: Session
    ) -> None:
        """Test that update delegates to the in-memory repository."""
        await repository.add(sample_session)

        # Modify the session
        sample_session.last_active_at = datetime.now(timezone.utc)
        result = await repository.update(sample_session)

        assert result is sample_session
        assert repository._memory_repo._sessions[sample_session.session_id] is sample_session

    @pytest.mark.asyncio
    async def test_delete_delegates_to_memory_repo(
        self, repository: PersistentSessionRepository, sample_session: Session
    ) -> None:
        """Test that delete delegates to the in-memory repository."""
        await repository.add(sample_session)

        result = await repository.delete(sample_session.session_id)
        assert result is True
        assert sample_session.session_id not in repository._memory_repo._sessions

    @pytest.mark.asyncio
    async def test_get_by_user_id_delegates_to_memory_repo(
        self, repository: PersistentSessionRepository, sample_session: Session
    ) -> None:
        """Test that get_by_user_id delegates to the in-memory repository."""
        await repository.add(sample_session)

        result = await repository.get_by_user_id("user-456")
        assert len(result) == 1
        assert result[0] is sample_session

    @pytest.mark.asyncio
    async def test_cleanup_expired_delegates_to_memory_repo(
        self, repository: PersistentSessionRepository, sample_session: Session
    ) -> None:
        """Test that cleanup_expired delegates to the in-memory repository."""
        await repository.add(sample_session)

        # Create an expired session
        expired_session = MockSessionWithUser(
            session_id="expired-session",
            user_id="user-456",
            state=sample_session.state,
        )
        expired_session.last_active_at = datetime.now(timezone.utc) - timedelta(seconds=1000)
        await repository._memory_repo.add(expired_session)

        # Clean up sessions older than 500 seconds
        deleted_count = await repository.cleanup_expired(500)

        assert deleted_count == 1
        assert expired_session.session_id not in repository._memory_repo._sessions
        assert sample_session.session_id in repository._memory_repo._sessions

    @pytest.mark.asyncio
    async def test_persistent_repo_caches_in_memory(
        self, repository: PersistentSessionRepository, sample_session: Session
    ) -> None:
        """Test that the persistent repo uses the in-memory repo as cache."""
        # Add through persistent repo
        await repository.add(sample_session)

        # Should be available through memory repo
        memory_result = await repository._memory_repo.get_by_id(sample_session.session_id)
        assert memory_result is sample_session

        # Should also be available through persistent repo
        persistent_result = await repository.get_by_id(sample_session.session_id)
        assert persistent_result is sample_session

    @pytest.mark.asyncio
    async def test_multiple_operations_work_consistently(
        self, repository: PersistentSessionRepository, sample_session: Session
    ) -> None:
        """Test that multiple operations work consistently."""
        # Add session
        await repository.add(sample_session)

        # Verify it exists
        assert await repository.get_by_id(sample_session.session_id) is not None

        # Update session
        sample_session.last_active_at = datetime.now(timezone.utc)
        await repository.update(sample_session)

        # Verify update worked
        updated = await repository.get_by_id(sample_session.session_id)
        assert updated is sample_session

        # Delete session
        await repository.delete(sample_session.session_id)

        # Verify it's gone
        assert await repository.get_by_id(sample_session.session_id) is None

    @pytest.mark.asyncio
    async def test_empty_repository_operations(
        self, repository: PersistentSessionRepository
    ) -> None:
        """Test various operations on an empty repository."""
        # All operations should work without errors
        assert await repository.get_all() == []
        assert await repository.get_by_id("any") is None
        assert await repository.delete("any") is False
        assert await repository.get_by_user_id("any") == []
        assert await repository.cleanup_expired(0) == 0

    @pytest.mark.asyncio
    async def test_storage_path_is_stored(
        self, sample_session: Session
    ) -> None:
        """Test that storage path is properly stored."""
        storage_path = "/custom/storage/path"
        repository = PersistentSessionRepository(storage_path)

        assert repository._storage_path == storage_path

        # Repository should still function normally
        await repository.add(sample_session)
        result = await repository.get_by_id(sample_session.session_id)
        assert result is sample_session

    @pytest.mark.asyncio
    async def test_none_storage_path_works(
        self, sample_session: Session
    ) -> None:
        """Test that None storage path works (no persistence)."""
        repository = PersistentSessionRepository(None)

        assert repository._storage_path is None

        # Repository should still function normally
        await repository.add(sample_session)
        result = await repository.get_by_id(sample_session.session_id)
        assert result is sample_session

    @pytest.mark.asyncio
    async def test_user_sessions_are_tracked_properly(
        self, repository: PersistentSessionRepository, sample_session: Session
    ) -> None:
        """Test that user session tracking works properly."""
        await repository.add(sample_session)

        # Check user tracking through memory repo
        user_sessions = await repository.get_by_user_id("user-456")
        assert len(user_sessions) == 1
        assert user_sessions[0] is sample_session

        # Add another session for the same user
        session2 = MockSessionWithUser(
            session_id="session-2",
            user_id="user-456",
            state=sample_session.state,
        )
        await repository.add(session2)

        # Should now have 2 sessions for the user
        user_sessions = await repository.get_by_user_id("user-456")
        assert len(user_sessions) == 2
        assert sample_session in user_sessions
        assert session2 in user_sessions

    @pytest.mark.asyncio
    async def test_session_without_user_id_not_tracked(
        self, repository: PersistentSessionRepository
    ) -> None:
        """Test that sessions without user_id are not tracked by user."""
        backend_config = BackendConfiguration(backend_type="anthropic", model="claude-3")
        reasoning_config = ReasoningConfiguration(temperature=0.5)
        loop_config = LoopDetectionConfiguration()

        session_state = SessionState(
            backend_config=backend_config,
            reasoning_config=reasoning_config,
            loop_config=loop_config,
        )

        session_no_user = Session(
            session_id="session-no-user",
            state=session_state,
        )

        await repository.add(session_no_user)

        # Should not appear in user queries
        user_sessions = await repository.get_by_user_id("any-user")
        assert len(user_sessions) == 0

        # But should still be retrievable by ID
        result = await repository.get_by_id("session-no-user")
        assert result is session_no_user

    @pytest.mark.asyncio
    async def test_repository_state_consistency(
        self, repository: PersistentSessionRepository, sample_session: Session
    ) -> None:
        """Test that repository state remains consistent after operations."""
        initial_memory_sessions = len(repository._memory_repo._sessions)

        # Add session
        await repository.add(sample_session)
        assert len(repository._memory_repo._sessions) == initial_memory_sessions + 1

        # Get session (should not change state)
        await repository.get_by_id(sample_session.session_id)
        assert len(repository._memory_repo._sessions) == initial_memory_sessions + 1

        # Delete session
        await repository.delete(sample_session.session_id)
        assert len(repository._memory_repo._sessions) == initial_memory_sessions
