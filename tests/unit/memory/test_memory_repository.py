"""Unit tests for MemoryRepository SQLite implementation."""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from freezegun import freeze_time
from src.core.memory.config import MemoryConfiguration
from src.core.memory.models import (
    FileChange,
    GitOperation,
    SessionSummary,
    TaskItem,
    TestRun,
)
from src.core.memory.sqlite_repository import MemoryRepository


def create_test_summary(
    user_id: str = "test-user",
    session_id: str = "sess-123",
    tenant_id: str | None = None,
    project_id: str | None = None,
    project_root: str | None = None,
    session_start: datetime | None = None,
) -> SessionSummary:
    """Create a test SessionSummary."""
    with freeze_time("2024-01-01 12:00:00"):
        now = session_start or datetime.now(timezone.utc)
        return SessionSummary(
            id=f"sum-{session_id}",
            user_id=user_id,
            tenant_id=tenant_id,
            project_id=project_id,
            project_root=project_root,
            session_id=session_id,
            session_start=now,
            client_agent="test-agent",
            backend_model="openai:gpt-4o",
            title="Test session summary",
            scope="Unit testing",
            goals=["Test goal 1", "Test goal 2"],
            open_questions=["Question 1"],
            remaining_tasks=[
                TaskItem(description="Task 1", status="open"),
                TaskItem(description="Task 2", status="blocked"),
            ],
            modified_files=[
                FileChange(path="src/test.py", status="modified"),
                FileChange(path="src/new.py", status="created"),
            ],
            git_operations=[
                GitOperation(type="commit", ref="abc123", details="Test commit"),
            ],
            completion_status="completed",
            key_decisions=["Decision 1"],
            operations_performed=["pytest tests/"],
            tests_run=[
                TestRun(name="test_example", status="passed", command="pytest"),
            ],
            errors=[],
            risks_or_warnings=["Warning 1"],
            evidence=["Evidence 1"],
            full_analysis="<session_summary>Test</session_summary>",
            branch="main",
            head_sha="abc123def",
            summary_version="v1",
            created_at=now,
        )


