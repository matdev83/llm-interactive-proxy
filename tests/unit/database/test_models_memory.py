"""Unit tests for memory SQLModel table models."""

from datetime import datetime, timezone

from freezegun import freeze_time
from sqlmodel import SQLModel
from src.core.database.models.memory import (
    SessionSummaryTable,
    UserProjectDirTable,
)


class TestSessionSummaryTable:
    """Tests for SessionSummaryTable model."""

    def test_table_name(self) -> None:
        """Test that table name is correct."""
        assert SessionSummaryTable.__tablename__ == "session_summaries"

    def test_is_sqlmodel_table(self) -> None:
        """Test that model is properly configured as a SQLModel table."""
        assert issubclass(SessionSummaryTable, SQLModel)
        # Check that table=True was set
        assert hasattr(SessionSummaryTable, "__table__")

    @freeze_time("2024-01-01 12:00:00")
    def test_create_minimal_record(self) -> None:
        """Test creating a record with minimal required fields."""
        record = SessionSummaryTable(
            id="test-id-123",
            user_id="user-456",
            session_id="session-789",
            session_start=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            backend_model="openai:gpt-4",
            title="Test Session",
            summary_version="v1",
        )

        assert record.id == "test-id-123"
        assert record.user_id == "user-456"
        assert record.session_id == "session-789"
        assert record.backend_model == "openai:gpt-4"
        assert record.title == "Test Session"
        assert record.summary_version == "v1"

    @freeze_time("2024-01-01 12:00:00")
    def test_create_full_record(self) -> None:
        """Test creating a record with all fields."""
        now = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        record = SessionSummaryTable(
            id="test-id-full",
            user_id="user-full",
            tenant_id="tenant-123",
            project_id="proj-456",
            project_root="/path/to/project",
            session_id="session-full",
            session_start=now,
            client_agent="test-agent",
            backend_model="anthropic:claude-3",
            title="Full Test Session",
            scope="Test scope",
            goals='["goal1", "goal2"]',
            modified_files='[{"path": "test.py", "change": "modified"}]',
            remaining_tasks='[{"task": "test", "done": false}]',
            git_operations="[]",
            operations_performed='["op1", "op2"]',
            open_questions='["question1"]',
            tests_run="[]",
            errors="[]",
            branch="main",
            head_sha="abc123",
            completion_status="complete",
            key_decisions='["decision1"]',
            risks_or_warnings="[]",
            evidence="[]",
            full_analysis="Full analysis text",
            summary_version="v1",
            created_at=now,
        )

        assert record.tenant_id == "tenant-123"
        assert record.project_id == "proj-456"
        assert record.project_root == "/path/to/project"
        assert record.client_agent == "test-agent"
        assert record.scope == "Test scope"
        assert record.goals == '["goal1", "goal2"]'
        assert record.branch == "main"
        assert record.head_sha == "abc123"
        assert record.completion_status == "complete"
        assert record.full_analysis == "Full analysis text"

    @freeze_time("2024-01-01 12:00:00")
    def test_optional_fields_default_to_none(self) -> None:
        """Test that optional fields default to None."""
        record = SessionSummaryTable(
            id="test-id",
            user_id="user-id",
            session_id="session-id",
            session_start=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            backend_model="model",
            title="Title",
            summary_version="v1",
        )

        assert record.tenant_id is None
        assert record.project_id is None
        assert record.project_root is None
        assert record.client_agent is None
        assert record.scope is None
        assert record.goals is None
        assert record.modified_files is None
        assert record.branch is None
        assert record.head_sha is None

    @freeze_time("2024-01-01 12:00:00")
    def test_created_at_has_default(self) -> None:
        """Test that created_at has a default value."""
        # With freeze_time, the default should be set to the frozen time
        record = SessionSummaryTable(
            id="test-id",
            user_id="user-id",
            session_id="session-id",
            session_start=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            backend_model="model",
            title="Title",
            summary_version="v1",
        )

        assert record.created_at is not None
        # Default should be set to frozen time
        assert record.created_at == datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    def test_has_required_indexes(self) -> None:
        """Test that model defines required indexes."""
        # Check __table_args__ contains indexes
        table_args = SessionSummaryTable.__table_args__
        assert table_args is not None

        # Get index names
        index_names = [idx.name for idx in table_args if hasattr(idx, "name")]
        assert "idx_session_summaries_session_start" in index_names
        assert "idx_session_summaries_user_session_start" in index_names
        assert "idx_session_summaries_user_tenant" in index_names
        assert "idx_session_summaries_user_project" in index_names


class TestUserProjectDirTable:
    """Tests for UserProjectDirTable model."""

    def test_table_name(self) -> None:
        """Test that table name is correct."""
        assert UserProjectDirTable.__tablename__ == "user_project_dirs"

    def test_is_sqlmodel_table(self) -> None:
        """Test that model is properly configured as a SQLModel table."""
        assert issubclass(UserProjectDirTable, SQLModel)
        assert hasattr(UserProjectDirTable, "__table__")

    def test_create_record(self) -> None:
        """Test creating a record."""
        record = UserProjectDirTable(
            user_id="user-123",
            project_root="/path/to/project",
        )

        assert record.id is None  # Auto-generated
        assert record.user_id == "user-123"
        assert record.project_root == "/path/to/project"

    def test_create_record_with_id(self) -> None:
        """Test creating a record with explicit ID."""
        record = UserProjectDirTable(
            id=42,
            user_id="user-123",
            project_root="/path/to/project",
        )

        assert record.id == 42

    def test_has_unique_constraint(self) -> None:
        """Test that model has unique constraint on user_id + project_root."""
        table_args = UserProjectDirTable.__table_args__
        assert table_args is not None

        # Check for unique index
        index_names = [idx.name for idx in table_args if hasattr(idx, "name")]
        assert "idx_user_project_dirs_unique" in index_names
