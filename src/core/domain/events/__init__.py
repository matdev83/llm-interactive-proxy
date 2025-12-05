"""Event system domain models.

This module provides base classes for events used in the pub/sub pattern.
Events are immutable data containers that carry information about something
that happened in the system.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import ClassVar
from uuid import uuid4


@dataclass(frozen=True)
class Event:
    """Base class for all events in the system.

    Events are immutable data containers that represent something
    that happened. They should be treated as facts about the past.

    Attributes:
        event_id: Unique identifier for this event instance.
        timestamp: When the event was created (UTC).
        event_type: String identifier for the event type (set by subclasses).
    """

    event_type: ClassVar[str] = "base_event"

    event_id: str = field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        """Validate event after initialization."""
        # Subclasses can override for validation

    @classmethod
    def get_event_type(cls) -> str:
        """Return the event type identifier for this class."""
        return cls.event_type


@dataclass(frozen=True)
class DomainEvent(Event):
    """Base class for domain-specific events.

    Domain events represent meaningful occurrences in the business domain.
    """

    event_type: ClassVar[str] = "domain_event"


@dataclass(frozen=True)
class InfrastructureEvent(Event):
    """Base class for infrastructure-related events.

    Infrastructure events represent system-level occurrences like
    health checks, connectivity changes, etc.
    """

    event_type: ClassVar[str] = "infrastructure_event"


__all__ = [
    "Event",
    "DomainEvent",
    "InfrastructureEvent",
]
