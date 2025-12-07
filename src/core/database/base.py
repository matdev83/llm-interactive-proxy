"""Base classes for SQLModel models."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import Field, SQLModel


class TimestampMixin(SQLModel):
    """Mixin providing created_at timestamp."""

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        nullable=False,
        description="Timestamp when record was created",
    )


class BaseModel(SQLModel):
    """Base model with common configuration.

    All database models should inherit from this class.
    """

    class Config:
        """SQLModel configuration."""

        # Allow arbitrary types for complex fields
        arbitrary_types_allowed = True
