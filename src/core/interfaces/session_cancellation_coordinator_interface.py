"""Interface for session cancellation coordinator.

This module defines the interface for coordinating session-scoped cancellation
of in-flight backend work and preventing new work after client termination.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol

from src.core.domain.client_termination import ClientTerminationReason
from src.core.domain.session_key import SessionKey


class ICancellable(Protocol):
    """Protocol for cancellable in-flight work.

    Components that can be cancelled (e.g., backend requests, scheduled tasks)
    should implement this protocol.
    """

    def cancel(self) -> None:
        """Cancel the in-flight work.

        This method should be idempotent and safe to call multiple times.
        """
        ...


class ISessionCancellationCoordinator(ABC):
    """Interface for session-scoped cancellation coordination.

    This coordinator maintains explicit "cancelled" state per lifecycle session
    and provides cancellation gating to prevent new backend work after client
    termination.

    All operations are scoped to SessionKey to ensure strict session isolation.
    """

    @abstractmethod
    def is_cancelled(self, session_key: SessionKey) -> bool:
        """Check if a session has been cancelled.

        Args:
            session_key: The lifecycle session identifier.

        Returns:
            True if the session has been cancelled, False otherwise.
        """
        ...

    @abstractmethod
    def cancel_session(
        self, session_key: SessionKey, reason: ClientTerminationReason
    ) -> None:
        """Mark a session as cancelled and cancel all registered work.

        This method is idempotent: calling it multiple times for the same session
        will only cancel registered work once per registration.

        Args:
            session_key: The lifecycle session identifier.
            reason: Standardized client termination reason.
        """
        ...

    @abstractmethod
    def register_cancellable(
        self, session_key: SessionKey, cancellable: ICancellable
    ) -> None:
        """Register cancellable in-flight work for a session.

        Registered cancellables will be cancelled when cancel_session is called
        for the session. If the session is already cancelled, the cancellable
        will be cancelled immediately.

        Args:
            session_key: The lifecycle session identifier.
            cancellable: The cancellable work to register.
        """
        ...

    @abstractmethod
    def ensure_not_cancelled(self, session_key: SessionKey) -> None:
        """Ensure a session is not cancelled, raising if it is.

        This is a cancellation gate that can be called before initiating any
        backend work (initial calls, retries, failover, recovery, follow-up calls).

        Args:
            session_key: The lifecycle session identifier.

        Raises:
            SessionCancelledError: If the session has been cancelled.
        """
        ...

    @abstractmethod
    def cleanup(self, session_key: SessionKey) -> None:
        """Clean up cancellation state for a session.

        This method removes in-memory cancellation state. It is best-effort and
        should not raise exceptions that could block other cleanup operations.

        Args:
            session_key: The lifecycle session identifier.
        """
        ...
