"""SQLModel models for memory/ProxyMem feature."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import Index
from sqlmodel import Field, SQLModel

if TYPE_CHECKING:
    pass


class SessionSummaryTable(SQLModel, table=True):
    """SQLModel table for session summaries.

    Stores AI session summaries including goals, modified files,
    and completion status for cross-session context retrieval.
    """

    __tablename__ = "session_summaries"  # type: ignore[assignment]

    # Primary key
    id: str = Field(primary_key=True, max_length=64)

    # Identity fields (for scoping)
    user_id: str = Field(nullable=False, index=True, max_length=256)
    tenant_id: str | None = Field(default=None, max_length=256)
    project_id: str | None = Field(default=None, max_length=256)
    project_root: str | None = Field(default=None, max_length=1024)

    # Session metadata
    session_id: str = Field(nullable=False, max_length=64)
    session_start: datetime = Field(nullable=False)
    client_agent: str | None = Field(default=None, max_length=256)
    backend_model: str = Field(nullable=False, max_length=256)

    # Summary content
    title: str = Field(nullable=False, max_length=512)
    scope: str | None = Field(default=None, max_length=1024)

    # JSON-serialized fields (stored as TEXT)
    goals: str | None = Field(default=None)  # JSON list of strings
    modified_files: str | None = Field(default=None)  # JSON list of FileChange
    remaining_tasks: str | None = Field(default=None)  # JSON list of TaskItem
    git_operations: str | None = Field(default=None)  # JSON list of GitOperation
    operations_performed: str | None = Field(default=None)  # JSON list of strings
    open_questions: str | None = Field(default=None)  # JSON list of strings
    tests_run: str | None = Field(default=None)  # JSON list of TestRun
    errors: str | None = Field(default=None)  # JSON list of strings
    key_decisions: str | None = Field(default=None)  # JSON list of strings
    risks_or_warnings: str | None = Field(default=None)  # JSON list of strings
    evidence: str | None = Field(default=None)  # JSON list of strings

    # Git context
    branch: str | None = Field(default=None, max_length=256)
    head_sha: str | None = Field(default=None, max_length=64)

    # Status and analysis
    completion_status: str | None = Field(default=None, max_length=64)
    full_analysis: str | None = Field(default=None)

    # Versioning
    summary_version: str = Field(nullable=False, max_length=32)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Define composite indexes
    __table_args__ = (
        Index("idx_session_summaries_session_start", "session_start"),
        Index("idx_session_summaries_user_session_start", "user_id", "session_start"),
        Index(
            "idx_session_summaries_user_tenant", "user_id", "tenant_id", "session_start"
        ),
        Index(
            "idx_session_summaries_user_project",
            "user_id",
            "project_id",
            "session_start",
        ),
    )


class UserProjectDirTable(SQLModel, table=True):
    """SQLModel table for user project directory mappings.

    Maps user+project_root pairs to stable project IDs.
    """

    __tablename__ = "user_project_dirs"  # type: ignore[assignment]

    # Auto-increment primary key
    id: int | None = Field(default=None, primary_key=True)

    # Composite unique constraint
    user_id: str = Field(nullable=False, max_length=256)
    project_root: str = Field(nullable=False, max_length=1024)

    __table_args__ = (
        Index("idx_user_project_dirs_unique", "user_id", "project_root", unique=True),
    )
