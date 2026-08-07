"""Unit tests for ContextInjector."""

from __future__ import annotations

import tempfile
from collections.abc import AsyncGenerator, Generator
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from freezegun import freeze_time
from src.core.memory.config import MemoryConfiguration
from src.core.memory.context_injector import ContextInjector
from src.core.memory.models import SessionSummary, TaskItem
from src.core.memory.sqlite_repository import MemoryRepository


def create_summary(
    user_id: str = "user-1",
    session_id: str = "sess-1",
    title: str = "Test Session",
    days_ago: int = 0,
    remaining_tasks: list[TaskItem] | None = None,
    key_decisions: list[str] | None = None,
    risks_or_warnings: list[str] | None = None,
    base_time: datetime | None = None,
) -> SessionSummary:
    """Create a test SessionSummary."""
    if base_time is None:
        # Use freeze_time only if base_time is not provided
        with freeze_time("2024-01-01 12:00:00"):
            now = datetime.now(timezone.utc) - timedelta(days=days_ago)
            return _create_summary_impl(
                user_id,
                session_id,
                title,
                now,
                remaining_tasks,
                key_decisions,
                risks_or_warnings,
            )
    else:
        # Use provided base_time directly (assumes freeze_time is already active)
        now = base_time - timedelta(days=days_ago)
        return _create_summary_impl(
            user_id,
            session_id,
            title,
            now,
            remaining_tasks,
            key_decisions,
            risks_or_warnings,
        )


def _create_summary_impl(
    user_id: str,
    session_id: str,
    title: str,
    now: datetime,
    remaining_tasks: list[TaskItem] | None,
    key_decisions: list[str] | None,
    risks_or_warnings: list[str] | None,
) -> SessionSummary:
    """Internal implementation of create_summary."""
    return SessionSummary(
        id=f"sum-{session_id}",
        user_id=user_id,
        session_id=session_id,
        session_start=now,
        backend_model="openai:gpt-4o",
        title=title,
        scope="Testing",
        goals=["Goal 1"],
        remaining_tasks=remaining_tasks or [],
        key_decisions=key_decisions or [],
        risks_or_warnings=risks_or_warnings or [],
        completion_status="completed",
        full_analysis="<session_summary/>",
        summary_version="v1",
        created_at=now,
    )


