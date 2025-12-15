"""Unit tests for ProxyMem domain models."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError
from src.core.memory.models import (
    CapturedInteraction,
    FileChange,
    FileEditEvent,
    GitCommitEvent,
    GitOperation,
    SessionData,
    SessionSummary,
    TaskItem,
    TestRun,
)


class TestTaskItem:
    """Tests for TaskItem model."""

    def test_create_open_task(self) -> None:
        """Test creating an open task."""
        task = TaskItem(description="Implement feature X", status="open")
        assert task.description == "Implement feature X"
        assert task.status == "open"

    def test_create_blocked_task(self) -> None:
        """Test creating a blocked task."""
        task = TaskItem(description="Waiting for API", status="blocked")
        assert task.description == "Waiting for API"
        assert task.status == "blocked"

    def test_task_is_frozen(self) -> None:
        """Test that TaskItem is immutable."""
        task = TaskItem(description="Test", status="open")
        with pytest.raises(ValidationError):
            task.status = "blocked"  # type: ignore[misc]


class TestFileChange:
    """Tests for FileChange model."""

    def test_create_created_file(self) -> None:
        """Test file with created status."""
        change = FileChange(path="src/new_file.py", status="created")
        assert change.path == "src/new_file.py"
        assert change.status == "created"

    def test_create_modified_file(self) -> None:
        """Test file with modified status."""
        change = FileChange(path="src/existing.py", status="modified")
        assert change.status == "modified"

    def test_create_deleted_file(self) -> None:
        """Test file with deleted status."""
        change = FileChange(path="old_file.py", status="deleted")
        assert change.status == "deleted"


class TestGitOperation:
    """Tests for GitOperation model."""

    def test_commit_operation(self) -> None:
        """Test commit git operation."""
        op = GitOperation(
            type="commit",
            ref="abc123",
            details="Added new feature",
        )
        assert op.type == "commit"
        assert op.ref == "abc123"
        assert op.details == "Added new feature"

    def test_branch_operation(self) -> None:
        """Test branch git operation."""
        op = GitOperation(
            type="branch",
            ref="feature/new-feature",
            details="Created feature branch",
        )
        assert op.type == "branch"
        assert op.ref == "feature/new-feature"

    def test_merge_operation_no_ref(self) -> None:
        """Test merge operation without ref."""
        op = GitOperation(
            type="merge",
            ref=None,
            details="Merged main into feature branch",
        )
        assert op.type == "merge"
        assert op.ref is None


class TestTestRun:
    """Tests for TestRun model."""

    def test_passed_test(self) -> None:
        """Test passed test run."""
        test = TestRun(
            name="test_feature_works",
            status="passed",
            command="pytest tests/test_feature.py",
        )
        assert test.name == "test_feature_works"
        assert test.status == "passed"
        assert test.command == "pytest tests/test_feature.py"

    def test_failed_test(self) -> None:
        """Test failed test run."""
        test = TestRun(name="test_broken", status="failed")
        assert test.status == "failed"
        assert test.command is None

    def test_timeout_test(self) -> None:
        """Test timeout test run."""
        test = TestRun(name="test_slow", status="timeout")
        assert test.status == "timeout"

    def test_skipped_test(self) -> None:
        """Test skipped test run."""
        test = TestRun(name="test_conditional", status="skipped")
        assert test.status == "skipped"


class TestCapturedInteraction:
    """Tests for CapturedInteraction model."""

    def test_user_interaction(self) -> None:
        """Test user interaction capture."""
        now = datetime.now(timezone.utc)
        interaction = CapturedInteraction(
            timestamp=now,
            role="user",
            content="Please implement feature X",
            metadata={"client": "test-client"},
        )
        assert interaction.timestamp == now
        assert interaction.role == "user"
        assert interaction.content == "Please implement feature X"
        assert interaction.metadata == {"client": "test-client"}

    def test_assistant_interaction(self) -> None:
        """Test assistant interaction capture."""
        now = datetime.now(timezone.utc)
        interaction = CapturedInteraction(
            timestamp=now,
            role="assistant",
            content="I will implement feature X",
            metadata={"model": "gpt-4o", "tokens": 150},
        )
        assert interaction.role == "assistant"
        assert interaction.metadata["model"] == "gpt-4o"

    def test_default_metadata(self) -> None:
        """Test default empty metadata."""
        interaction = CapturedInteraction(
            timestamp=datetime.now(timezone.utc),
            role="user",
            content="Hello",
        )
        assert interaction.metadata == {}


class TestSessionData:
    """Tests for SessionData model."""

    def test_minimal_session_data(self) -> None:
        """Test session data with minimal required fields."""
        now = datetime.now(timezone.utc)
        data = SessionData(
            session_id="sess-123",
            user_id="user-456",
            backend_model="openai:gpt-4o",
            started_at=now,
            ended_at=now,
            transcript_chars=1000,
        )
        assert data.session_id == "sess-123"
        assert data.user_id == "user-456"
        assert data.backend_model == "openai:gpt-4o"
        assert data.tenant_id is None
        assert data.project_id is None
        assert data.interactions == []
        assert data.deterministic_file_edits == []
        assert data.deterministic_git_commits == []

    def test_full_session_data(self) -> None:
        """Test session data with all fields."""
        now = datetime.now(timezone.utc)
        interaction = CapturedInteraction(
            timestamp=now,
            role="user",
            content="Test",
        )
        file_edit = FileEditEvent(
            path="src/file.py",
            action="modified",
            tool="apply_patch",
            timestamp=now,
        )
        git_commit = GitCommitEvent(
            commit_hash="abc123",
            message="Fix bug",
            branch="main",
            timestamp=now,
        )
        data = SessionData(
            session_id="sess-123",
            user_id="user-456",
            tenant_id="tenant-789",
            project_id="proj-abc",
            project_root="/home/user/project",
            client_agent="vscode",
            backend_model="openai:gpt-4o",
            branch="main",
            head_sha="abc123def",
            started_at=now,
            ended_at=now,
            transcript_chars=5000,
            estimated_tokens=1200,
            redaction_applied=True,
            interactions=[interaction],
            deterministic_file_edits=[file_edit],
            deterministic_git_commits=[git_commit],
        )
        assert data.tenant_id == "tenant-789"
        assert data.project_id == "proj-abc"
        assert data.project_root == "/home/user/project"
        assert data.branch == "main"
        assert data.head_sha == "abc123def"
        assert data.redaction_applied is True
        assert len(data.interactions) == 1
        assert len(data.deterministic_file_edits) == 1
        assert data.deterministic_file_edits[0].path == "src/file.py"
        assert len(data.deterministic_git_commits) == 1
        assert data.deterministic_git_commits[0].commit_hash == "abc123"


class TestSessionSummary:
    """Tests for SessionSummary model."""

    def test_minimal_session_summary(self) -> None:
        """Test session summary with minimal required fields."""
        now = datetime.now(timezone.utc)
        summary = SessionSummary(
            id="sum-123",
            user_id="user-456",
            session_id="sess-789",
            session_start=now,
            backend_model="openai:gpt-4o",
            title="Implemented feature X",
            scope="Feature development",
            completion_status="completed",
            full_analysis="<session_summary>...</session_summary>",
            summary_version="v1",
            created_at=now,
        )
        assert summary.id == "sum-123"
        assert summary.user_id == "user-456"
        assert summary.title == "Implemented feature X"
        assert summary.completion_status == "completed"
        assert summary.goals == []
        assert summary.modified_files == []

    def test_full_session_summary(self) -> None:
        """Test session summary with all fields populated."""
        now = datetime.now(timezone.utc)
        summary = SessionSummary(
            id="sum-123",
            user_id="user-456",
            tenant_id="tenant-abc",
            project_id="proj-xyz",
            project_root="/home/user/project",
            session_id="sess-789",
            session_start=now,
            client_agent="cursor",
            backend_model="anthropic:claude-3-opus",
            title="Refactored authentication system",
            scope="Security improvements",
            goals=["Improve security", "Add MFA support"],
            open_questions=["Should we support SMS 2FA?"],
            remaining_tasks=[
                TaskItem(description="Add SMS provider", status="open"),
            ],
            modified_files=[
                FileChange(path="src/auth.py", status="modified"),
                FileChange(path="src/mfa.py", status="created"),
            ],
            git_operations=[
                GitOperation(type="commit", ref="abc123", details="Add MFA"),
            ],
            completion_status="partial",
            key_decisions=["Using TOTP over SMS"],
            operations_performed=["ran migration", "updated schema"],
            tests_run=[
                TestRun(name="test_mfa", status="passed"),
            ],
            errors=["TypeError in legacy code"],
            risks_or_warnings=["Breaking change for API v1"],
            evidence=["See commit abc123"],
            full_analysis="<session_summary>...</session_summary>",
            branch="feature/mfa",
            head_sha="abc123def456",
            summary_version="v1",
            created_at=now,
        )
        assert summary.tenant_id == "tenant-abc"
        assert len(summary.goals) == 2
        assert len(summary.modified_files) == 2
        assert len(summary.git_operations) == 1
        assert summary.branch == "feature/mfa"
        assert summary.completion_status == "partial"

    def test_session_summary_is_frozen(self) -> None:
        """Test that SessionSummary is immutable."""
        now = datetime.now(timezone.utc)
        summary = SessionSummary(
            id="sum-123",
            user_id="user-456",
            session_id="sess-789",
            session_start=now,
            backend_model="openai:gpt-4o",
            title="Test",
            scope="Test",
            completion_status="completed",
            full_analysis="<session_summary/>",
            summary_version="v1",
            created_at=now,
        )
        with pytest.raises(ValidationError):
            summary.title = "Modified"  # type: ignore[misc]
