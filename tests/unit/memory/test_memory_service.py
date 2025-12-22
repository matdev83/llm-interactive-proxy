"""Unit tests for MemoryService."""

from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest
from src.core.memory.config import MemoryConfiguration
from src.core.memory.models import CapturedInteraction
from src.core.memory.service import MemoryService
from src.core.memory.sqlite_repository import MemoryRepository


def create_interaction(
    content: str = "Test", role: str = "user"
) -> CapturedInteraction:
    """Create a test CapturedInteraction."""
    return CapturedInteraction(
        role=role,
        content=content,
        timestamp=datetime.now(timezone.utc),
    )


class TestMemoryService:
    """Tests for MemoryService."""

    @pytest.fixture
    def temp_db_path(self) -> Path:
        """Create a temporary database path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir) / "test_memory.sqlite3"

    @pytest.fixture
    def config(self, temp_db_path: Path) -> MemoryConfiguration:
        """Create test configuration."""
        return MemoryConfiguration(
            available=True,
            database_path=str(temp_db_path),
            require_project_discovery=False,
            summarization_delay_seconds=0,  # Immediate queue for tests
        )

    @pytest.fixture
    def disabled_config(self, temp_db_path: Path) -> MemoryConfiguration:
        """Create disabled configuration."""
        return MemoryConfiguration(
            available=False,
            database_path=str(temp_db_path),
            require_project_discovery=False,
        )

    @pytest.fixture
    async def repository(self, config: MemoryConfiguration) -> MemoryRepository:
        """Create repository instance."""
        repo = MemoryRepository(config)
        yield repo
        await repo.close()

    @pytest.fixture
    def service(
        self, config: MemoryConfiguration, repository: MemoryRepository
    ) -> MemoryService:
        """Create service instance."""
        return MemoryService(config, repository)

    @pytest.mark.asyncio
    async def test_is_available_when_enabled(self, service: MemoryService) -> None:
        """Test is_available returns True when enabled."""
        assert service.is_available() is True

    @pytest.mark.asyncio
    async def test_is_available_when_disabled(
        self, disabled_config: MemoryConfiguration, repository: MemoryRepository
    ) -> None:
        """Test is_available returns False when disabled."""
        service = MemoryService(disabled_config, repository)
        assert service.is_available() is False

    @pytest.mark.asyncio
    async def test_enable_for_session(self, service: MemoryService) -> None:
        """Test enabling memory for a session."""
        result = await service.enable_for_session(
            "sess-1", "user-1", project_root="/home/user/project"
        )
        assert result is True
        assert await service.is_enabled_for_session("sess-1") is True

    @pytest.mark.asyncio
    async def test_enable_fails_when_disabled(
        self, disabled_config: MemoryConfiguration, repository: MemoryRepository
    ) -> None:
        """Test enable fails when memory is globally disabled."""
        service = MemoryService(disabled_config, repository)
        result = await service.enable_for_session("sess-1", "user-1")
        assert result is False
        assert await service.is_enabled_for_session("sess-1") is False

    @pytest.mark.asyncio
    async def test_enable_fails_for_denied_user(self, temp_db_path: Path) -> None:
        """Test enable fails for users in deny list."""
        config = MemoryConfiguration(
            available=True,
            database_path=str(temp_db_path),
            disabled_users=["blocked-user"],
            require_project_discovery=False,
        )
        repo = MemoryRepository(config)
        service = MemoryService(config, repo)

        result = await service.enable_for_session("sess-1", "blocked-user")
        assert result is False

    @pytest.mark.asyncio
    async def test_enable_fails_for_denied_client(self, temp_db_path: Path) -> None:
        """Test enable fails for clients in deny list."""
        config = MemoryConfiguration(
            available=True,
            database_path=str(temp_db_path),
            disabled_clients=["blocked-client"],
            require_project_discovery=False,
        )
        repo = MemoryRepository(config)
        service = MemoryService(config, repo)

        result = await service.enable_for_session(
            "sess-1", "user-1", client_id="blocked-client"
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_enable_fails_without_user_in_multiuser_mode(
        self, service: MemoryService
    ) -> None:
        """Test enable fails without user_id in multi-user mode."""
        result = await service.enable_for_session("sess-1", "")
        assert result is False

    @pytest.mark.asyncio
    async def test_enable_succeeds_in_single_user_mode(
        self, temp_db_path: Path
    ) -> None:
        """Test enable succeeds without explicit user in single-user mode."""
        config = MemoryConfiguration(
            available=True,
            database_path=str(temp_db_path),
            single_user_mode=True,
            fixed_user_id="local-user",
            require_project_discovery=False,
        )
        repo = MemoryRepository(config)
        service = MemoryService(config, repo)

        result = await service.enable_for_session("sess-1", "")
        assert result is True

    @pytest.mark.asyncio
    async def test_disable_for_session(self, service: MemoryService) -> None:
        """Test disabling memory for a session."""
        await service.enable_for_session("sess-1", "user-1")
        assert await service.is_enabled_for_session("sess-1") is True

        await service.disable_for_session("sess-1")
        assert await service.is_enabled_for_session("sess-1") is False

    @pytest.mark.asyncio
    async def test_capture_interaction(self, service: MemoryService) -> None:
        """Test capturing an interaction."""
        await service.enable_for_session("sess-1", "user-1")

        interaction = create_interaction(content="Hello")
        result = await service.capture_interaction("sess-1", interaction)
        assert result is True

    @pytest.mark.asyncio
    async def test_capture_fails_for_disabled_session(
        self, service: MemoryService
    ) -> None:
        """Test capture fails for non-enabled session."""
        interaction = create_interaction()
        result = await service.capture_interaction("nonexistent", interaction)
        assert result is False

    @pytest.mark.asyncio
    async def test_mark_session_complete(self, service: MemoryService) -> None:
        """Test marking a session as complete."""
        await service.enable_for_session("sess-1", "user-1")

        result = await service.mark_session_complete(
            "sess-1", backend_model="openai:gpt-4o"
        )
        assert result is True
        assert service.get_analysis_queue_size() == 1

    @pytest.mark.asyncio
    async def test_mark_complete_fails_for_disabled_session(
        self, service: MemoryService
    ) -> None:
        """Test mark complete fails for non-enabled session."""
        result = await service.mark_session_complete("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_mark_complete_prevents_double_queue(
        self, service: MemoryService
    ) -> None:
        """Test that a session can only be queued once."""
        await service.enable_for_session("sess-1", "user-1")

        result1 = await service.mark_session_complete("sess-1")
        result2 = await service.mark_session_complete("sess-1")

        assert result1 is True
        assert result2 is False
        assert service.get_analysis_queue_size() == 1

    @pytest.mark.asyncio
    async def test_mark_session_complete_with_termination_reason(
        self, service: MemoryService
    ) -> None:
        """Test marking a session as complete with termination reason."""
        await service.enable_for_session("sess-1", "user-1")

        result = await service.mark_session_complete(
            "sess-1",
            backend_model="openai:gpt-4o",
            termination_reason="client_disconnected",
        )
        assert result is True
        assert service.get_analysis_queue_size() == 1

    @pytest.mark.asyncio
    async def test_get_session_user_id(self, service: MemoryService) -> None:
        """Test getting user ID for a session."""
        await service.enable_for_session("sess-1", "user-123")

        user_id = await service.get_session_user_id("sess-1")
        assert user_id == "user-123"

        user_id_none = await service.get_session_user_id("nonexistent")
        assert user_id_none is None

    @pytest.mark.asyncio
    async def test_get_session_project_root(self, service: MemoryService) -> None:
        """Test getting project root for a session."""
        await service.enable_for_session(
            "sess-1", "user-1", project_root="/home/user/project"
        )

        project_root = await service.get_session_project_root("sess-1")
        assert project_root == "/home/user/project"

    @pytest.mark.asyncio
    async def test_get_captured_interactions(self, service: MemoryService) -> None:
        """Test getting captured interactions."""
        await service.enable_for_session("sess-1", "user-1")

        for i in range(3):
            interaction = create_interaction(content=f"Message {i}")
            await service.capture_interaction("sess-1", interaction)

        interactions, is_partial = await service.get_captured_interactions("sess-1")
        assert len(interactions) == 3
        assert is_partial is False

    @pytest.mark.asyncio
    async def test_get_pending_analysis_session(self, service: MemoryService) -> None:
        """Test getting pending analysis sessions."""
        await service.enable_for_session("sess-1", "user-1")
        await service.mark_session_complete("sess-1")

        session_id = await service.get_pending_analysis_session()
        assert session_id == "sess-1"

        # Queue should be empty now
        session_id2 = await service.get_pending_analysis_session()
        assert session_id2 is None

    @pytest.mark.asyncio
    async def test_complete_analysis(self, service: MemoryService) -> None:
        """Test completing analysis for a session."""
        await service.enable_for_session("sess-1", "user-1")
        await service.mark_session_complete("sess-1")

        session_id = await service.get_pending_analysis_session()
        assert session_id == "sess-1"

        await service.complete_analysis("sess-1")
        assert await service.is_enabled_for_session("sess-1") is False

    @pytest.mark.asyncio
    async def test_session_isolation(self, service: MemoryService) -> None:
        """Test that sessions are isolated."""
        await service.enable_for_session("sess-1", "user-1")
        await service.enable_for_session("sess-2", "user-2")

        interaction1 = create_interaction(content="Session 1")
        interaction2 = create_interaction(content="Session 2")

        await service.capture_interaction("sess-1", interaction1)
        await service.capture_interaction("sess-2", interaction2)

        int1, _ = await service.get_captured_interactions("sess-1")
        int2, _ = await service.get_captured_interactions("sess-2")

        assert len(int1) == 1
        assert len(int2) == 1
        assert int1[0].content == "Session 1"
        assert int2[0].content == "Session 2"

    @pytest.mark.asyncio
    async def test_project_required_mode(self, temp_db_path: Path) -> None:
        """Test require_project_discovery enforcement."""
        config = MemoryConfiguration(
            available=True,
            database_path=str(temp_db_path),
            require_project_discovery=True,
        )
        repo = MemoryRepository(config)
        try:
            service = MemoryService(config, repo)

            # Should fail without project_root
            result1 = await service.enable_for_session("sess-1", "user-1")
            assert result1 is False

            # Should succeed with project_root
            result2 = await service.enable_for_session(
                "sess-2", "user-1", project_root="/home/user/project"
            )
            assert result2 is True
        finally:
            await repo.close()

    @pytest.mark.asyncio
    async def test_record_tool_event_file_edit(self, service: MemoryService) -> None:
        """Test recording a file edit tool event."""
        from src.core.memory.models import FileEditEvent

        await service.enable_for_session("sess-1", "user-1")

        event = FileEditEvent(
            path="src/test.py",
            action="modified",
            tool="apply_patch",
            timestamp=datetime.now(timezone.utc),
        )
        result = await service.record_tool_event("sess-1", event)
        assert result is True

        file_edits, git_commits = await service.get_captured_tool_events("sess-1")
        assert len(file_edits) == 1
        assert len(git_commits) == 0
        assert file_edits[0].path == "src/test.py"
        assert file_edits[0].action == "modified"

    @pytest.mark.asyncio
    async def test_record_tool_event_git_commit(self, service: MemoryService) -> None:
        """Test recording a git commit tool event."""
        from src.core.memory.models import GitCommitEvent

        await service.enable_for_session("sess-1", "user-1")

        event = GitCommitEvent(
            commit_hash="abc123def456",
            message="Fix bug",
            branch="main",
            timestamp=datetime.now(timezone.utc),
        )
        result = await service.record_tool_event("sess-1", event)
        assert result is True

        file_edits, git_commits = await service.get_captured_tool_events("sess-1")
        assert len(file_edits) == 0
        assert len(git_commits) == 1
        assert git_commits[0].commit_hash == "abc123def456"

    @pytest.mark.asyncio
    async def test_record_tool_event_fails_for_disabled_session(
        self, service: MemoryService
    ) -> None:
        """Test recording tool event fails for non-enabled session."""
        from src.core.memory.models import FileEditEvent

        event = FileEditEvent(
            path="test.py",
            action="created",
            timestamp=datetime.now(timezone.utc),
        )
        result = await service.record_tool_event("nonexistent", event)
        assert result is False

    @pytest.mark.asyncio
    async def test_tool_events_cleared_on_disable(self, service: MemoryService) -> None:
        """Test that tool events are cleared when session is disabled."""
        from src.core.memory.models import FileEditEvent

        await service.enable_for_session("sess-1", "user-1")

        event = FileEditEvent(
            path="test.py",
            action="created",
            timestamp=datetime.now(timezone.utc),
        )
        await service.record_tool_event("sess-1", event)

        await service.disable_for_session("sess-1")

        file_edits, git_commits = await service.get_captured_tool_events("sess-1")
        assert len(file_edits) == 0
        assert len(git_commits) == 0
