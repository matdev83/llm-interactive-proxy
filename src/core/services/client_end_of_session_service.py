"""Client end-of-session service implementation.

This service normalizes client termination signals, orchestrates cancellation,
and ensures End-of-Session events are emitted for client-terminated sessions.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from src.core.domain.client_termination import (
    ClientEndOfSessionSignal,
    ClientTerminationReason,
)
from src.core.domain.events.end_of_session_events import (
    EndOfSessionSignal,
    EndOfSessionSignalType,
    EndOfSessionTerminationCategory,
)
from src.core.domain.session_key import SessionKey
from src.core.interfaces.client_end_of_session_service_interface import (
    IClientEndOfSessionService,
)
from src.core.interfaces.client_termination_reason_mapper_interface import (
    IClientTerminationReasonMapper,
)
from src.core.interfaces.end_of_session_service_interface import (
    IEndOfSessionService,
)
from src.core.interfaces.session_cancellation_coordinator_interface import (
    ISessionCancellationCoordinator,
)
from src.core.interfaces.session_metrics_initializer_interface import (
    ISessionMetricsInitializer,
)

logger = logging.getLogger(__name__)


class ClientEndOfSessionService(IClientEndOfSessionService):
    """Service for normalizing client termination and orchestrating EoS closure.

    This service bridges transport-level termination detection with the EoS
    emission system, ensuring client termination consistently triggers cancellation
    and End-of-Session events.

    The service is idempotent: multiple termination reports for the same session
    are deduplicated via the cancellation coordinator, ensuring at most one EoS
    event per session.
    """

    def __init__(
        self,
        cancellation_coordinator: ISessionCancellationCoordinator,
        metrics_initializer: ISessionMetricsInitializer,
        eos_service: IEndOfSessionService,
        reason_mapper: IClientTerminationReasonMapper,
    ) -> None:
        """Initialize the client end-of-session service.

        Args:
            cancellation_coordinator: Coordinator for session-scoped cancellation
            metrics_initializer: Service for ensuring session metrics exist
            eos_service: Service for emitting End-of-Session events
            reason_mapper: Mapper for normalizing termination reasons
        """
        self._cancellation_coordinator = cancellation_coordinator
        self._metrics_initializer = metrics_initializer
        self._eos_service = eos_service
        self._reason_mapper = reason_mapper

    async def report_client_termination(self, signal: ClientEndOfSessionSignal) -> None:
        """Report a client termination signal and orchestrate EoS closure.

        This method:
        1. Checks if session is already cancelled (dedupe)
        2. Cancels session via coordinator (before blocking work)
        3. Ensures session metrics exist (defensive fallback)
        4. Emits EoS signal with CLIENT_TERMINATION type, NORMAL category

        Args:
            signal: Normalized client termination signal with session metadata
        """
        session_key = signal.session_key

        # Requirement 2.5, 2.6: Deduplicate multiple termination signals
        # Check if session is already cancelled (idempotent check)
        if self._cancellation_coordinator.is_cancelled(session_key):
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Session %s already cancelled, skipping duplicate termination report",
                    session_key.primary_id,
                    extra={
                        "session_key": {
                            "protocol": session_key.protocol,
                            "primary_id": session_key.primary_id,
                        },
                    },
                )
            return

        # Requirement 4.1, 4.2: Cancel session before blocking operations
        # This ensures backend work stops immediately (NFR 1: performance)
        self._cancellation_coordinator.cancel_session(session_key, signal.reason)

        # Requirement 3.10, 5.5: Ensure session metrics exist (defensive fallback)
        # This happens after cancellation to avoid delaying cancellation (NFR 1)
        try:
            await self._metrics_initializer.ensure_session_metrics(
                session_key, observed_at=signal.observed_at
            )
        except Exception as e:
            # Requirement 3.9: Fail-open behavior
            # Log but continue with EoS emission even if metrics init fails
            # Design.md line 434: Log with high-signal error code/metric for visibility
            logger.warning(
                "Failed to ensure session metrics for session %s during client termination: %s",
                session_key.primary_id,
                e,
                exc_info=True,
                extra={
                    "session_key": {
                        "protocol": session_key.protocol,
                        "primary_id": session_key.primary_id,
                    },
                    "error_code": "SESSION_METRICS_INIT_FAILED",
                },
            )

        # Requirement 3.2, 3.3, 3.4: Emit EoS event with client-termination signal type
        # Requirement 6.1: Log termination reason with session identifier
        if logger.isEnabledFor(logging.INFO):
            logger.info(
                "Client termination reported for session %s (reason: %s)",
                session_key.primary_id,
                signal.reason.value,
                extra={
                    "session_key": {
                        "protocol": session_key.protocol,
                        "primary_id": session_key.primary_id,
                        "group_id": session_key.group_id,
                    },
                    "reason": signal.reason.value,
                    "details": signal.details,
                },
            )

        # Create EoS signal with client-termination type and normal category
        eos_signal = EndOfSessionSignal(
            session_id=session_key.primary_id,
            signal_type=EndOfSessionSignalType.CLIENT_TERMINATION,
            termination_category=EndOfSessionTerminationCategory.NORMAL,
            observed_at=signal.observed_at,
            reason=signal.reason.value,
            error_classification=None,
            error_status_code=None,
            protocol=session_key.protocol,
            request_id=None,
            backend=None,
        )

        # Requirement 3.9: Fail-open EoS emission
        # Emit EoS event (idempotency and fail-open behavior handled by EoS service)
        # Even if EoS service fails, we've already cancelled the session, so we log and continue
        try:
            await self._eos_service.record_signal(eos_signal)
        except Exception as e:
            # Fail-open: log but don't raise - cancellation already happened
            logger.error(
                "Failed to emit EoS event for client-terminated session %s: %s",
                session_key.primary_id,
                e,
                exc_info=True,
                extra={
                    "session_key": {
                        "protocol": session_key.protocol,
                        "primary_id": session_key.primary_id,
                    },
                    "reason": signal.reason.value,
                    "error_code": "CLIENT_EOS_EMISSION_FAILED",
                },
            )

    async def report_client_termination_if_applicable(
        self, session_key: SessionKey, observed_exception: BaseException | None
    ) -> None:
        """Report client termination if the exception indicates termination.

        This method detects cancellation exceptions (CancelledError, GeneratorExit)
        and maps them to client termination signals. If the exception does not
        indicate client termination, this method does nothing.

        Args:
            session_key: The lifecycle session identifier
            observed_exception: Exception that may indicate client termination
                (e.g., CancelledError, GeneratorExit) or None
        """
        if observed_exception is None:
            return

        # Map exception to termination reason
        reason = self._reason_mapper.map_exception(observed_exception)

        # Only report if exception maps to a known termination reason
        # UNKNOWN_CLIENT_TERMINATION means the exception doesn't indicate termination
        if reason == ClientTerminationReason.UNKNOWN_CLIENT_TERMINATION:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Exception %s does not indicate client termination for session %s",
                    type(observed_exception).__name__,
                    session_key.primary_id,
                    extra={
                        "session_key": {
                            "protocol": session_key.protocol,
                            "primary_id": session_key.primary_id,
                        },
                        "exception_type": type(observed_exception).__name__,
                    },
                )
            return

        # Create termination signal from exception
        signal = ClientEndOfSessionSignal(
            session_key=session_key,
            observed_at=datetime.now(timezone.utc),
            reason=reason,
            details=f"Exception-based termination: {type(observed_exception).__name__}",
        )

        # Report termination (will dedupe if already reported)
        await self.report_client_termination(signal)