class TestContextInjector:
    """Tests for ContextInjector."""

    @pytest.fixture
    def temp_db_path(self) -> Generator[Path, None, None]:
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
            max_sessions_to_consider=5,
            # Set low threshold for tests since we don't have exact keyword matches
            context_relevance_threshold=0.0,
        )

    @pytest.fixture
    async def repository(
        self, config: MemoryConfiguration
    ) -> AsyncGenerator[MemoryRepository, None]:
        """Create repository instance."""
        repo = MemoryRepository(config)
        yield repo
        await repo.close()

    @pytest.fixture
    def injector(
        self, config: MemoryConfiguration, repository: MemoryRepository
    ) -> ContextInjector:
        """Create injector instance."""
        return ContextInjector(config, repository)

    @pytest.mark.asyncio
    async def test_returns_none_when_no_history(
        self, injector: ContextInjector, repository: MemoryRepository
    ) -> None:
        """Test returns None when no historical sessions."""
        await repository.initialize_schema()

        context = await injector.get_context_for_session(
            user_id="user-1",
            current_prompt="Help me with something",
        )

        assert context is None

    @pytest.mark.asyncio
    async def test_returns_context_with_history(
        self, injector: ContextInjector, repository: MemoryRepository
    ) -> None:
        """Test returns context when historical sessions exist."""
        await repository.initialize_schema()

        summary = create_summary(
            title="Previous work on auth",
            key_decisions=["Use JWT tokens"],
        )
        await repository.save_session_summary(summary)

        context = await injector.get_context_for_session(
            user_id="user-1",
            current_prompt="Help me with authentication",
        )

        assert context is not None
        assert "Previous work on auth" in context

    @pytest.mark.asyncio
    async def test_includes_remaining_tasks(
        self, injector: ContextInjector, repository: MemoryRepository
    ) -> None:
        """Test context includes remaining tasks."""
        await repository.initialize_schema()

        summary = create_summary(
            title="Auth implementation",
            remaining_tasks=[
                TaskItem(description="Implement logout", status="open"),
            ],
        )
        await repository.save_session_summary(summary)

        context = await injector.get_context_for_session(
            user_id="user-1",
            current_prompt="What's pending?",
        )

        assert context is not None
        assert "Implement logout" in context

    @pytest.mark.asyncio
    async def test_includes_key_decisions(
        self, injector: ContextInjector, repository: MemoryRepository
    ) -> None:
        """Test context includes key decisions."""
        await repository.initialize_schema()

        summary = create_summary(
            title="Architecture decisions",
            key_decisions=["Use microservices pattern"],
        )
        await repository.save_session_summary(summary)

        context = await injector.get_context_for_session(
            user_id="user-1",
            current_prompt="What architecture did we choose?",
        )

        assert context is not None
        assert "microservices" in context

    @pytest.mark.asyncio
    async def test_includes_warnings(
        self, injector: ContextInjector, repository: MemoryRepository
    ) -> None:
        """Test context includes warnings."""
        await repository.initialize_schema()

        summary = create_summary(
            title="Database work",
            risks_or_warnings=["No indexes on user table"],
        )
        await repository.save_session_summary(summary)

        context = await injector.get_context_for_session(
            user_id="user-1",
            current_prompt="Any issues with the database?",
        )

        assert context is not None
        assert "indexes" in context

    @pytest.mark.asyncio
    async def test_user_isolation(
        self, injector: ContextInjector, repository: MemoryRepository
    ) -> None:
        """Test context is isolated per user."""
        await repository.initialize_schema()

        summary1 = create_summary(
            user_id="user-1",
            session_id="sess-1",
            title="User 1 work",
        )
        summary2 = create_summary(
            user_id="user-2",
            session_id="sess-2",
            title="User 2 work",
        )
        await repository.save_session_summary(summary1)
        await repository.save_session_summary(summary2)

        context = await injector.get_context_for_session(
            user_id="user-1",
            current_prompt="What did I work on?",
        )

        assert context is not None
        assert "User 1 work" in context
        assert "User 2 work" not in context

    @pytest.mark.asyncio
    async def test_project_filtering(
        self, injector: ContextInjector, repository: MemoryRepository
    ) -> None:
        """Test context filtering by project."""
        await repository.initialize_schema()

        summary1 = create_summary(
            session_id="sess-1",
            title="Project A work",
        )
        summary1 = SessionSummary(
            **{**summary1.model_dump(), "project_root": "/home/user/project-a"}
        )

        summary2 = create_summary(
            session_id="sess-2",
            title="Project B work",
        )
        summary2 = SessionSummary(
            **{**summary2.model_dump(), "project_root": "/home/user/project-b"}
        )

        await repository.save_session_summary(summary1)
        await repository.save_session_summary(summary2)

        context = await injector.get_context_for_session(
            user_id="user-1",
            current_prompt="What's happening in project A?",
            project_root="/home/user/project-a",
        )

        assert context is not None
        assert "Project A work" in context

    def test_format_context_for_injection(self, injector: ContextInjector) -> None:
        """Test context formatting for injection."""
        context = "Some prior context here"

        formatted = injector.format_context_for_injection(context)

        assert "<prior_session_context>" in formatted
        assert context in formatted
        assert "</prior_session_context>" in formatted

    def test_format_empty_context(self, injector: ContextInjector) -> None:
        """Test formatting empty context returns no-context marker per Req 8.11."""
        formatted = injector.format_context_for_injection("")

        # Per Req 8.11: When no context, insert marker
        assert formatted == "[NO_PRIOR_CONTEXT_PROVIDED]"

    def test_format_none_context(self, injector: ContextInjector) -> None:
        """Test formatting None context returns no-context marker per Req 8.11."""
        formatted = injector.format_context_for_injection(None)

        # Per Req 8.11: When no context, insert marker
        assert formatted == "[NO_PRIOR_CONTEXT_PROVIDED]"

    @pytest.mark.asyncio
    async def test_format_with_custom_template(self, temp_db_path: Path) -> None:
        """Test formatting with custom template."""
        config = MemoryConfiguration(
            available=True,
            database_path=str(temp_db_path),
            context_template="[CONTEXT]{context}[/CONTEXT]",
            require_project_discovery=False,
        )
        repo = MemoryRepository(config)
        try:
            injector = ContextInjector(config, repo)

            formatted = injector.format_context_for_injection("My context")

            assert formatted == "[CONTEXT]My context[/CONTEXT]"
        finally:
            await repo.close()

    @freeze_time("2024-01-01 12:00:00")
    def test_format_summaries(self, injector: ContextInjector) -> None:
        """Test summary formatting."""
        base_time = datetime.now(timezone.utc)
        summaries = [
            create_summary(
                title="First session",
                key_decisions=["Decision 1"],
                remaining_tasks=[TaskItem(description="Task 1", status="open")],
                base_time=base_time,
            ),
            create_summary(
                session_id="sess-2",
                title="Second session",
                base_time=base_time,
            ),
        ]

        formatted = injector._format_summaries(summaries)

        assert "Session 1" in formatted
        assert "Session 2" in formatted
        assert "First session" in formatted
        assert "Second session" in formatted
        assert "Decision 1" in formatted
        assert "Task 1" in formatted

    def test_build_simple_context(self, injector: ContextInjector) -> None:
        """Test simple context building without LLM."""
        summaries = [
            create_summary(
                title="Auth work",
                key_decisions=["Use JWT"],
                remaining_tasks=[TaskItem(description="Add logout", status="open")],
                risks_or_warnings=["Rate limiting needed"],
            ),
        ]

        context = injector._build_simple_context(summaries)

        assert "Prior Context:" in context
        assert "Auth work" in context
        assert "Add logout" in context
        assert "Use JWT" in context
        assert "Rate limiting" in context
