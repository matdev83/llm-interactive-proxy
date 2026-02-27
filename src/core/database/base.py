"""Base classes for SQLModel models."""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel
from sqlmodel._compat import SQLModelConfig


def _get_timestamp() -> datetime:
    """Get current UTC timestamp, respecting time source override if active."""
    # Use the TimeSource service so tests can override time safely.
    from src.core.services.time_source_service import TimeSource

    return TimeSource().now_utc()


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

    # SQLModel uses a TypedDict-based config in Pydantic v2.
    # Start from SQLModel's default v2 behavior (from_attributes/orm_mode analogue)
    # and allow arbitrary types for connector/service objects stored on models.
    model_config = SQLModelConfig()
    model_config["from_attributes"] = True  # type: ignore[literal-required]
    model_config["arbitrary_types_allowed"] = True  # type: ignore[literal-required]
