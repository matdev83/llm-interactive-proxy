"""Database configuration model."""

from __future__ import annotations

from pydantic import ConfigDict, Field, field_validator

from src.core.interfaces.model_bases import DomainModel


class DatabaseConfig(DomainModel):
    """Configuration for the database abstraction layer.

    Controls database connection, pooling, and migration settings.
    """

    model_config = ConfigDict(frozen=True)

    # Database URL (SQLAlchemy format)
    # SQLite: sqlite+aiosqlite:///./var/proxy.db
    # PostgreSQL: postgresql+asyncpg://user:pass@host/db
    url: str = Field(
        default="sqlite+aiosqlite:///./var/proxy.db",
        description="Database connection URL in SQLAlchemy format",
    )

    # Connection pool settings (ignored for SQLite)
    pool_size: int = Field(
        default=5,
        ge=1,
        le=100,
        description="Connection pool size",
    )
    max_overflow: int = Field(
        default=10,
        ge=0,
        le=100,
        description="Max overflow connections beyond pool_size",
    )
    pool_timeout: int = Field(
        default=30,
        ge=1,
        description="Seconds to wait for a connection from pool",
    )

    # SQLAlchemy settings
    echo: bool = Field(
        default=False,
        description="Echo SQL statements to logs",
    )
    echo_pool: bool = Field(
        default=False,
        description="Echo connection pool events",
    )

    # Migration settings
    auto_migrate: bool = Field(
        default=True,
        description="Run Alembic migrations on startup",
    )

    @field_validator("url", mode="before")
    @classmethod
    def validate_url(cls, v: str) -> str:
        """Validate database URL format."""
        if not isinstance(v, str):
            raise ValueError("Database URL must be a string")
        if not v:
            raise ValueError("Database URL cannot be empty")
        # Basic validation - SQLAlchemy will do full validation
        if "://" not in v and not v.startswith("sqlite"):
            raise ValueError(
                f"Invalid database URL format: {v}. "
                "Expected format: dialect+driver://user:pass@host/db"
            )
        return v

    @property
    def is_sqlite(self) -> bool:
        """Check if using SQLite backend."""
        return self.url.startswith("sqlite")

    @property
    def is_async(self) -> bool:
        """Check if using async driver."""
        return "aiosqlite" in self.url or "asyncpg" in self.url
