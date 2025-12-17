"""Interface for availability gating collaborator."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope


class IBackendAvailabilityChecker(ABC):
    """Encapsulates disabled-backend and resilience availability checks."""

    @abstractmethod
    async def check_backend_availability(
        self, backend_type: str, effective_model: str, allow_failover: bool
    ) -> None:
        """Check if the backend is available (not disabled, not rate limited).

        Args:
            backend_type: The backend name
            effective_model: The model name
            allow_failover: Whether failover is allowed

        Raises:
            BackendError: If backend is permanently disabled
            RateLimitExceededError: If backend is rate limited
        """
        ...


class ICompletionSessionResolver(ABC):
    """Encapsulates session lookup and per-session backend resolution."""

    @abstractmethod
    async def resolve_session(
        self, context: Any | None, request: Any
    ) -> tuple[Any | None, str | None]:
        """Resolve session and session ID for backend.

        Args:
            context: The request context
            request: The chat request

        Returns:
            Tuple of (session object, session_id_for_backend)
        """
        ...


class IBackendRequestPreparer(ABC):
    """Encapsulates request preparation, config application, and target synchronization."""

    @abstractmethod
    async def prepare_request(
        self, request: Any, context: Any | None
    ) -> tuple[str, str, dict[str, str]]:
        """Resolve target backend/model and apply URI parameters.

        Args:
            request: The chat request
            context: The request context

        Returns:
            Tuple of (backend_type, effective_model, uri_params)
        """
        ...

    @abstractmethod
    def synchronize_request_with_target(
        self, request: Any, backend_type: str, effective_model: str
    ) -> Any:
        """Synchronize the request object with the resolved target.

        Args:
            request: The chat request
            backend_type: The resolved backend type
            effective_model: The resolved model

        Returns:
            Updated request object
        """
        ...

    @abstractmethod
    async def prepare_backend_request(
        self,
        request: Any,
        backend_type: str,
        session: Any | None,
        uri_params: dict[str, str],
    ) -> Any:
        """Prepare the request domain object for the backend.

        Args:
            request: The chat request
            backend_type: The backend type
            session: The session object
            uri_params: URI parameters

        Returns:
            The prepared backend request object
        """
        ...

    @abstractmethod
    def prepare_backend_kwargs(
        self,
        session_id_for_backend: str | None,
        session: Any | None,
        context: Any | None,
        backend_type: str,
    ) -> dict[str, Any]:
        """Prepare keyword arguments for the backend call.

        Args:
            session_id_for_backend: Session ID
            session: Session object
            context: Request context
            backend_type: Backend type

        Returns:
            Dictionary of kwargs for the backend call
        """
        ...


class IBackendInvoker(ABC):
    """Encapsulates backend acquisition and invocation."""

    @abstractmethod
    async def acquire_backend(self, backend_type: str, session_id: str | None) -> Any:
        """Get or create a backend instance.

        Args:
            backend_type: The backend name
            session_id: Optional session ID

        Returns:
            The backend instance (LLMBackend)
        """
        ...


class IWireCaptureOrchestrator(ABC):
    """Encapsulates outbound/inbound wire capture orchestration."""

    @abstractmethod
    async def prepare_wire_capture_context(
        self, backend_type: str, session: Any | None
    ) -> Any | None:
        """Prepare wire capture context (e.g. identity).

        Args:
            backend_type: The backend type
            session: The session object

        Returns:
            Identity object if applicable
        """
        ...

    @abstractmethod
    async def capture_wire_outbound(
        self,
        backend_type: str,
        effective_model: str,
        domain_request: Any,
        context: Any | None,
    ) -> None:
        """Capture outbound request payload.

        Args:
            backend_type: The backend type
            effective_model: The model name
            domain_request: The domain request object
            context: The request context
        """
        ...

    @abstractmethod
    def detect_key_name(self, backend_type: str) -> str | None:
        """Detect the key name for redaction.

        Args:
            backend_type: The backend type

        Returns:
            The detected key name or None
        """
        ...

    @abstractmethod
    async def capture_inbound_response(
        self,
        context: Any | None,
        session_id: str | None,
        backend_type: str,
        effective_model: str,
        key_name: str | None,
        response_content: Any,
    ) -> None:
        """Capture inbound response payload (best-effort).

        Args:
            context: Request context
            session_id: Session ID
            backend_type: Backend type
            effective_model: Model name
            key_name: Key name for redaction
            response_content: The response content
        """
        ...

    @abstractmethod
    def wrap_inbound_stream(
        self,
        context: Any | None,
        session_id: str | None,
        backend_type: str,
        effective_model: str,
        key_name: str | None,
        stream: AsyncIterator[bytes],
    ) -> AsyncIterator[bytes]:
        """Wrap inbound stream for wire capture.

        Args:
            context: Request context
            session_id: Session ID
            backend_type: Backend type
            effective_model: Model name
            key_name: Key name for redaction
            stream: The input byte stream

        Returns:
            Wrapped byte stream
        """
        ...


class IUsageAccountingOrchestrator(ABC):
    """Encapsulates usage recording and response wrapping."""

    @abstractmethod
    async def calculate_and_record_usage(
        self,
        domain_request: Any,
        request: Any,
        backend_type: str,
        effective_model: str,
        session: Any | None,
        session_id_for_backend: str | None,
    ) -> tuple[int, str | None, str | None]:
        """Calculate tokens and record request usage.

        Returns:
            Tuple of (outbound_tokens, ctp_record_id, ptb_record_id)
        """
        ...

    @abstractmethod
    async def wrap_response_for_usage(
        self,
        result: Any,
        outbound_tokens: int,
        ctp_record_id: str | None,
        ptb_record_id: str | None,
        start_time: float,
    ) -> Any:
        """Wrap response with usage tracking.

        Returns:
            Response with usage tracking applied
        """
        ...

    @abstractmethod
    async def handle_streaming_response(
        self,
        result: Any,
        backend_type: str,
        effective_model: str,
        context: Any | None,
        request: Any,
        session_id_for_backend: str | None,
    ) -> StreamingResponseEnvelope:
        """Handle streaming response with wire capture and session ID injection.

        Returns:
            Wrapped streaming response envelope
        """
        ...

    @abstractmethod
    async def handle_non_streaming_response(
        self,
        result: Any,
        backend_type: str,
        effective_model: str,
        session_id_for_backend: str | None,
    ) -> ResponseEnvelope:
        """Handle non-streaming response with usage recording.

        Returns:
            The response envelope
        """
        ...

    @abstractmethod
    async def handle_auth_failure(
        self,
        exc: Exception,
        backend: Any,
        backend_type: str,
        session_id_for_backend: str | None,
    ) -> None:
        """Handle authentication failure with backend lifecycle side effects."""
        ...

    @abstractmethod
    async def handle_backend_error(
        self,
        call_exc: Exception,
        backend_type: str,
        effective_model: str,
        context: Any | None,
        request: Any,
        backend: Any,
        normalized_exc: Exception | None = None,
    ) -> None:
        """Handle backend error with normalization and wire capture."""
        ...


class IFailureRecoveryExecutor(ABC):
    """Encapsulates retry/failover execution logic."""

    @abstractmethod
    async def check_complex_failover(
        self,
        request: Any,
        effective_model: str,
        backend_type: str,
        stream: bool,
        context: Any | None = None,
    ) -> bool:
        """Check if complex failover should be executed."""
        ...

    @abstractmethod
    async def execute_complex_failover(
        self,
        request: Any,
        effective_model: str,
        backend_type: str,
        stream: bool,
        call_completion_callback: Any,
        context: Any | None = None,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Execute complex failover strategy."""
        ...

    @abstractmethod
    async def apply_failure_recovery(
        self,
        error: Exception,
        model: str,
        backend_type: str,
        attempted_backends: list[str],
        start_time: float,
        is_streaming: bool,
        content_started: bool,
        request: Any,
        call_completion_callback: Any,
        context: Any | None = None,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Apply failure handling strategy to decide retry/failover."""
        ...
