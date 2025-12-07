"""Base repository class for async database operations."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Generic, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import SQLModel, select

if TYPE_CHECKING:
    from src.core.database.engine import DatabaseEngine

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=SQLModel)


class AsyncRepository(ABC, Generic[T]):
    """Abstract base class for async repositories.

    Provides common CRUD operations for SQLModel tables.
    Subclasses should implement model-specific query methods.
    """

    def __init__(self, engine: DatabaseEngine) -> None:
        """Initialize repository with database engine.

        Args:
            engine: Database engine for session creation
        """
        self._engine = engine

    @property
    @abstractmethod
    def model_class(self) -> type[T]:
        """Return the SQLModel class this repository manages."""
        ...

    async def get_by_id(self, id_value: str | int) -> T | None:
        """Get a record by its primary key.

        Args:
            id_value: Primary key value

        Returns:
            Model instance or None if not found
        """
        async with self._engine.session() as session:
            return await session.get(self.model_class, id_value)

    async def create(self, instance: T) -> T:
        """Create a new record.

        Args:
            instance: Model instance to create

        Returns:
            Created model instance with any auto-generated fields
        """
        async with self._engine.session() as session:
            session.add(instance)
            await session.flush()
            await session.refresh(instance)
            return instance

    async def update(self, instance: T) -> T:
        """Update an existing record.

        Args:
            instance: Model instance to update

        Returns:
            Updated model instance
        """
        async with self._engine.session() as session:
            session.add(instance)
            await session.flush()
            await session.refresh(instance)
            return instance

    async def delete(self, instance: T) -> None:
        """Delete a record.

        Args:
            instance: Model instance to delete
        """
        async with self._engine.session() as session:
            await session.delete(instance)

    async def delete_by_id(self, id_value: str | int) -> bool:
        """Delete a record by its primary key.

        Args:
            id_value: Primary key value

        Returns:
            True if deleted, False if not found
        """
        async with self._engine.session() as session:
            instance = await session.get(self.model_class, id_value)
            if instance:
                await session.delete(instance)
                return True
            return False

    async def get_all(self, limit: int = 100, offset: int = 0) -> list[T]:
        """Get all records with pagination.

        Args:
            limit: Maximum number of records to return
            offset: Number of records to skip

        Returns:
            List of model instances
        """
        async with self._engine.session() as session:
            statement = select(self.model_class).offset(offset).limit(limit)
            result = await session.execute(statement)
            return list(result.scalars().all())

    async def count(self) -> int:
        """Count total records.

        Returns:
            Total number of records
        """
        from sqlalchemy import func

        async with self._engine.session() as session:
            statement = select(func.count()).select_from(self.model_class)
            result = await session.execute(statement)
            return result.scalar() or 0

    async def _execute_in_session(
        self, session: AsyncSession, callback: object
    ) -> object:
        """Execute a callback within an existing session.

        This allows subclasses to perform complex operations
        within a single transaction.

        Args:
            session: Active database session
            callback: Async callable to execute

        Returns:
            Result from callback
        """
        raise NotImplementedError("Subclasses should implement specific methods")
