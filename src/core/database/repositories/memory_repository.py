"""SQLModel repository for memory/ProxyMem feature."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import TYPE_CHECKING

from sqlmodel import select

from src.core.database.models.memory import (
    SessionSummaryTable,
    UserProjectDirTable,
)
from src.core.database.repositories.base import AsyncRepository
from src.core.memory.models import (
    FileChange,
    GitOperation,
    SessionSummary,
    TaskItem,
    TestRun,
)

if TYPE_CHECKING:
    from src.core.database.engine import DatabaseEngine

logger = logging.getLogger(__name__)


class SQLModelMemoryRepository(AsyncRepository[SessionSummaryTable]):
    """SQLModel-based repository for memory data persistence.

    Implements IMemoryRepository interface using SQLModel.
    """

    def __init__(self, engine: DatabaseEngine) -> None:
        """Initialize memory repository.

        Args:
            engine: Database engine for session creation
        """
        super().__init__(engine)
        self._initialized = False

    @property
    def model_class(self) -> type[SessionSummaryTable]:
        """Return the SQLModel class this repository manages."""
        return SessionSummaryTable

    async def initialize_schema(self) -> None:
        """Initialize database schema.

        With SQLModel, this is handled by DatabaseEngine.initialize().
        This method exists for interface compatibility.
        """
        await self._engine.initialize()
        self._initialized = True
        logger.info("Memory repository schema initialized")

    async def save_session_summary(self, summary: SessionSummary) -> None:
        """Persist a session summary to the database.

        Args:
            summary: SessionSummary domain model to persist
        """
        if not self._initialized:
            await self.initialize_schema()

        # Convert domain model to table model
        table_record = SessionSummaryTable(
            id=summary.id,
            user_id=summary.user_id,
            tenant_id=summary.tenant_id,
            project_id=summary.project_id,
            project_root=summary.project_root,
            session_id=summary.session_id,
            session_start=summary.session_start,
            client_agent=summary.client_agent,
            backend_model=summary.backend_model,
            title=summary.title,
            scope=summary.scope,
            goals=json.dumps(summary.goals),
            modified_files=json.dumps([f.model_dump() for f in summary.modified_files]),
            remaining_tasks=json.dumps(
                [t.model_dump() for t in summary.remaining_tasks]
            ),
            git_operations=json.dumps([g.model_dump() for g in summary.git_operations]),
            operations_performed=json.dumps(summary.operations_performed),
            open_questions=json.dumps(summary.open_questions),
            tests_run=json.dumps([t.model_dump() for t in summary.tests_run]),
            errors=json.dumps(summary.errors),
            branch=summary.branch,
            head_sha=summary.head_sha,
            completion_status=summary.completion_status,
            key_decisions=json.dumps(summary.key_decisions),
            risks_or_warnings=json.dumps(summary.risks_or_warnings),
            evidence=json.dumps(summary.evidence),
            full_analysis=summary.full_analysis,
            summary_version=summary.summary_version,
            created_at=summary.created_at,
        )

        async with self._engine.session() as session:
            # Use merge for upsert behavior
            await session.merge(table_record)

        logger.debug(
            "Saved session summary %s for user %s", summary.id, summary.user_id
        )

    async def get_recent_sessions(
        self,
        user_id: str,
        limit: int,
        tenant_id: str | None = None,
        project_id: str | None = None,
        project_root: str | None = None,
    ) -> list[SessionSummary]:
        """Retrieve recent session summaries for a user.

        Args:
            user_id: User identifier
            limit: Maximum number of sessions to return
            tenant_id: Optional tenant filter
            project_id: Optional project ID filter
            project_root: Optional project root filter (used if project_id not set)

        Returns:
            List of SessionSummary domain models
        """
        if not self._initialized:
            await self.initialize_schema()

        async with self._engine.session() as session:
            # Build query
            statement = select(SessionSummaryTable).where(
                SessionSummaryTable.user_id == user_id
            )

            if tenant_id is not None:
                statement = statement.where(SessionSummaryTable.tenant_id == tenant_id)

            if project_id is not None:
                statement = statement.where(
                    SessionSummaryTable.project_id == project_id
                )
            elif project_root is not None:
                statement = statement.where(
                    SessionSummaryTable.project_root == project_root
                )

            statement = statement.order_by(
                SessionSummaryTable.session_start.desc()  # type: ignore[attr-defined]
            ).limit(limit)

            result = await session.execute(statement)
            rows = result.scalars().all()

            return [self._table_to_domain(row) for row in rows]

    async def delete_old_sessions(self, before_date: datetime) -> int:
        """Delete sessions older than the specified date.

        Args:
            before_date: Delete sessions before this date

        Returns:
            Number of deleted records
        """
        if not self._initialized:
            await self.initialize_schema()

        async with self._engine.session() as session:
            statement = select(SessionSummaryTable).where(
                SessionSummaryTable.session_start < before_date
            )
            result = await session.execute(statement)
            rows = list(result.scalars().all())

            for row in rows:
                await session.delete(row)

            deleted = len(rows)
            if deleted > 0:
                logger.info("Deleted %d old session summaries", deleted)
            return deleted

    async def get_or_create_project_id(self, user_id: str, project_root: str) -> str:
        """Get or create a stable project_id for a user+project_root pair.

        Args:
            user_id: User identifier
            project_root: Project root path

        Returns:
            Stable project ID string
        """
        if not self._initialized:
            await self.initialize_schema()

        async with self._engine.session() as session:
            # Check if exists
            statement = select(UserProjectDirTable).where(
                UserProjectDirTable.user_id == user_id,
                UserProjectDirTable.project_root == project_root,
            )
            result = await session.execute(statement)
            existing = result.scalar_one_or_none()

            if existing:
                return f"proj-{existing.id}"

            # Create new
            new_record = UserProjectDirTable(
                user_id=user_id,
                project_root=project_root,
            )
            session.add(new_record)
            await session.flush()
            await session.refresh(new_record)
            return f"proj-{new_record.id}"

    async def close(self) -> None:
        """Close the repository (for graceful shutdown)."""
        # Engine lifecycle is managed by DatabaseEngine

    def _table_to_domain(self, row: SessionSummaryTable) -> SessionSummary:
        """Convert a table model to a domain model.

        Args:
            row: Database table row

        Returns:
            SessionSummary domain model
        """
        return SessionSummary(
            id=row.id,
            user_id=row.user_id,
            tenant_id=row.tenant_id,
            project_id=row.project_id,
            project_root=row.project_root,
            session_id=row.session_id,
            session_start=row.session_start,
            client_agent=row.client_agent,
            backend_model=row.backend_model,
            title=row.title,
            scope=row.scope or "",
            goals=json.loads(row.goals or "[]"),
            open_questions=json.loads(row.open_questions or "[]"),
            remaining_tasks=[
                TaskItem(**t) for t in json.loads(row.remaining_tasks or "[]")
            ],
            modified_files=[
                FileChange(**f) for f in json.loads(row.modified_files or "[]")
            ],
            git_operations=[
                GitOperation(**g) for g in json.loads(row.git_operations or "[]")
            ],
            completion_status=row.completion_status or "partial",
            key_decisions=json.loads(row.key_decisions or "[]"),
            operations_performed=json.loads(row.operations_performed or "[]"),
            tests_run=[TestRun(**t) for t in json.loads(row.tests_run or "[]")],
            errors=json.loads(row.errors or "[]"),
            risks_or_warnings=json.loads(row.risks_or_warnings or "[]"),
            evidence=json.loads(row.evidence or "[]"),
            full_analysis=row.full_analysis or "",
            branch=row.branch,
            head_sha=row.head_sha,
            summary_version=row.summary_version,
            created_at=row.created_at,
        )
