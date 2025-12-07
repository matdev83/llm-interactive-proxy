"""Unit tests for memory repository implementation."""

from datetime import datetime, timedelta, timezone

import pytest
from src.core.database.config import DatabaseConfig
from src.core.database.engine import DatabaseEngine
from src.core.database.repositories.memory_repository import SQLModelMemoryRepository
from src.core.memory.models import (
    FileChange,
    GitOperation,
    SessionSummary,
    TaskItem,
    TestRun,
)


class TestSQLModelMemoryRepository:
    """Tests for SQLModelMemoryRepository."""

    @pytest.fixture
    async def engine(self) -> DatabaseEngine:
        """Create in-memory database engine for testing."""
        config = DatabaseConfig(url="sqlite+aiosqlite:///:memory:")
        engine = DatabaseEngine(config)
        await engine.initialize()
        yield engine
        await engine.close()

    @pytest.fixture
    def repository(self, engine: DatabaseEngine) -> SQLModelMemoryRepository:
        """Create memory repository for testing."""
        repo = SQLModelMemoryRepository(engine)
        repo._initialized = True  # Skip redundant init
        return repo

    @pytest.fixture
    def sample_summary(self) -> SessionSummary:
        """Create a sample session summary for testing."""
        return SessionSummary(
            id="test-summary-123",
            user_id="user-456",
            tenant_id="tenant-789",
            project_id="proj-001",
            project_root="/path/to/project",
            session_id="session-abc",
            session_start=datetime.now(timezone.utc),
            client_agent="test-agent",
            backend_model="openai:gpt-4",
            title="Test Session Summary",
            scope="Test scope",
            goals=["Goal 1", "Goal 2"],
            modified_files=[FileChange(path="test.py", status="modified")],
            remaining_tasks=[TaskItem(description="Task 1", status="open")],
            git_operations=[
                GitOperation(type="commit", ref="abc123", details="Test commit")
            ],
            operations_performed=["op1", "op2"],
            open_questions=["Question 1"],
            tests_run=[TestRun(name="test_foo", status="passed")],
            errors=["Error 1"],
            branch="main",
            head_sha="abc123def456",
            completion_status="complete",
            key_decisions=["Decision 1"],
            risks_or_warnings=["Warning 1"],
            evidence=["Evidence 1"],
            full_analysis="Full analysis text here",
            summary_version="v1",
            created_at=datetime.now(timezone.utc),
        )

    @pytest.mark.asyncio
    async def test_model_class_property(
        self, repository: SQLModelMemoryRepository
    ) -> None:
        """Test model_class property returns correct type."""
        from src.core.database.models.memory import SessionSummaryTable

        assert repository.model_class is SessionSummaryTable

    @pytest.mark.asyncio
    async def test_save_and_retrieve_summary(
        self,
        repository: SQLModelMemoryRepository,
        sample_summary: SessionSummary,
    ) -> None:
        """Test saving and retrieving a session summary."""
        await repository.save_session_summary(sample_summary)

        # Retrieve it
        summaries = await repository.get_recent_sessions(
            user_id=sample_summary.user_id,
            limit=10,
        )

        assert len(summaries) == 1
        retrieved = summaries[0]
        assert retrieved.id == sample_summary.id
        assert retrieved.user_id == sample_summary.user_id
        assert retrieved.title == sample_summary.title
        assert retrieved.backend_model == sample_summary.backend_model

    @pytest.mark.asyncio
    async def test_save_updates_existing_summary(
        self,
        repository: SQLModelMemoryRepository,
        sample_summary: SessionSummary,
    ) -> None:
        """Test that saving with same ID updates existing record."""
        await repository.save_session_summary(sample_summary)

        # Modify and save again
        updated = SessionSummary(
            **{**sample_summary.model_dump(), "title": "Updated Title"}
        )
        await repository.save_session_summary(updated)

        # Should still have only one record
        summaries = await repository.get_recent_sessions(
            user_id=sample_summary.user_id,
            limit=10,
        )

        assert len(summaries) == 1
        assert summaries[0].title == "Updated Title"

    @pytest.mark.asyncio
    async def test_get_recent_sessions_respects_limit(
        self,
        repository: SQLModelMemoryRepository,
    ) -> None:
        """Test that get_recent_sessions respects limit parameter."""
        user_id = "user-limit-test"

        # Create multiple summaries
        for i in range(5):
            summary = SessionSummary(
                id=f"summary-{i}",
                user_id=user_id,
                session_id=f"session-{i}",
                session_start=datetime.now(timezone.utc) + timedelta(minutes=i),
                backend_model="model",
                title=f"Session {i}",
                scope="Test scope",
                completion_status="complete",
                full_analysis="Analysis",
                summary_version="v1",
                created_at=datetime.now(timezone.utc),
            )
            await repository.save_session_summary(summary)

        # Get with limit
        summaries = await repository.get_recent_sessions(
            user_id=user_id,
            limit=3,
        )

        assert len(summaries) == 3

    @pytest.mark.asyncio
    async def test_get_recent_sessions_orders_by_session_start_desc(
        self,
        repository: SQLModelMemoryRepository,
    ) -> None:
        """Test that results are ordered by session_start descending."""
        user_id = "user-order-test"
        base_time = datetime.now(timezone.utc)

        # Create summaries with different start times
        for i in range(3):
            summary = SessionSummary(
                id=f"summary-order-{i}",
                user_id=user_id,
                session_id=f"session-{i}",
                session_start=base_time + timedelta(hours=i),
                backend_model="model",
                title=f"Session {i}",
                scope="Test scope",
                completion_status="complete",
                full_analysis="Analysis",
                summary_version="v1",
                created_at=datetime.now(timezone.utc),
            )
            await repository.save_session_summary(summary)

        summaries = await repository.get_recent_sessions(
            user_id=user_id,
            limit=10,
        )

        # Most recent first
        assert summaries[0].id == "summary-order-2"
        assert summaries[1].id == "summary-order-1"
        assert summaries[2].id == "summary-order-0"

    @pytest.mark.asyncio
    async def test_get_recent_sessions_filters_by_tenant_id(
        self,
        repository: SQLModelMemoryRepository,
    ) -> None:
        """Test filtering by tenant_id."""
        user_id = "user-tenant-test"

        # Create summaries for different tenants
        for tenant in ["tenant-a", "tenant-b"]:
            summary = SessionSummary(
                id=f"summary-{tenant}",
                user_id=user_id,
                tenant_id=tenant,
                session_id=f"session-{tenant}",
                session_start=datetime.now(timezone.utc),
                backend_model="model",
                title=f"Session for {tenant}",
                scope="Test scope",
                completion_status="complete",
                full_analysis="Analysis",
                summary_version="v1",
                created_at=datetime.now(timezone.utc),
            )
            await repository.save_session_summary(summary)

        # Get only tenant-a
        summaries = await repository.get_recent_sessions(
            user_id=user_id,
            limit=10,
            tenant_id="tenant-a",
        )

        assert len(summaries) == 1
        assert summaries[0].tenant_id == "tenant-a"

    @pytest.mark.asyncio
    async def test_get_recent_sessions_filters_by_project_id(
        self,
        repository: SQLModelMemoryRepository,
    ) -> None:
        """Test filtering by project_id."""
        user_id = "user-project-test"

        # Create summaries for different projects
        for proj_id in ["proj-a", "proj-b"]:
            summary = SessionSummary(
                id=f"summary-{proj_id}",
                user_id=user_id,
                project_id=proj_id,
                session_id=f"session-{proj_id}",
                session_start=datetime.now(timezone.utc),
                backend_model="model",
                title=f"Session for {proj_id}",
                scope="Test scope",
                completion_status="complete",
                full_analysis="Analysis",
                summary_version="v1",
                created_at=datetime.now(timezone.utc),
            )
            await repository.save_session_summary(summary)

        summaries = await repository.get_recent_sessions(
            user_id=user_id,
            limit=10,
            project_id="proj-a",
        )

        assert len(summaries) == 1
        assert summaries[0].project_id == "proj-a"

    @pytest.mark.asyncio
    async def test_get_recent_sessions_filters_by_project_root(
        self,
        repository: SQLModelMemoryRepository,
    ) -> None:
        """Test filtering by project_root when project_id not provided."""
        user_id = "user-root-test"

        # Create summaries for different project roots
        for root in ["/path/a", "/path/b"]:
            summary = SessionSummary(
                id=f"summary-{root.replace('/', '-')}",
                user_id=user_id,
                project_root=root,
                session_id=f"session-{root}",
                session_start=datetime.now(timezone.utc),
                backend_model="model",
                title=f"Session for {root}",
                scope="Test scope",
                completion_status="complete",
                full_analysis="Analysis",
                summary_version="v1",
                created_at=datetime.now(timezone.utc),
            )
            await repository.save_session_summary(summary)

        summaries = await repository.get_recent_sessions(
            user_id=user_id,
            limit=10,
            project_root="/path/a",
        )

        assert len(summaries) == 1
        assert summaries[0].project_root == "/path/a"

    @pytest.mark.asyncio
    async def test_delete_old_sessions(
        self,
        repository: SQLModelMemoryRepository,
    ) -> None:
        """Test deleting sessions older than a date."""
        user_id = "user-delete-test"
        now = datetime.now(timezone.utc)

        # Create old and new sessions
        old_summary = SessionSummary(
            id="old-summary",
            user_id=user_id,
            session_id="old-session",
            session_start=now - timedelta(days=100),
            backend_model="model",
            title="Old Session",
            scope="Test scope",
            completion_status="complete",
            full_analysis="Analysis",
            summary_version="v1",
            created_at=now - timedelta(days=100),
        )
        new_summary = SessionSummary(
            id="new-summary",
            user_id=user_id,
            session_id="new-session",
            session_start=now,
            backend_model="model",
            title="New Session",
            scope="Test scope",
            completion_status="complete",
            full_analysis="Analysis",
            summary_version="v1",
            created_at=now,
        )

        await repository.save_session_summary(old_summary)
        await repository.save_session_summary(new_summary)

        # Delete sessions older than 30 days
        deleted_count = await repository.delete_old_sessions(
            before_date=now - timedelta(days=30)
        )

        assert deleted_count == 1

        # Verify only new session remains
        summaries = await repository.get_recent_sessions(
            user_id=user_id,
            limit=10,
        )
        assert len(summaries) == 1
        assert summaries[0].id == "new-summary"

    @pytest.mark.asyncio
    async def test_get_or_create_project_id_creates_new(
        self,
        repository: SQLModelMemoryRepository,
    ) -> None:
        """Test creating a new project ID."""
        user_id = "user-proj-create"
        project_root = "/new/project/path"

        proj_id = await repository.get_or_create_project_id(user_id, project_root)

        assert proj_id.startswith("proj-")
        assert proj_id != "proj-None"

    @pytest.mark.asyncio
    async def test_get_or_create_project_id_returns_existing(
        self,
        repository: SQLModelMemoryRepository,
    ) -> None:
        """Test that same user+project_root returns same ID."""
        user_id = "user-proj-existing"
        project_root = "/existing/project"

        proj_id1 = await repository.get_or_create_project_id(user_id, project_root)
        proj_id2 = await repository.get_or_create_project_id(user_id, project_root)

        assert proj_id1 == proj_id2

    @pytest.mark.asyncio
    async def test_get_or_create_project_id_different_users(
        self,
        repository: SQLModelMemoryRepository,
    ) -> None:
        """Test that different users get different project IDs for same root."""
        project_root = "/shared/project"

        proj_id1 = await repository.get_or_create_project_id("user-a", project_root)
        proj_id2 = await repository.get_or_create_project_id("user-b", project_root)

        # Different users should get different project IDs
        assert proj_id1 != proj_id2

    @pytest.mark.asyncio
    async def test_json_fields_roundtrip(
        self,
        repository: SQLModelMemoryRepository,
        sample_summary: SessionSummary,
    ) -> None:
        """Test that JSON-serialized fields survive roundtrip."""
        await repository.save_session_summary(sample_summary)

        summaries = await repository.get_recent_sessions(
            user_id=sample_summary.user_id,
            limit=1,
        )

        retrieved = summaries[0]

        # Check list fields
        assert retrieved.goals == sample_summary.goals
        assert retrieved.operations_performed == sample_summary.operations_performed
        assert retrieved.open_questions == sample_summary.open_questions
        assert retrieved.errors == sample_summary.errors
        assert retrieved.key_decisions == sample_summary.key_decisions

        # Check nested model fields
        assert len(retrieved.modified_files) == len(sample_summary.modified_files)
        assert retrieved.modified_files[0].path == sample_summary.modified_files[0].path

        assert len(retrieved.remaining_tasks) == len(sample_summary.remaining_tasks)
        assert (
            retrieved.remaining_tasks[0].description
            == sample_summary.remaining_tasks[0].description
        )

        assert len(retrieved.git_operations) == len(sample_summary.git_operations)
        assert retrieved.git_operations[0].type == sample_summary.git_operations[0].type

        assert len(retrieved.tests_run) == len(sample_summary.tests_run)
        assert retrieved.tests_run[0].name == sample_summary.tests_run[0].name

    @pytest.mark.asyncio
    async def test_close_is_safe(
        self,
        repository: SQLModelMemoryRepository,
    ) -> None:
        """Test that close() can be called safely."""
        # Should not raise
        await repository.close()
        await repository.close()  # Multiple calls should be safe
