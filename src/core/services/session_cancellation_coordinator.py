"""Session cancellation coordinator implementation.

This module implements session-scoped cancellation coordination using a
TTLCache for bounded state retention and automatic cleanup.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock

from cachetools import TTLCache

from src.core.common.exceptions import SessionCancelledError
from src.core.domain.client_termination import ClientTerminationReason
from src.core.domain.session_key import SessionKey
from src.core.interfaces.session_cancellation_coordinator_interface import (
    ICancellable,
    ISessionCancellationCoordinator,
)

logger = logging.getLogger(__name__)

# Default TTL for cancellation state (1 hour as per design.md)
DEFAULT_CANCELLATION_TTL_SECONDS = 3600


@dataclass
class _CancellationState:
    """Internal state for a cancelled session."""

    cancelled: bool
    reason: ClientTerminationReason
    cancelled_at: datetime
    cancellables: list[ICancellable]


class SessionCancellationCoordinator(ISessionCancellationCoordinator):
    """Session-scoped cancellation coordinator.

    This coordinator maintains explicit "cancelled" state per SessionKey and
    provides cancellation gating to prevent new backend work after client
    termination.

    State is stored in a TTLCache that automatically expires entries after
    the configured TTL, providing bounded retention without background tasks.

    Thread Safety:
        This implementation is thread-safe. The TTLCache is thread-safe for
        concurrent reads/writes, and cancellable registration uses a lock.
    """

    def __init__(self, ttl_seconds: float = DEFAULT_CANCELLATION_TTL_SECONDS) -> None:
        """Initialize the cancellation coordinator.

        Args:
            ttl_seconds: Time-to-live for cancellation state entries in seconds.
                Defaults to 1 hour (3600 seconds).
        """
        # TTLCache is thread-safe and provides automatic expiry
        # Use a large maxsize (100k entries) with TTL for bounded retention
        # This provides both size-based and time-based cleanup
        self._cache: TTLCache[SessionKey, _CancellationState] = TTLCache(
            maxsize=100_000, ttl=ttl_seconds
        )
        self._lock = Lock()

    def is_cancelled(self, session_key: SessionKey) -> bool:
        """Check if a session has been cancelled.

        Args:
            session_key: The lifecycle session identifier.

        Returns:
            True if the session has been cancelled, False otherwise.
        """
        state = self._cache.get(session_key)
        return state is not None and state.cancelled

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
        with self._lock:
            state = self._cache.get(session_key)
            was_already_cancelled = False
            if state is None:
                # Create new cancellation state
                state = _CancellationState(
                    cancelled=True,
                    reason=reason,
                    cancelled_at=datetime.now(timezone.utc),
                    cancellables=[],
                )
                self._cache[session_key] = state
                # Requirement 6.1: Log client termination reason with session identifier
                if logger.isEnabledFor(logging.INFO):
                    logger.info(
                        "Session cancelled: %s (reason: %s)",
                        session_key.primary_id,
                        reason.value,
                        extra={
                            "session_key": {
                                "protocol": session_key.protocol,
                                "primary_id": session_key.primary_id,
                                "group_id": session_key.group_id,
                            },
                            "reason": reason.value,
                        },
                    )
            elif not state.cancelled:
                # Update existing state to cancelled
                state.cancelled = True
                state.reason = reason
                state.cancelled_at = datetime.now(timezone.utc)
                # Requirement 6.1: Log client termination reason with session identifier
                if logger.isEnabledFor(logging.INFO):
                    logger.info(
                        "Session cancelled: %s (reason: %s)",
                        session_key.primary_id,
                        reason.value,
                        extra={
                            "session_key": {
                                "protocol": session_key.protocol,
                                "primary_id": session_key.primary_id,
                                "group_id": session_key.group_id,
                            },
                            "reason": reason.value,
                        },
                    )
            else:
                # State was already cancelled - idempotent call, skip cancellation
                was_already_cancelled = True

            # Cancel all registered cancellables only if we're transitioning to cancelled state
            # Requirement 6.3: Record backend cancellation due to client termination
            # Create a snapshot of cancellables while holding the lock to avoid race conditions
            # Only cancel if state was not already cancelled (idempotent: skip if already cancelled)
            cancellables_to_cancel: list[ICancellable] = []
            if not was_already_cancelled and state.cancellables:
                cancellables_to_cancel = list(state.cancellables)
                # Clear the list after taking snapshot to prevent re-cancellation on subsequent calls
                state.cancellables.clear()
                cancellable_count = len(cancellables_to_cancel)
                if cancellable_count > 0 and logger.isEnabledFor(logging.INFO):
                    logger.info(
                        "Cancelling %d in-flight backend request(s) for session %s due to client termination (reason: %s)",
                        cancellable_count,
                        session_key.primary_id,
                        reason.value,
                        extra={
                            "session_key": {
                                "protocol": session_key.protocol,
                                "primary_id": session_key.primary_id,
                            },
                            "reason": reason.value,
                            "cancelled_work_count": cancellable_count,
                        },
                    )

        # Iterate over cancellables outside the lock to avoid holding lock during cancellation
        # (cancellation operations may take time and shouldn't block other operations)
        for cancellable in cancellables_to_cancel:
            try:
                cancellable.cancel()
            except Exception as e:
                # Log but don't fail if cancellation fails
                logger.warning(
                    "Failed to cancel registered work for session %s: %s",
                    session_key.primary_id,
                    e,
                    exc_info=True,
                    extra={
                        "session_key": {
                            "protocol": session_key.protocol,
                            "primary_id": session_key.primary_id,
                        },
                    },
                )

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
        with self._lock:
            state = self._cache.get(session_key)
            if state is None:
                # Create new state (not cancelled yet)
                state = _CancellationState(
                    cancelled=False,
                    reason=ClientTerminationReason.UNKNOWN_CLIENT_TERMINATION,
                    cancelled_at=datetime.now(timezone.utc),
                    cancellables=[],
                )
                self._cache[session_key] = state

            # If already cancelled, cancel immediately
            if state.cancelled:
                # Requirement 6.3: Record backend cancellation due to client termination
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Cancelling work registered after session cancellation for %s (reason: %s)",
                        session_key.primary_id,
                        state.reason.value,
                        extra={
                            "session_key": {
                                "protocol": session_key.protocol,
                                "primary_id": session_key.primary_id,
                            },
                            "reason": state.reason.value,
                        },
                    )
                try:
                    cancellable.cancel()
                except Exception as e:
                    logger.warning(
                        "Failed to cancel work registered after session cancellation for %s: %s",
                        session_key.primary_id,
                        e,
                        exc_info=True,
                    )
            else:
                # Register for later cancellation
                state.cancellables.append(cancellable)

    def ensure_not_cancelled(self, session_key: SessionKey) -> None:
        """Ensure a session is not cancelled, raising if it is.

        This is a cancellation gate that can be called before initiating any
        backend work (initial calls, retries, failover, recovery, follow-up calls).

        Args:
            session_key: The lifecycle session identifier.

        Raises:
            SessionCancelledError: If the session has been cancelled.
        """
        state = self._cache.get(session_key)
        if state is not None and state.cancelled:
            raise SessionCancelledError(
                session_key=session_key,
                reason=state.reason,
            )

    def cleanup(self, session_key: SessionKey) -> None:
        """Clean up cancellation state for a session.

        This method removes in-memory cancellation state. It is best-effort and
        should not raise exceptions that could block other cleanup operations.

        Args:
            session_key: The lifecycle session identifier.
        """
        try:
            with self._lock:
                if session_key in self._cache:
                    del self._cache[session_key]
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Cleaned up cancellation state for session %s",
                            session_key.primary_id,
                            extra={
                                "session_key": {
                                    "protocol": session_key.protocol,
                                    "primary_id": session_key.primary_id,
                                },
                            },
                        )
        except Exception as e:
            # Best-effort: log but don't raise
            logger.warning(
                "Failed to cleanup cancellation state for session %s: %s",
                session_key.primary_id,
                e,
                exc_info=True,
            )
