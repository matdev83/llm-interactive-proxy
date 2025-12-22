"""End-of-Session events for the event bus.

This module defines domain events and signal models for end-of-session detection
and emission. These events normalize completion signals across protocols and
enable consistent session finalization.

Event Types:
- RemoteBackendConnectionEndOfSessionEvent: Emitted when a session ends

All events are immutable dataclasses inheriting from DomainEvent.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import ClassVar

from src.core.domain.events import DomainEvent


class EndOfSessionSignalType(str, Enum):
    """Canonical signal types for end-of-session detection.

    These types represent the different sources of completion signals
    that can trigger an end-of-session event.
    """

    DONE_SENTINEL = "done_sentinel"
    """Streaming completion sentinel (e.g., [DONE])."""

    FINISH_REASON = "finish_reason"
    """Protocol finish_reason marker."""

    RESPONSE_COMPLETED = "response_completed"
    """Explicit response completion event (e.g., response.completed)."""

    TOOL_COMPLETION = "tool_completion"
    """Completion tool call invocation."""

    ERROR_TERMINATION = "error_termination"
    """Backend or transport error termination."""

    CLIENT_TERMINATION = "client_termination"
    """Client-side termination (disconnect or cancellation).

    When used, the termination category MUST be NORMAL (not ERROR), as client
    termination is considered a normal session ending from the proxy's perspective.
    See requirement 3.3 in client-end-of-session-handling specification.
    """


class EndOfSessionTerminationCategory(str, Enum):
    """Canonical termination categories for end-of-session events.

    These categories classify how a session ended.
    """

    NORMAL = "normal"
    """Session ended normally (completion signal received)."""

    ERROR = "error"
    """Session ended due to an error (backend or transport failure)."""


class EndOfSessionErrorClassification(str, Enum):
    """Standardized error classifications for error terminations.

    These values provide normalized error categorization for error-driven
    end-of-session events.
    """

    TRANSPORT_ERROR = "transport_error"
    """Transport-level error (connection, timeout, network)."""

    HTTP_ERROR = "http_error"
    """HTTP-level error (non-200 status code)."""

    BACKEND_ERROR = "backend_error"
    """Backend API error (provider-specific error response)."""

    UNKNOWN_ERROR = "unknown_error"
    """Unknown or unclassified error."""


@dataclass(frozen=True)
class EndOfSessionSignal:
    """Normalized signal input for the End-of-Session service.

    This dataclass represents a completion signal that has been normalized
    from protocol-specific markers into a unified format. It contains all
    metadata needed to emit an End-of-Session event.

    Attributes:
        session_id: Unique identifier for the session.
        signal_type: Type of completion signal detected.
        termination_category: How the session ended (normal or error).
        observed_at: When the signal was observed.
        reason: Optional reason or description for the termination.
        error_classification: Standardized error classification (if error termination).
        error_status_code: HTTP status code (if applicable).
        protocol: Protocol identifier (e.g., "openai", "anthropic").
        request_id: Request identifier for correlation.
        backend: Backend name that handled the request.

    Note:
        This signal does not include secrets or authorization data.
        All fields are optional except session_id, signal_type, termination_category,
        and observed_at.
    """

    session_id: str
    signal_type: EndOfSessionSignalType
    termination_category: EndOfSessionTerminationCategory
    observed_at: datetime
    reason: str | None = None
    error_classification: EndOfSessionErrorClassification | None = None
    error_status_code: int | None = None
    protocol: str | None = None
    request_id: str | None = None
    backend: str | None = None


@dataclass(frozen=True)
class RemoteBackendConnectionEndOfSessionEvent(DomainEvent):
    """Event emitted when a remote backend connection session ends.

    This event is emitted once per session when an end-of-session condition
    is detected. It normalizes completion signals across protocols and provides
    a consistent interface for subsystems to react to session completion.

    Attributes:
        session_id: Unique identifier for the session.
        signal_type: Type of completion signal that triggered the event.
        termination_category: How the session ended (normal or error).
        reason: Optional reason or description for the termination.
        error_classification: Standardized error classification (if error termination).
        error_status_code: HTTP status code (if applicable).
        protocol: Protocol identifier (e.g., "openai", "anthropic").
        request_id: Request identifier for correlation.
        backend: Backend name that handled the request.

    Note:
        This event does not include secrets or authorization data.
        The timestamp field is inherited from DomainEvent and represents
        when the event was created (not when the signal was observed).
    """

    event_type: ClassVar[str] = "remote_backend_connection_end_of_session"

    session_id: str = ""
    signal_type: EndOfSessionSignalType = EndOfSessionSignalType.DONE_SENTINEL
    termination_category: EndOfSessionTerminationCategory = (
        EndOfSessionTerminationCategory.NORMAL
    )
    reason: str | None = None
    error_classification: EndOfSessionErrorClassification | None = None
    error_status_code: int | None = None
    protocol: str | None = None
    request_id: str | None = None
    backend: str | None = None

    def __post_init__(self) -> None:
        """Validate required fields."""
        if not self.session_id:
            raise ValueError("session_id is required")
        super().__post_init__()


__all__ = [
    "EndOfSessionSignalType",
    "EndOfSessionTerminationCategory",
    "EndOfSessionErrorClassification",
    "EndOfSessionSignal",
    "RemoteBackendConnectionEndOfSessionEvent",
]
