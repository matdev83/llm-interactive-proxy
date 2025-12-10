"""SQL-based storage for usage records with database persistence.

This module provides the SqlUsageStore class which persists usage records
to a SQL database using SQLAlchemy, compatible with InMemoryUsageStore interface.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.core.database.models.usage import UsageRecordTable
from src.core.domain.statistics_filter import StatisticsFilter
from src.core.domain.usage_record import UsageRecord

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import async_sessionmaker

logger = logging.getLogger(__name__)


class SqlUsageStore:
    """SQL-based storage for usage records.

    Provides the same interface as InMemoryUsageStore but persists to database.
    All operations are synchronous but use async database calls internally.

    Attributes:
        _session_factory: SQLAlchemy async session factory
    """

    def __init__(self, session_factory: async_sessionmaker):
        """Initialize the SQL usage store.

        Args:
            session_factory: SQLAlchemy async session factory from DatabaseEngine
        """
        self._session_factory = session_factory

    def add_record(self, record: UsageRecord) -> None:
        """Add a usage record to the store.

        Args:
            record: Usage record to add
        """
        import asyncio

        # Get or create event loop
        try:
            loop = asyncio.get_running_loop()
            # If we're in an event loop, schedule the task
            # Store reference to avoid RUF006 warning
            task = loop.create_task(self._add_record_async(record))
            # Add done callback to handle any errors
            task.add_done_callback(lambda t: t.exception() if t.done() else None)
        except RuntimeError:
            # No event loop running, create a new one
            asyncio.run(self._add_record_async(record))

    async def _add_record_async(self, record: UsageRecord) -> None:
        """Async implementation of add_record."""
        async with self._session_factory() as session:
            db_record = UsageRecordTable.from_domain(record)
            session.add(db_record)
            await session.commit()
            logger.debug(f"Added usage record to database: {record.id}")

    def get_records(self, filters: StatisticsFilter | None = None) -> list[UsageRecord]:
        """Get usage records matching the filter.

        Args:
            filters: Optional filter to apply. If None, returns all records.

        Returns:
            List of usage records matching the filter
        """
        import asyncio
        import concurrent.futures

        try:
            asyncio.get_running_loop()
            # We're in an async context, but this method is sync
            # Use run_in_executor to avoid blocking
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, self._get_records_async(filters))
                return future.result()
        except RuntimeError:
            # No event loop, safe to use asyncio.run
            return asyncio.run(self._get_records_async(filters))

    async def _get_records_async(
        self, filters: StatisticsFilter | None
    ) -> list[UsageRecord]:
        """Async implementation of get_records."""
        from sqlalchemy import select

        async with self._session_factory() as session:
            query = select(UsageRecordTable)

            # Apply filters
            # Note: SQLAlchemy column comparisons return ColumnElement, not bool
            # mypy doesn't understand this, so we use type: ignore comments
            if filters:
                if filters.backend_type:
                    query = query.where(
                        UsageRecordTable.backend_type == filters.backend_type  # type: ignore[arg-type]
                    )
                if filters.model:
                    query = query.where(UsageRecordTable.model == filters.model)  # type: ignore[arg-type]
                if filters.frontend_type:
                    query = query.where(
                        UsageRecordTable.frontend_type == filters.frontend_type  # type: ignore[arg-type]
                    )
                if filters.leg:
                    query = query.where(UsageRecordTable.leg == filters.leg.value)  # type: ignore[arg-type]
                if filters.http_status_code:
                    query = query.where(
                        UsageRecordTable.http_status_code == filters.http_status_code  # type: ignore[arg-type]
                    )
                if filters.proxy_user:
                    query = query.where(
                        UsageRecordTable.proxy_user == filters.proxy_user  # type: ignore[arg-type]
                    )
                if filters.start_date:
                    query = query.where(
                        UsageRecordTable.timestamp >= filters.start_date  # type: ignore[arg-type]
                    )
                if filters.end_date:
                    query = query.where(UsageRecordTable.timestamp <= filters.end_date)  # type: ignore[arg-type]

            result = await session.execute(query)
            db_records = result.scalars().all()
            return [UsageRecordTable.to_domain(r) for r in db_records]

    def update_record(self, record: UsageRecord) -> None:
        """Update an existing usage record.

        Args:
            record: Usage record to update

        Raises:
            KeyError: If record with given ID does not exist
        """
        import asyncio

        try:
            loop = asyncio.get_running_loop()
            # Store reference to avoid RUF006 warning
            task = loop.create_task(self._update_record_async(record))
            task.add_done_callback(lambda t: t.exception() if t.done() else None)
        except RuntimeError:
            asyncio.run(self._update_record_async(record))

    async def _update_record_async(self, record: UsageRecord) -> None:
        """Async implementation of update_record."""
        from sqlalchemy import select

        async with self._session_factory() as session:
            result = await session.execute(
                select(UsageRecordTable).where(UsageRecordTable.id == record.id)  # type: ignore[arg-type]
            )
            db_record = result.scalar_one_or_none()

            if db_record is None:
                raise KeyError(f"Record with id {record.id} not found")

            # Update fields from domain model
            updated_record = UsageRecordTable.from_domain(record)
            for key, value in updated_record.__dict__.items():
                if not key.startswith("_"):
                    setattr(db_record, key, value)

            await session.commit()
            logger.debug(f"Updated usage record in database: {record.id}")

    def get_record_by_id(self, record_id: str) -> UsageRecord | None:
        """Get a usage record by ID.

        Args:
            record_id: ID of the record to retrieve

        Returns:
            Usage record if found, None otherwise
        """
        import asyncio
        import concurrent.futures

        try:
            asyncio.get_running_loop()
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(
                    asyncio.run, self._get_record_by_id_async(record_id)
                )
                return future.result()
        except RuntimeError:
            return asyncio.run(self._get_record_by_id_async(record_id))

    async def _get_record_by_id_async(self, record_id: str) -> UsageRecord | None:
        """Async implementation of get_record_by_id."""
        from sqlalchemy import select

        async with self._session_factory() as session:
            result = await session.execute(
                select(UsageRecordTable).where(UsageRecordTable.id == record_id)  # type: ignore[arg-type]
            )
            db_record = result.scalar_one_or_none()
            if db_record:
                return UsageRecordTable.to_domain(db_record)
            return None

    def clear(self) -> None:
        """Clear all records from the store.

        This method removes all records from the database.
        """
        import asyncio

        try:
            loop = asyncio.get_running_loop()
            # Store reference to avoid RUF006 warning
            task = loop.create_task(self._clear_async())
            task.add_done_callback(lambda t: t.exception() if t.done() else None)
        except RuntimeError:
            asyncio.run(self._clear_async())

    async def _clear_async(self) -> None:
        """Async implementation of clear."""
        from sqlalchemy import delete

        async with self._session_factory() as session:
            await session.execute(delete(UsageRecordTable))
            await session.commit()
            logger.info("Cleared all usage records from database")

    def get_record_count(self) -> int:
        """Get the total number of records in the store.

        Returns:
            Number of records in the store
        """
        import asyncio
        import concurrent.futures

        try:
            asyncio.get_running_loop()
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, self._get_record_count_async())
                return future.result()
        except RuntimeError:
            return asyncio.run(self._get_record_count_async())

    async def _get_record_count_async(self) -> int:
        """Async implementation of get_record_count."""
        from sqlalchemy import func, select

        async with self._session_factory() as session:
            result = await session.execute(
                select(func.count()).select_from(UsageRecordTable)
            )
            count: int = result.scalar_one()
            return count

    # Compatibility methods (no-ops for SQL store)
    def is_dirty(self) -> bool:
        """Check if the store has been modified since last flush.

        For SQL store, always returns False as changes are persisted immediately.

        Returns:
            False
        """
        return False

    def start_persistence_thread(self) -> None:
        """Start background thread for periodic persistence.

        No-op for SQL store as changes are persisted immediately.
        """
        logger.debug("Persistence thread not needed for SQL store")

    def stop_persistence_thread(self) -> None:
        """Stop the background persistence thread.

        No-op for SQL store as there's no background thread.
        """
        logger.debug("No persistence thread to stop for SQL store")

    def flush_to_disk(self) -> None:
        """Persist current state to disk.

        No-op for SQL store as changes are persisted immediately.
        """
        logger.debug("Flush not needed for SQL store (auto-committed)")

    def load_from_disk(self) -> None:
        """Load persisted state from disk.

        No-op for SQL store as data is always in database.
        """
        logger.debug("Load not needed for SQL store (always in database)")
