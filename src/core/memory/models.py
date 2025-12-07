"""Domain models for ProxyMem feature."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import ConfigDict, Field

from src.core.interfaces.model_bases import DomainModel


class TaskItem(DomainModel):
    """Remaining or open tasks from the session."""

    model_config = ConfigDict(frozen=True)

    description: str
    status: Literal["open", "blocked"]


class FileChange(DomainModel):
    """A single file touched during the session."""

    model_config = ConfigDict(frozen=True)

    path: str
    status: Literal["created", "modified", "deleted"]


class GitOperation(DomainModel):
    """Git actions observed during the session."""

    model_config = ConfigDict(frozen=True)

    type: Literal["commit", "branch", "merge", "rebase", "cherry-pick"]
    ref: str | None = None
    details: str


class FileEditEvent(DomainModel):
    """Deterministic record of a file edit captured from tool calls.

    Captures file edit operations from proxy tool hooks (e.g., apply_patch,
    write-file, append-file) with normalized paths and action classification.
    """

    model_config = ConfigDict(frozen=True)

    path: str  # normalized relative to project_root when available
    action: Literal["created", "modified", "deleted", "unknown"]
    tool: str | None = None  # original tool name for auditability
    timestamp: datetime


class GitCommitEvent(DomainModel):
    """Deterministic record of a git commit event captured from tool calls.

    Captures git commit operations detected from proxy tool hooks.
    """

    model_config = ConfigDict(frozen=True)

    commit_hash: str
    message: str | None = None
    branch: str | None = None
    timestamp: datetime


# Type alias for deterministic tool events
ToolEvent = FileEditEvent | GitCommitEvent


class TestRun(DomainModel):
    """Test execution details."""

    model_config = ConfigDict(frozen=True)

    name: str
    status: Literal["passed", "failed", "timeout", "skipped"]
    command: str | None = None


class CapturedInteraction(DomainModel):
    """A single captured interaction in a session."""

    model_config = ConfigDict(frozen=True)

    timestamp: datetime
    role: str  # "user" or "assistant"
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class SessionData(DomainModel):
    """Complete data for a session pending analysis."""

    model_config = ConfigDict(frozen=True)

    session_id: str
    user_id: str
    tenant_id: str | None = None
    project_id: str | None = None
    project_root: str | None = None
    client_agent: str | None = None
    backend_model: str
    branch: str | None = None
    head_sha: str | None = None
    started_at: datetime
    ended_at: datetime
    transcript_chars: int
    estimated_tokens: int | None = None
    redaction_applied: bool = False
    interactions: list[CapturedInteraction] = Field(default_factory=list)
    # Deterministic tool events from proxy hooks
    deterministic_file_edits: list[FileEditEvent] = Field(default_factory=list)
    deterministic_git_commits: list[GitCommitEvent] = Field(default_factory=list)


class SessionSummary(DomainModel):
    """Structured summary of a completed session."""

    model_config = ConfigDict(frozen=True)

    id: str  # UUID
    user_id: str
    tenant_id: str | None = None
    project_id: str | None = None
    project_root: str | None = None
    session_id: str
    session_start: datetime
    client_agent: str | None = None
    backend_model: str  # backend:model format
    title: str  # One-sentence summary
    scope: str  # What the session was about
    goals: list[str] = Field(default_factory=list)  # Main objectives
    open_questions: list[str] = Field(default_factory=list)
    remaining_tasks: list[TaskItem] = Field(default_factory=list)
    modified_files: list[FileChange] = Field(default_factory=list)
    git_operations: list[GitOperation] = Field(default_factory=list)
    completion_status: str  # "completed", "partial", "abandoned"
    key_decisions: list[str] = Field(default_factory=list)
    operations_performed: list[str] = Field(default_factory=list)
    tests_run: list[TestRun] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    risks_or_warnings: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    full_analysis: str  # Complete LLM analysis (XML payload)
    branch: str | None = None
    head_sha: str | None = None
    summary_version: str
    created_at: datetime