class TestMemoryRepository:
    """Tests for MemoryRepository."""

    @pytest.fixture
    def temp_db_path(self) -> Path:
        """Create a temporary database path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir) / "test_memory.sqlite3"

    @pytest.fixture
    def config(self, temp_db_path: Path) -> MemoryConfiguration:
        """Create test configuration."""
        return MemoryConfiguration(database_path=str(temp_db_path))

    @pytest.fixture
    async def repository(self, config: MemoryConfiguration) -> MemoryRepository:
        """Create repository instance."""
        repo = MemoryRepository(config)
        yield repo
        await repo.close()

    @pytest.mark.asyncio
    async def test_initialize_schema(self, repository: MemoryRepository) -> None:
        """Test schema initialization."""
        await repository.initialize_schema()
        assert repository._initialized is True

    @pytest.mark.asyncio
    async def test_save_and_retrieve_summary(
        self, repository: MemoryRepository
    ) -> None:
        """Test saving and retrieving a summary."""
        await repository.initialize_schema()

        summary = create_test_summary()
        await repository.save_session_summary(summary)

        # Retrieve
        summaries = await repository.get_recent_sessions("test-user", limit=10)
        assert len(summaries) == 1

        retrieved = summaries[0]
        assert retrieved.id == summary.id
        assert retrieved.user_id == summary.user_id
        assert retrieved.session_id == summary.session_id
        assert retrieved.title == summary.title
        assert retrieved.completion_status == summary.completion_status
        assert len(retrieved.goals) == 2
        assert len(retrieved.remaining_tasks) == 2
        assert len(retrieved.modified_files) == 2
        assert len(retrieved.git_operations) == 1
        assert len(retrieved.tests_run) == 1

    @pytest.mark.asyncio
    async def test_user_isolation(self, repository: MemoryRepository) -> None:
        """Test that users can only see their own summaries."""
        await repository.initialize_schema()

        # Save summaries for different users
        summary1 = create_test_summary(user_id="user-1", session_id="sess-1")
        summary2 = create_test_summary(user_id="user-2", session_id="sess-2")

        await repository.save_session_summary(summary1)
        await repository.save_session_summary(summary2)

        # User 1 should only see their summary
        user1_summaries = await repository.get_recent_sessions("user-1", limit=10)
        assert len(user1_summaries) == 1
        assert user1_summaries[0].user_id == "user-1"

        # User 2 should only see their summary
        user2_summaries = await repository.get_recent_sessions("user-2", limit=10)
        assert len(user2_summaries) == 1
        assert user2_summaries[0].user_id == "user-2"

    @pytest.mark.asyncio
    async def test_tenant_filtering(self, repository: MemoryRepository) -> None:
        """Test filtering by tenant_id."""
        await repository.initialize_schema()

        summary1 = create_test_summary(
            user_id="user-1", session_id="sess-1", tenant_id="tenant-a"
        )
        summary2 = create_test_summary(
            user_id="user-1", session_id="sess-2", tenant_id="tenant-b"
        )

        await repository.save_session_summary(summary1)
        await repository.save_session_summary(summary2)

        # Filter by tenant-a
        tenant_a_summaries = await repository.get_recent_sessions(
            "user-1", limit=10, tenant_id="tenant-a"
        )
        assert len(tenant_a_summaries) == 1
        assert tenant_a_summaries[0].tenant_id == "tenant-a"

    @pytest.mark.asyncio
    async def test_project_filtering(self, repository: MemoryRepository) -> None:
        """Test filtering by project_id and project_root."""
        await repository.initialize_schema()

        summary1 = create_test_summary(
            user_id="user-1",
            session_id="sess-1",
            project_id="proj-1",
            project_root="/home/user/project1",
        )
        summary2 = create_test_summary(
            user_id="user-1",
            session_id="sess-2",
            project_id="proj-2",
            project_root="/home/user/project2",
        )

        await repository.save_session_summary(summary1)
        await repository.save_session_summary(summary2)

        # Filter by project_id
        proj1_summaries = await repository.get_recent_sessions(
            "user-1", limit=10, project_id="proj-1"
        )
        assert len(proj1_summaries) == 1
        assert proj1_summaries[0].project_id == "proj-1"

        # Filter by project_root
        proj2_summaries = await repository.get_recent_sessions(
            "user-1", limit=10, project_root="/home/user/project2"
        )
        assert len(proj2_summaries) == 1
        assert proj2_summaries[0].project_root == "/home/user/project2"

    @pytest.mark.asyncio
    @freeze_time("2024-01-01 12:00:00")
    async def test_delete_old_sessions(self, repository: MemoryRepository) -> None:
        """Test retention-based deletion."""
        await repository.initialize_schema()

        now = datetime.now(timezone.utc)
        old_date = now - timedelta(days=100)
        recent_date = now - timedelta(days=10)

        # Create old and recent summaries
        old_summary = create_test_summary(
            user_id="user-1", session_id="old-sess", session_start=old_date
        )
        recent_summary = create_test_summary(
            user_id="user-1", session_id="recent-sess", session_start=recent_date
        )

        await repository.save_session_summary(old_summary)
        await repository.save_session_summary(recent_summary)

        # Delete sessions older than 90 days
        cutoff = now - timedelta(days=90)
        deleted = await repository.delete_old_sessions(cutoff)

        assert deleted == 1

        # Only recent summary should remain
        summaries = await repository.get_recent_sessions("user-1", limit=10)
        assert len(summaries) == 1
        assert summaries[0].session_id == "recent-sess"

    @pytest.mark.asyncio
    async def test_limit_enforcement(self, repository: MemoryRepository) -> None:
        """Test that limit is enforced on retrieval."""
        await repository.initialize_schema()

        # Create 5 summaries
        with freeze_time("2024-01-01 12:00:00"):
            for i in range(5):
                summary = create_test_summary(
                    user_id="user-1",
                    session_id=f"sess-{i}",
                    session_start=datetime.now(timezone.utc) - timedelta(hours=i),
                )
                await repository.save_session_summary(summary)

        # Retrieve with limit=3
        summaries = await repository.get_recent_sessions("user-1", limit=3)
        assert len(summaries) == 3

        # Most recent first
        assert summaries[0].session_id == "sess-0"

    @pytest.mark.asyncio
    async def test_get_or_create_project_id(self, repository: MemoryRepository) -> None:
        """Test project ID creation and retrieval."""
        await repository.initialize_schema()

        # First call should create
        proj_id1 = await repository.get_or_create_project_id(
            "user-1", "/home/user/project"
        )
        assert proj_id1.startswith("proj-")

        # Second call should return same ID
        proj_id2 = await repository.get_or_create_project_id(
            "user-1", "/home/user/project"
        )
        assert proj_id1 == proj_id2

        # Different project should get different ID
        proj_id3 = await repository.get_or_create_project_id(
            "user-1", "/home/user/other-project"
        )
        assert proj_id3 != proj_id1

        # Different user same project should get different ID
        proj_id4 = await repository.get_or_create_project_id(
            "user-2", "/home/user/project"
        )
        assert proj_id4 != proj_id1

    @pytest.mark.asyncio
    async def test_nested_models_roundtrip(self, repository: MemoryRepository) -> None:
        """Test that nested models survive serialization."""
        await repository.initialize_schema()

        summary = create_test_summary()
        await repository.save_session_summary(summary)

        summaries = await repository.get_recent_sessions("test-user", limit=1)
        retrieved = summaries[0]

        # Check TaskItem roundtrip
        assert len(retrieved.remaining_tasks) == 2
        assert retrieved.remaining_tasks[0].description == "Task 1"
        assert retrieved.remaining_tasks[0].status == "open"

        # Check FileChange roundtrip
        assert len(retrieved.modified_files) == 2
        assert retrieved.modified_files[0].path == "src/test.py"
        assert retrieved.modified_files[0].status == "modified"

        # Check GitOperation roundtrip
        assert len(retrieved.git_operations) == 1
        assert retrieved.git_operations[0].type == "commit"
        assert retrieved.git_operations[0].ref == "abc123"

        # Check TestRun roundtrip
        assert len(retrieved.tests_run) == 1
        assert retrieved.tests_run[0].name == "test_example"
        assert retrieved.tests_run[0].status == "passed"
