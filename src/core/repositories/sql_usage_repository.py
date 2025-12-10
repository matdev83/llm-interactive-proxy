"""SQL-based implementation of usage repository using SQLAlchemy."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select

from src.core.database.models.usage import UsageRecordTable
from src.core.domain.usage_data import UsageData
from src.core.interfaces.repositories_interface import IUsageRepository

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import async_sessionmaker

logger = logging.getLogger(__name__)


class SqlUsageRepository(IUsageRepository):
    """SQL-based implementation of usage repository.

    This repository persists usage data to a SQL database using SQLAlchemy.
    It is suitable for production use with proper persistence and querying.
    """

    def __init__(self, session_factory: async_sessionmaker) -> None:
        """Initialize the SQL usage repository.

        Args:
            session_factory: Async session factory from DatabaseEngine
        """
        self._session_factory = session_factory

    async def get_by_id(self, id: str) -> UsageData | None:
        """Get usage data by its ID."""
        async with self._session_factory() as session:
            result = await session.execute(
                select(UsageRecordTable).where(
                    UsageRecordTable.id == id  # type: ignore[arg-type]
                )
            )
            record = result.scalar_one_or_none()
            if record:
                return self._to_domain(record)
            return None

    async def get_all(self) -> list[UsageData]:
        """Get all usage data."""
        async with self._session_factory() as session:
            result = await session.execute(select(UsageRecordTable))
            records = result.scalars().all()
            return [self._to_domain(record) for record in records]

    async def add(self, entity: UsageData) -> UsageData:
        """Add new usage data."""
        async with self._session_factory() as session:
            record = self._from_domain(entity)
            session.add(record)
            await session.commit()
            await session.refresh(record)
            logger.debug(f"Added usage record: {entity.id}")
            return self._to_domain(record)

    async def update(self, entity: UsageData) -> UsageData:
        """Update existing usage data."""
        async with self._session_factory() as session:
            result = await session.execute(
                select(UsageRecordTable).where(
                    UsageRecordTable.id == entity.id  # type: ignore[arg-type]
                )
            )
            record = result.scalar_one_or_none()

            if record is None:
                # If doesn't exist, add it
                return await self.add(entity)

            # Update fields
            record.session_id = entity.session_id
            record.model = entity.model
            record.mutated_prompt_tokens = entity.prompt_tokens
            record.mutated_completion_tokens = entity.completion_tokens
            record.total_tokens = entity.total_tokens
            record.timestamp = entity.timestamp

            await session.commit()
            await session.refresh(record)
            logger.debug(f"Updated usage record: {entity.id}")
            return self._to_domain(record)

    async def delete(self, id: str) -> bool:
        """Delete usage data by its ID."""
        async with self._session_factory() as session:
            result = await session.execute(
                select(UsageRecordTable).where(
                    UsageRecordTable.id == id  # type: ignore[arg-type]
                )
            )
            record = result.scalar_one_or_none()

            if record:
                await session.delete(record)
                await session.commit()
                logger.debug(f"Deleted usage record: {id}")
                return True
            return False

    async def get_by_session_id(self, session_id: str) -> list[UsageData]:
        """Get all usage data for a specific session."""
        async with self._session_factory() as session:
            result = await session.execute(
                select(UsageRecordTable)
                .where(
                    UsageRecordTable.session_id == session_id  # type: ignore[arg-type]
                )
                .order_by(UsageRecordTable.timestamp)  # type: ignore[arg-type]
            )
            records = result.scalars().all()
            return [self._to_domain(record) for record in records]

    async def get_stats(self, project: str | None = None) -> dict[str, Any]:
        """Get usage statistics, optionally filtered by project."""
        async with self._session_factory() as session:
            # Build query for aggregated stats by model
            # Note: mypy doesn't understand SQLAlchemy column types properly
            query = select(  # type: ignore[call-overload]
                UsageRecordTable.model,
                func.sum(UsageRecordTable.total_tokens).label("total_tokens"),
                func.sum(UsageRecordTable.mutated_prompt_tokens).label("prompt_tokens"),
                func.sum(UsageRecordTable.mutated_completion_tokens).label(
                    "completion_tokens"
                ),
                func.count(UsageRecordTable.id).label("requests"),  # type: ignore[arg-type]
            ).group_by(UsageRecordTable.model)

            # Note: project filtering not implemented in UsageRecordTable yet
            # If project field is added to the table, add filter here:
            # if project:
            #     query = query.where(UsageRecordTable.project == project)

            result = await session.execute(query)
            rows = result.all()

            stats: dict[str, Any] = {}
            for row in rows:
                model_name = str(row[0]) if row[0] is not None else "unknown"
                stats[model_name] = {
                    "total_tokens": row[1] or 0,
                    "prompt_tokens": row[2] or 0,
                    "completion_tokens": row[3] or 0,
                    "cost": 0.0,  # Cost calculation to be implemented
                    "requests": row[4] or 0,
                }

            return stats

    def _to_domain(self, record: UsageRecordTable) -> UsageData:
        """Convert database record to domain model."""
        return UsageData(
            id=record.id,
            session_id=record.session_id,
            project=None,  # Project field not in UsageRecordTable yet
            model=record.model,
            prompt_tokens=record.mutated_prompt_tokens,
            completion_tokens=record.mutated_completion_tokens,
            total_tokens=record.total_tokens,
            cost=None,  # Cost calculation to be implemented
            timestamp=record.timestamp,
        )

    def _from_domain(self, entity: UsageData) -> UsageRecordTable:
        """Convert domain model to database record."""
        return UsageRecordTable(
            id=entity.id,
            session_id=entity.session_id,
            model=entity.model,
            backend_type="unknown",  # Default, should be passed if available
            frontend_type="unknown",  # Default, should be passed if available
            leg="PTC",  # Default value
            mutated_prompt_tokens=entity.prompt_tokens,
            mutated_completion_tokens=entity.completion_tokens,
            total_tokens=entity.total_tokens,
            timestamp=entity.timestamp,
        )
