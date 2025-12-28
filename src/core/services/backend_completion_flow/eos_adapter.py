"""End-of-Session adapter for BackendCompletionFlow.

This adapter translates backend and transport failures into End-of-Session
signals with standardized error classifications.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from src.core.common.exceptions import (
    APIConnectionError,
    APITimeoutError,
    BackendError,
    LLMProxyError,
)
from src.core.config.models.end_of_session import EndOfSessionConfig
from src.core.domain.events.end_of_session_events import (
    EndOfSessionErrorClassification,
    EndOfSessionSignal,
    EndOfSessionSignalType,
    EndOfSessionTerminationCategory,
)
from src.core.domain.request_context import RequestContext
from src.core.interfaces.end_of_session_service_interface import IEndOfSessionService

logger = logging.getLogger(__name__)


class BackendCompletionFlowEosAdapter:
    """Adapter that translates backend/transport errors into EoS signals.

    This adapter observes BackendCompletionFlow failures and emits End-of-Session
    signals with standardized error classifications. It remains fail-open and
    does not interfere with error handling paths.
    """

    def __init__(
        self,
        end_of_session_service: IEndOfSessionService,
        config: EndOfSessionConfig,
    ) -> None:
        """Initialize the BackendCompletionFlow EoS adapter.

        Args:
            end_of_session_service: Service for recording EoS signals
            config: End-of-Session configuration
        """
        self._eos_service = end_of_session_service
        self._config = config

    async def record_error_termination(
        self,
        error: Exception,
        session_id: str | None,
        backend_type: str | None = None,
        context: RequestContext | None = None,
    ) -> None:
        """Record an error termination as an EoS signal.

        This method classifies the error and emits an End-of-Session signal
        if EoS detection is enabled. It fails-open and does not raise exceptions.

        Args:
            error: The exception that caused the termination
            session_id: Session identifier (extracted from context if not provided)
            backend_type: Backend name that handled the request
            context: Optional request context for extracting session_id and metadata
        """
        # Skip if EoS detection or emission is disabled
        if not self._config.enabled or not self._config.emit_events:
            return

        # Extract session_id from context if not provided
        if not session_id and context is not None:
            session_id = getattr(context, "session_id", None)

        if not session_id:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "EoS adapter: Missing session_id, skipping error termination signal",
                    extra={"error_type": type(error).__name__},
                )
            return

        # Early exit if session has already ended (hot-path dedupe)
        if await self._eos_service.has_ended(session_id):
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "EoS adapter: Session %s already ended, skipping error termination signal",
                    session_id,
                )
            return

        # Classify error
        error_classification = self._classify_error(error)
        status_code = self._extract_status_code(error)

        # Create EoS signal
        signal = EndOfSessionSignal(
            session_id=session_id,
            signal_type=EndOfSessionSignalType.ERROR_TERMINATION,
            termination_category=EndOfSessionTerminationCategory.ERROR,
            observed_at=datetime.now(timezone.utc),
            reason=f"Backend/transport error: {type(error).__name__}: {str(error)[:200]}",
            error_classification=error_classification,
            error_status_code=status_code,
            backend=backend_type,
            protocol=None,  # Errors don't have explicit protocol
            request_id=getattr(context, "request_id", None) if context else None,
        )

        # Emit signal (fail-open on errors)
        try:
            await self._eos_service.record_signal(signal)
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "EoS error termination signal emitted: session=%s, error_classification=%s",
                    session_id,
                    error_classification.value,
                    extra={
                        "session_id": session_id,
                        "error_type": type(error).__name__,
                        "error_classification": error_classification.value,
                        "status_code": status_code,
                    },
                )
        except Exception as e:
            logger.warning(
                "Failed to record EoS error termination signal: %s",
                e,
                exc_info=True,
                extra={
                    "session_id": session_id,
                    "error_type": type(error).__name__,
                },
            )

    def _classify_error(self, error: Exception) -> EndOfSessionErrorClassification:
        """Classify error into standardized error classification.

        Args:
            error: The exception to classify

        Returns:
            Standardized error classification
        """
        # Check for httpx errors in cause first (most specific)
        if hasattr(error, "__cause__") and error.__cause__ is not None:
            cause = error.__cause__
            # Check if cause is httpx.TimeoutException or httpx.ConnectError
            cause_type_name = type(cause).__name__
            if "Timeout" in cause_type_name:
                return EndOfSessionErrorClassification.TRANSPORT_ERROR
            if "Connect" in cause_type_name or "Connection" in cause_type_name:
                return EndOfSessionErrorClassification.TRANSPORT_ERROR
            # Check if cause is httpx.HTTPStatusError
            if "HTTPStatus" in cause_type_name or "HTTPError" in cause_type_name:
                return EndOfSessionErrorClassification.HTTP_ERROR

        # Transport errors (connection, timeout, network)
        if isinstance(error, (APIConnectionError, APITimeoutError)):  # noqa: UP038
            return EndOfSessionErrorClassification.TRANSPORT_ERROR

        # Backend API errors (check before HTTP_ERROR to avoid misclassification)
        if isinstance(error, BackendError):
            return EndOfSessionErrorClassification.BACKEND_ERROR

        # HTTP errors (non-200 status codes) - only for non-BackendError LLMProxyErrors
        if isinstance(error, LLMProxyError) and not isinstance(error, BackendError):
            status_code = getattr(error, "status_code", None)
            if isinstance(status_code, int) and status_code >= 400:
                return EndOfSessionErrorClassification.HTTP_ERROR

        # Unknown error
        return EndOfSessionErrorClassification.UNKNOWN_ERROR

    def _extract_status_code(self, error: Exception) -> int | None:
        """Extract HTTP status code from error if available.

        Prioritizes status_code from error cause (more specific) over error itself.

        Args:
            error: The exception to extract status code from

        Returns:
            HTTP status code if available, None otherwise
        """
        # Check cause first (more specific)
        if hasattr(error, "__cause__") and error.__cause__ is not None:
            cause = error.__cause__
            if hasattr(cause, "response") and hasattr(cause.response, "status_code"):
                status_code = cause.response.status_code
                if isinstance(status_code, int):
                    return status_code
            if hasattr(cause, "status_code"):
                status_code = getattr(cause, "status_code", None)
                if isinstance(status_code, int):
                    return status_code

        # Check error itself
        if hasattr(error, "status_code"):
            status_code = getattr(error, "status_code", None)
            if isinstance(status_code, int):
                return status_code

        return None
