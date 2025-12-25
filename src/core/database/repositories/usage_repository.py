"""Repository for usage records with batch operations and filtering.

This module provides the UsageRecordRepository for CRUD operations
on usage records with support for batch inserts and filtered queries.

Note: This module has mypy type: ignore[arg-type] comments on SQLAlchemy
comparison operations due to type inference limitations with SQLModel/SQLAlchemy.
These are false positives - the comparisons work correctly at runtime.
"""

# mypy: disable-error-code="arg-type,attr-defined,union-attr,call-overload"
from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import func, select, update

from src.core.database.models.usage import SessionMetricsTable, UsageRecordTable
from src.core.database.repositories.base import AsyncRepository
from src.core.database.repositories.usage_repository_types import (
    RepositoryAggregatedStats,
    RepositoryUsageStats,
)
from src.core.domain.statistics_filter import StatisticsFilter
from src.core.domain.usage_record import UsageRecord

if TYPE_CHECKING:
    from src.core.database.engine import DatabaseEngine

logger = logging.getLogger(__name__)


class UsageRecordRepository(AsyncRepository[UsageRecordTable]):
    """Repository for usage record CRUD operations.

    Provides batch operations for efficient database writes and
    filtered queries for statistics aggregation.
    """

    def __init__(self, engine: DatabaseEngine) -> None:
        """Initialize the repository.

        Args:
            engine: Database engine for session creation
        """
        super().__init__(engine)

    @property
    def model_class(self) -> type[UsageRecordTable]:
        """Return the model class."""
        return UsageRecordTable

    async def batch_insert(self, records: list[UsageRecord]) -> int:
        """Insert multiple records in a single transaction.

        Args:
            records: List of domain UsageRecord instances to insert

        Returns:
            Number of records successfully inserted
        """
        if not records:
            return 0

        async with self._engine.session() as session:
            try:
                # Convert domain records to table models
                table_records = [
                    UsageRecordTable.from_domain(record) for record in records
                ]

                # Add all in bulk
                session.add_all(table_records)
                await session.flush()

                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug("Batch inserted %d usage records", len(records))

                return len(records)

            except Exception as e:
                logger.error("Failed to batch insert records: %s", e, exc_info=True)
                raise

    async def batch_update(self, records: list[UsageRecord]) -> int:
        """Update multiple records in a single transaction.

        Args:
            records: List of domain UsageRecord instances to update

        Returns:
            Number of records successfully updated
        """
        if not records:
            return 0

        async with self._engine.session() as session:
            try:
                updated_count = 0

                for record in records:
                    # Get existing record
                    existing = await session.get(UsageRecordTable, record.id)
                    if existing:
                        # Update from domain record
                        table_record = UsageRecordTable.from_domain(record)

                        # Copy all fields
                        existing.timestamp = table_record.timestamp
                        existing.session_id = table_record.session_id
                        existing.turn_number = table_record.turn_number
                        existing.backend_type = table_record.backend_type
                        existing.backend_instance_id = table_record.backend_instance_id
                        existing.model = table_record.model
                        existing.frontend_type = table_record.frontend_type
                        existing.leg = table_record.leg
                        existing.verbatim_prompt_tokens = (
                            table_record.verbatim_prompt_tokens
                        )
                        existing.verbatim_completion_tokens = (
                            table_record.verbatim_completion_tokens
                        )
                        existing.mutated_prompt_tokens = (
                            table_record.mutated_prompt_tokens
                        )
                        existing.mutated_completion_tokens = (
                            table_record.mutated_completion_tokens
                        )
                        existing.total_tokens = table_record.total_tokens
                        existing.backend_reported_usage_json = (
                            table_record.backend_reported_usage_json
                        )
                        existing.http_status_code = table_record.http_status_code
                        existing.tool_call_count = table_record.tool_call_count
                        existing.native_tool_call_count = (
                            table_record.native_tool_call_count
                        )
                        existing.vtc_tool_call_count = table_record.vtc_tool_call_count
                        existing.tool_names_json = table_record.tool_names_json
                        existing.ttft_ms = table_record.ttft_ms
                        existing.stream_tps = table_record.stream_tps
                        existing.backend_wait_ms = table_record.backend_wait_ms
                        existing.proxy_processing_ms = table_record.proxy_processing_ms
                        existing.total_duration_ms = table_record.total_duration_ms
                        existing.user_agent = table_record.user_agent
                        existing.app_title = table_record.app_title
                        existing.proxy_user = table_record.proxy_user

                        session.add(existing)
                        updated_count += 1

                await session.flush()

                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug("Batch updated %d usage records", updated_count)

                return updated_count

            except Exception as e:
                logger.error("Failed to batch update records: %s", e, exc_info=True)
                raise

    async def get_by_id_domain(self, record_id: str) -> UsageRecord | None:
        """Get a record by ID and return as domain object.

        Args:
            record_id: Record ID

        Returns:
            Domain UsageRecord or None if not found
        """
        table_record = await self.get_by_id(record_id)
        if table_record:
            return table_record.to_domain()
        return None

    async def query_with_filter(
        self,
        filters: StatisticsFilter | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[UsageRecord]:
        """Query records with filters and return domain objects.

        Args:
            filters: Optional statistics filter
            limit: Maximum records to return
            offset: Number of records to skip

        Returns:
            List of domain UsageRecord instances
        """
        async with self._engine.session() as session:
            statement = select(UsageRecordTable)

            # Apply filters
            if filters:
                statement = self._apply_filters(statement, filters)

            # Apply ordering (most recent first)
            statement = statement.order_by(UsageRecordTable.timestamp.desc())

            # Apply pagination
            if offset:
                statement = statement.offset(offset)
            if limit:
                statement = statement.limit(limit)

            result = await session.execute(statement)
            table_records = result.scalars().all()

            return [record.to_domain() for record in table_records]

    async def count_with_filter(self, filters: StatisticsFilter | None = None) -> int:
        """Count records matching the filter.

        Args:
            filters: Optional statistics filter

        Returns:
            Count of matching records
        """
        async with self._engine.session() as session:
            statement = select(func.count()).select_from(UsageRecordTable)

            if filters:
                # Apply where clauses directly
                if filters.backend_type:
                    statement = statement.where(
                        UsageRecordTable.backend_type == filters.backend_type
                    )
                if filters.model:
                    statement = statement.where(UsageRecordTable.model == filters.model)
                if filters.frontend_type:
                    statement = statement.where(
                        UsageRecordTable.frontend_type == filters.frontend_type
                    )
                if filters.leg:
                    statement = statement.where(
                        UsageRecordTable.leg == filters.leg.value
                    )
                if filters.proxy_user:
                    statement = statement.where(
                        UsageRecordTable.proxy_user == filters.proxy_user
                    )
                if filters.http_status_code:
                    statement = statement.where(
                        UsageRecordTable.http_status_code == filters.http_status_code
                    )
                if filters.start_date:
                    statement = statement.where(
                        UsageRecordTable.timestamp >= filters.start_date
                    )
                if filters.end_date:
                    statement = statement.where(
                        UsageRecordTable.timestamp <= filters.end_date
                    )

            result = await session.execute(statement)
            return result.scalar() or 0

    async def get_aggregated_stats(
        self, filters: StatisticsFilter | None = None
    ) -> RepositoryAggregatedStats:
        """Get aggregated statistics from the database.

        This performs aggregation directly in SQL for efficiency.

        Args:
            filters: Optional statistics filter

        Returns:
            RepositoryAggregatedStats with aggregated statistics
        """
        async with self._engine.session() as session:
            # Base query for aggregations
            statement = select(
                func.count().label("request_count"),
                func.count(UsageRecordTable.http_status_code).label("response_count"),
                func.count(func.distinct(UsageRecordTable.session_id)).label(
                    "unique_sessions"
                ),
                func.sum(UsageRecordTable.turn_number).label("total_turns"),
                func.sum(UsageRecordTable.mutated_prompt_tokens).label(
                    "total_prompt_tokens"
                ),
                func.sum(UsageRecordTable.mutated_completion_tokens).label(
                    "total_completion_tokens"
                ),
                func.sum(UsageRecordTable.total_tokens).label("total_tokens"),
                func.sum(UsageRecordTable.tool_call_count).label("total_tool_calls"),
                func.min(UsageRecordTable.timestamp).label("first_timestamp"),
                func.max(UsageRecordTable.timestamp).label("last_timestamp"),
                # Timing aggregates
                func.min(UsageRecordTable.ttft_ms).label("min_ttft"),
                func.max(UsageRecordTable.ttft_ms).label("max_ttft"),
                func.avg(UsageRecordTable.ttft_ms).label("avg_ttft"),
                func.min(UsageRecordTable.proxy_processing_ms).label(
                    "min_proxy_processing"
                ),
                func.max(UsageRecordTable.proxy_processing_ms).label(
                    "max_proxy_processing"
                ),
                func.avg(UsageRecordTable.proxy_processing_ms).label(
                    "avg_proxy_processing"
                ),
                func.min(UsageRecordTable.total_duration_ms).label("min_duration"),
                func.max(UsageRecordTable.total_duration_ms).label("max_duration"),
                func.avg(UsageRecordTable.total_duration_ms).label("avg_duration"),
            ).select_from(UsageRecordTable)

            # Apply filters
            if filters:
                if filters.backend_type:
                    statement = statement.where(
                        UsageRecordTable.backend_type == filters.backend_type
                    )
                if filters.model:
                    statement = statement.where(UsageRecordTable.model == filters.model)
                if filters.frontend_type:
                    statement = statement.where(
                        UsageRecordTable.frontend_type == filters.frontend_type
                    )
                if filters.leg:
                    statement = statement.where(
                        UsageRecordTable.leg == filters.leg.value
                    )
                if filters.proxy_user:
                    statement = statement.where(
                        UsageRecordTable.proxy_user == filters.proxy_user
                    )
                if filters.http_status_code:
                    statement = statement.where(
                        UsageRecordTable.http_status_code == filters.http_status_code
                    )
                if filters.start_date:
                    statement = statement.where(
                        UsageRecordTable.timestamp >= filters.start_date
                    )
                if filters.end_date:
                    statement = statement.where(
                        UsageRecordTable.timestamp <= filters.end_date
                    )

            result = await session.execute(statement)
            row = result.one()

            return RepositoryAggregatedStats(
                request_count=row.request_count or 0,
                response_count=row.response_count or 0,
                unique_sessions=row.unique_sessions or 0,
                total_turns=row.total_turns or 0,
                total_prompt_tokens=row.total_prompt_tokens or 0,
                total_completion_tokens=row.total_completion_tokens or 0,
                total_tokens=row.total_tokens or 0,
                total_tool_calls=row.total_tool_calls or 0,
                first_timestamp=row.first_timestamp,
                last_timestamp=row.last_timestamp,
                min_ttft=row.min_ttft,
                max_ttft=row.max_ttft,
                avg_ttft=row.avg_ttft,
                min_proxy_processing=row.min_proxy_processing,
                max_proxy_processing=row.max_proxy_processing,
                avg_proxy_processing=row.avg_proxy_processing,
                min_duration=row.min_duration,
                max_duration=row.max_duration,
                avg_duration=row.avg_duration,
            )


    async def get_status_code_breakdown(
        self, filters: StatisticsFilter | None = None
    ) -> dict[str, dict[int, int]]:
        """Get status code counts by backend_instance_id:model.

        Args:
            filters: Optional statistics filter

        Returns:
            Dictionary mapping "backend_instance_id:model" to status code counts
        """
        async with self._engine.session() as session:
            statement = select(
                UsageRecordTable.backend_instance_id,
                UsageRecordTable.backend_type,
                UsageRecordTable.model,
                UsageRecordTable.http_status_code,
                func.count().label("count"),
            ).where(UsageRecordTable.http_status_code.isnot(None))

            # Apply filters
            if filters:
                if filters.backend_type:
                    statement = statement.where(
                        UsageRecordTable.backend_type == filters.backend_type
                    )
                if filters.backend_instance_id:
                    statement = statement.where(
                        UsageRecordTable.backend_instance_id
                        == filters.backend_instance_id
                    )
                if filters.model:
                    statement = statement.where(UsageRecordTable.model == filters.model)
                if filters.start_date:
                    statement = statement.where(
                        UsageRecordTable.timestamp >= filters.start_date
                    )
                if filters.end_date:
                    statement = statement.where(
                        UsageRecordTable.timestamp <= filters.end_date
                    )

            statement = statement.group_by(
                UsageRecordTable.backend_instance_id,
                UsageRecordTable.backend_type,
                UsageRecordTable.model,
                UsageRecordTable.http_status_code,
            )

            result = await session.execute(statement)
            rows = result.all()

            breakdown: dict[str, dict[int, int]] = {}
            for row in rows:
                # Prefer backend_instance_id if available, fallback to backend_type
                instance_id = row.backend_instance_id or row.backend_type
                key = f"{instance_id}:{row.model}"
                if key not in breakdown:
                    breakdown[key] = {}
                breakdown[key][row.http_status_code] = row.count

            return breakdown

    async def get_frontend_stats(
        self, filters: StatisticsFilter | None = None
    ) -> dict[str, RepositoryUsageStats]:
        """Get request counts and token totals by frontend type.

        Args:
            filters: Optional statistics filter

        Returns:
            Dictionary mapping frontend_type to RepositoryUsageStats
        """
        async with self._engine.session() as session:
            statement = select(
                UsageRecordTable.frontend_type,
                func.count().label("total_requests"),
                func.sum(
                    func.case(
                        (UsageRecordTable.http_status_code == 200, 1),
                        else_=0,
                    )
                ).label("successful_requests"),
                func.sum(UsageRecordTable.mutated_prompt_tokens).label("tokens_sent"),
                func.sum(UsageRecordTable.mutated_completion_tokens).label(
                    "tokens_received"
                ),
            )

            if filters:
                statement = self._apply_filters(statement, filters)

            statement = statement.group_by(UsageRecordTable.frontend_type)

            result = await session.execute(statement)
            rows = result.all()

            stats: dict[str, RepositoryUsageStats] = {}
            for row in rows:
                stats[row.frontend_type] = RepositoryUsageStats(
                    total_requests=row.total_requests or 0,
                    successful_requests=row.successful_requests or 0,
                    tokens_sent=row.tokens_sent or 0,
                    tokens_received=row.tokens_received or 0,
                )

            return stats

    async def get_backend_instance_stats(
        self, filters: StatisticsFilter | None = None
    ) -> dict[str, RepositoryUsageStats]:
        """Get request counts and token totals by backend instance.

        Args:
            filters: Optional statistics filter

        Returns:
            Dictionary mapping backend_instance_id to RepositoryUsageStats
        """
        async with self._engine.session() as session:
            statement = select(
                UsageRecordTable.backend_instance_id,
                UsageRecordTable.backend_type,
                func.count().label("total_requests"),
                func.sum(
                    func.case(
                        (UsageRecordTable.http_status_code == 200, 1),
                        else_=0,
                    )
                ).label("successful_requests"),
                func.sum(UsageRecordTable.mutated_prompt_tokens).label("tokens_sent"),
                func.sum(UsageRecordTable.mutated_completion_tokens).label(
                    "tokens_received"
                ),
            )

            if filters:
                statement = self._apply_filters(statement, filters)

            statement = statement.group_by(
                UsageRecordTable.backend_instance_id,
                UsageRecordTable.backend_type,
            )

            result = await session.execute(statement)
            rows = result.all()

            stats: dict[str, RepositoryUsageStats] = {}
            for row in rows:
                # Prefer backend_instance_id if available, fallback to backend_type
                instance_id = row.backend_instance_id or row.backend_type
                stats[instance_id] = RepositoryUsageStats(
                    total_requests=row.total_requests or 0,
                    successful_requests=row.successful_requests or 0,
                    tokens_sent=row.tokens_sent or 0,
                    tokens_received=row.tokens_received or 0,
                )

            return stats


    async def delete_older_than(self, cutoff_date: datetime) -> int:
        """Delete records older than the cutoff date.

        Args:
            cutoff_date: Delete records with timestamp before this date

        Returns:
            Number of records deleted
        """
        async with self._engine.session() as session:
            from sqlalchemy import delete

            statement = delete(UsageRecordTable).where(
                UsageRecordTable.timestamp < cutoff_date
            )
            result = await session.execute(statement)
            await session.commit()

            deleted_count = result.rowcount
            logger.info(
                "Deleted %d usage records older than %s",
                deleted_count,
                cutoff_date.isoformat(),
            )
            return deleted_count

    def _apply_filters(self, statement, filters: StatisticsFilter):
        """Apply filters to a select statement.

        Args:
            statement: SQLAlchemy select statement
            filters: Statistics filter

        Returns:
            Modified statement with filters applied
        """
        if filters.backend_type:
            statement = statement.where(
                UsageRecordTable.backend_type == filters.backend_type
            )
        if filters.backend_instance_id:
            statement = statement.where(
                UsageRecordTable.backend_instance_id == filters.backend_instance_id
            )
        if filters.model:
            statement = statement.where(UsageRecordTable.model == filters.model)
        if filters.frontend_type:
            statement = statement.where(
                UsageRecordTable.frontend_type == filters.frontend_type
            )
        if filters.leg:
            statement = statement.where(UsageRecordTable.leg == filters.leg.value)
        if filters.user_agent:
            statement = statement.where(
                UsageRecordTable.user_agent.contains(filters.user_agent)
            )
        if filters.proxy_user:
            statement = statement.where(
                UsageRecordTable.proxy_user == filters.proxy_user
            )
        if filters.start_date:
            statement = statement.where(
                UsageRecordTable.timestamp >= filters.start_date
            )
        if filters.end_date:
            statement = statement.where(UsageRecordTable.timestamp <= filters.end_date)
        if filters.day_of_week is not None:
            # SQLite uses strftime, PostgreSQL uses EXTRACT
            # This is SQLite-compatible
            statement = statement.where(
                func.strftime("%w", UsageRecordTable.timestamp)
                == str(filters.day_of_week)
            )
        if filters.hour_of_day is not None:
            statement = statement.where(
                func.strftime("%H", UsageRecordTable.timestamp)
                == f"{filters.hour_of_day:02d}"
            )
        if filters.http_status_code:
            statement = statement.where(
                UsageRecordTable.http_status_code == filters.http_status_code
            )

        return statement


class SessionMetricsRepository(AsyncRepository[SessionMetricsTable]):
    """Repository for session metrics CRUD operations."""

    def __init__(self, engine: DatabaseEngine) -> None:
        """Initialize the repository.

        Args:
            engine: Database engine for session creation
        """
        super().__init__(engine)

    @property
    def model_class(self) -> type[SessionMetricsTable]:
        """Return the model class."""
        return SessionMetricsTable

    async def upsert(self, metrics: SessionMetricsTable) -> SessionMetricsTable:
        """Insert or update session metrics.

        Args:
            metrics: Session metrics to upsert

        Returns:
            The upserted metrics
        """
        async with self._engine.session() as session:
            existing = await session.get(SessionMetricsTable, metrics.session_id)
            if existing:
                # Update
                existing.last_activity = metrics.last_activity
                existing.turn_count = metrics.turn_count
                existing.total_tokens = metrics.total_tokens
                existing.total_tool_calls = metrics.total_tool_calls
                existing.is_completed = metrics.is_completed
                existing.backend_type = metrics.backend_type
                existing.model = metrics.model
                existing.proxy_user = metrics.proxy_user
                # Update EoS fields if provided
                if metrics.eos_emitted_at is not None:
                    existing.eos_emitted_at = metrics.eos_emitted_at
                if metrics.eos_signal_type is not None:
                    existing.eos_signal_type = metrics.eos_signal_type
                if metrics.eos_reason is not None:
                    existing.eos_reason = metrics.eos_reason
                session.add(existing)
                await session.flush()
                return existing
            else:
                # Insert
                session.add(metrics)
                await session.flush()
                await session.refresh(metrics)
                return metrics

    async def get_active_sessions(
        self, since: datetime, limit: int = 100
    ) -> list[SessionMetricsTable]:
        """Get active sessions since a given time.

        Args:
            since: Get sessions active since this time
            limit: Maximum sessions to return

        Returns:
            List of session metrics
        """
        async with self._engine.session() as session:
            statement = (
                select(SessionMetricsTable)
                .where(SessionMetricsTable.last_activity >= since)
                .where(SessionMetricsTable.is_completed == False)
                .order_by(SessionMetricsTable.last_activity.desc())
                .limit(limit)
            )
            result = await session.execute(statement)
            return list(result.scalars().all())

    async def claim_eos_emission(
        self,
        session_id: str,
        emitted_at: datetime,
        signal_type: str,
        reason: str | None = None,
    ) -> bool:
        """Atomically claim the right to emit EoS event for a session.

        This method performs an atomic conditional update that only succeeds
        if eos_emitted_at is NULL, ensuring at-most-once emission per session.

        Precondition: Session metrics record must exist for the given session_id.
        If the record doesn't exist, the claim will fail (return False) as no rows
        will be updated. The caller should ensure session metrics are created before
        attempting to claim EoS emission.

        Args:
            session_id: Session identifier
            emitted_at: Timestamp when EoS event is emitted
            signal_type: Type of signal that triggered EoS (e.g., "done_sentinel")
            reason: Optional reason/context for the EoS event

        Returns:
            True if claim succeeded (first emission), False if already claimed or
            session metrics don't exist

        Raises:
            Database errors are logged and re-raised for upstream handling.
        """
        async with self._engine.session() as session:
            try:
                # Atomic conditional update: only update if eos_emitted_at IS NULL
                # Also set is_completed=True per design.md requirement for restart-safe
                # idempotency using both is_completed and eos_emitted_at
                statement = (
                    update(SessionMetricsTable)
                    .where(SessionMetricsTable.session_id == session_id)
                    .where(SessionMetricsTable.eos_emitted_at.is_(None))
                    .values(
                        eos_emitted_at=emitted_at,
                        eos_signal_type=signal_type,
                        eos_reason=reason,
                        is_completed=True,
                    )
                )
                result = await session.execute(statement)

                # Return True if any row was updated (claim succeeded)
                # Context manager handles commit automatically
                return result.rowcount > 0
            except Exception as e:
                logger.error(
                    "Failed to claim EoS emission for session %s: %s",
                    session_id,
                    e,
                    exc_info=True,
                )
                raise

    async def has_ended(self, session_id: str) -> bool:
        """Check if EoS event has been emitted for a session.

        Fast check for hot-path dedupe. Returns True if eos_emitted_at is not NULL.
        Returns False if the session doesn't exist or hasn't ended.

        Args:
            session_id: Session identifier

        Returns:
            True if session has ended (EoS event emitted), False otherwise
            (including when session metrics don't exist)

        Raises:
            Database errors are logged and re-raised for upstream handling.
        """
        async with self._engine.session() as session:
            try:
                statement = select(SessionMetricsTable.eos_emitted_at).where(
                    SessionMetricsTable.session_id == session_id
                )
                result = await session.execute(statement)
                eos_emitted_at = result.scalar_one_or_none()

                return eos_emitted_at is not None
            except Exception as e:
                logger.error(
                    "Failed to check EoS status for session %s: %s",
                    session_id,
                    e,
                    exc_info=True,
                )
                raise
