"""Interface for End-of-Session service.

This module defines the interface for the End-of-Session service that normalizes
completion signals and emits End-of-Session events once per session.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.core.domain.events.end_of_session_events import EndOfSessionSignal


class IEndOfSessionService(ABC):
    """Interface for End-of-Session detection and event emission.

    This service normalizes completion signals from various sources (streaming,
    tool calls, errors) and ensures at-most-once event emission per session
    using atomic database claims and in-memory dedupe.
    """

    @abstractmethod
    async def record_signal(self, signal: EndOfSessionSignal) -> None:
        """Normalize a signal and emit EoS event once per session.

        This method processes a completion signal and emits an End-of-Session
        event if:
        - EoS detection is enabled in configuration
        - Event emission is enabled in configuration
        - The session has not already ended (atomic claim succeeds)

        The method uses an atomic database claim to ensure only one caller
        can emit the first EoS event per session, preventing duplicate emissions
        under concurrency.

        Args:
            signal: Normalized completion signal with session metadata

        Preconditions:
            - signal.session_id must be present
            - EoS detection must be enabled in configuration

        Postconditions:
            - At most one event emitted per session (enforced by atomic DB claim)
            - Session marked as ended in database if emission succeeds

        Invariants:
            - Once ended, additional signals do not emit new events
            - Event emission respects dispatch timeout configuration
        """

    @abstractmethod
    async def has_ended(self, session_id: str, request_id: str | None = None) -> bool:
        """Return True if EoS event has been emitted for session or request.

        This is a fast in-memory check for hot-path dedupe. If request_id is
        provided, it checks for that specific turn. Otherwise, it checks if
        the session has already emitted an event (legacy behavior).

        Args:
            session_id: Session identifier
            request_id: Optional request identifier for turn-scoped check

        Returns:
            True if EoS event has been emitted, False otherwise
        """
