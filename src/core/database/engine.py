"""Async database engine and session management."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

import sqlalchemy.exc
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlmodel import SQLModel

from src.core.database.config import DatabaseConfig

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class DatabaseEngine:
    """Manages async database engine and session factory.

    This class provides:
    - Lazy initialization of async engine
    - Session factory for DI container
    - Schema initialization support
    - Graceful shutdown
    """

    def __init__(self, config: DatabaseConfig) -> None:
        """Initialize database engine manager.

        Args:
            config: Database configuration
        """
        self._config = config
        self._engine: AsyncEngine | None = None
        self._session_factory: async_sessionmaker[AsyncSession] | None = None
        self._initialized = False

    @property
    def config(self) -> DatabaseConfig:
        """Get database configuration."""
        return self._config

    @property
    def engine(self) -> AsyncEngine:
        """Get the async engine, creating it if necessary."""
        if self._engine is None:
            self._engine = self._create_engine()
        return self._engine

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        """Get the session factory, creating it if necessary."""
        if self._session_factory is None:
            self._session_factory = async_sessionmaker(
                bind=self.engine,
                class_=AsyncSession,
                expire_on_commit=False,
                autocommit=False,
                autoflush=False,
            )
        return self._session_factory

    def _create_engine(self) -> AsyncEngine:
        """Create the async engine with proper configuration."""
        # Ensure parent directory exists for SQLite
        if self._config.is_sqlite:
            self._ensure_sqlite_directory()

        # Build engine kwargs
        engine_kwargs: dict = {
            "echo": self._config.echo,
            "echo_pool": self._config.echo_pool,
        }

        # Add pool settings for non-SQLite databases
        if not self._config.is_sqlite:
            engine_kwargs.update(
                {
                    "pool_size": self._config.pool_size,
                    "max_overflow": self._config.max_overflow,
                    "pool_timeout": self._config.pool_timeout,
                }
            )
        else:
            # SQLite-specific settings
            engine_kwargs["connect_args"] = {"check_same_thread": False}

        logger.info("Creating async database engine for: %s", self._config.url)
        return create_async_engine(self._config.url, **engine_kwargs)

    def _ensure_sqlite_directory(self) -> None:
        """Ensure the SQLite database directory exists."""
        # Extract path from URL: sqlite+aiosqlite:///./var/db/proxy.db
        url = self._config.url
        if ":///" in url:
            # Absolute or relative path
            db_path = url.split(":///")[-1]
            path = Path(db_path)
            if path.parent and str(path.parent) != ".":
                path.parent.mkdir(parents=True, exist_ok=True)
                logger.debug("Ensured database directory exists: %s", path.parent)

    async def initialize(self) -> None:
        """Initialize the database (create tables if needed)."""
        if self._initialized:
            return

        async with self.engine.begin() as conn:
            # Import all models to register them with SQLModel
            import src.core.database.models.memory as memory_models
            import src.core.database.models.sso as sso_models
            import src.core.database.models.usage as usage_models

            _ = (memory_models, sso_models, usage_models)
            await conn.run_sync(SQLModel.metadata.create_all)

        self._initialized = True
        logger.info("Database schema initialized")

    async def close(self) -> None:
        """Close the database engine and release resources."""
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
            self._session_factory = None
            self._initialized = False
            logger.info("Database engine closed")

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """Get a database session as async context manager.

        Usage:
            async with engine.session() as session:
                result = await session.execute(...)

        Yields:
            AsyncSession: Database session that auto-commits on success
        """
        session = self.session_factory()
        try:
            yield session
            await session.commit()
        except sqlalchemy.exc.SQLAlchemyError as exc:
            # Log SQLAlchemy-specific errors with full context for debugging
            logger.error(
                "SQLAlchemy error in database session, rolling back: %s",
                exc,
                exc_info=True,
            )
            await asyncio.shield(session.rollback())
            raise
        except asyncio.CancelledError:
            await asyncio.shield(session.rollback())
            raise
        except Exception as exc:
            # Catch all other exceptions to ensure rollback, then re-raise
            # This preserves transaction safety for non-SQLAlchemy errors
            # Log with full context to aid debugging of unexpected errors
            logger.error(
                "Non-SQLAlchemy error in database session, rolling back: %s",
                exc,
                exc_info=True,
            )
            await asyncio.shield(session.rollback())
            raise
        finally:
            await asyncio.shield(session.close())


# Module-level convenience functions


async def init_database(config: DatabaseConfig) -> DatabaseEngine:
    """Create and initialize a database engine.

    Args:
        config: Database configuration

    Returns:
        Initialized DatabaseEngine instance
    """
    engine = DatabaseEngine(config)
    await engine.initialize()
    return engine


@asynccontextmanager
async def get_async_session(
    engine: DatabaseEngine,
) -> AsyncGenerator[AsyncSession, None]:
    """Get an async session from the engine.

    This is a convenience wrapper for use in DI and tests.

    Args:
        engine: Database engine instance

    Yields:
        AsyncSession: Database session
    """
    async with engine.session() as session:
        yield session
