"""Base classes for SQLModel models."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import Field, SQLModel


def _get_timestamp() -> datetime:
    """Get current UTC timestamp, respecting time source override if active."""
    # Check for time source override (used by tests)
    from src.core.services.time_source_service import _OVERRIDE_TIME_SOURCE

    override = _OVERRIDE_TIME_SOURCE.get()
    if override is not None:
        return override.now_utc()
    return datetime.now(timezone.utc)


class TimestampMixin(SQLModel):
    """Mixin providing created_at timestamp."""

    created_at: datetime = Field(
        default_factory=_get_timestamp,
        nullable=False,
        description="Timestamp when record was created",
    )


class BaseModel(SQLModel):
    """Base model with common configuration.

    All database models should inherit from this class.
    """

    class Config:  # type: ignore[misc]
        """SQLModel configuration."""

        # Allow arbitrary types for complex fields
        arbitrary_types_allowed = True
