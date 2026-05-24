from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

from pydantic.types import JsonValue

from src.core.domain.request_context import RequestContext
from src.core.domain.usage_summary import UsageSummary

# Typed contract for processed chunk content crossing boundaries
ProcessedChunkContent = bytes | str | dict[str, JsonValue] | None


class ProcessedResponse:
    """Result of response processing."""

    def __init__(
        self,
        content: ProcessedChunkContent = "",
        usage: UsageSummary | None = None,
        metadata: dict[str, JsonValue] | None = None,
    ):
        """Initialize a processed response.

        Args:
            content: The response content (JSON dict with JsonValue values, string, bytes, or None)
            usage: Usage information (canonical UsageSummary contract)
            metadata: Additional metadata (JSON-serializable values)
        """
        self.content = content
        self.usage = usage
        # No mutable class-level default - create new dict instance per object
        self.metadata = metadata if metadata is not None else {}

    content: ProcessedChunkContent
    usage: UsageSummary | None = None
    metadata: dict[str, JsonValue]


class IResponseProcessor(ABC):
    """Interface for response processing operations.

    This interface defines the contract for components that process
    LLM responses before returning them to clients.
    """

    @abstractmethod
    async def process_response(
        self,
        response: Any,
        session_id: str,
        context: RequestContext | None = None,
    ) -> ProcessedResponse:
        """Process a complete LLM response.

        Args:
            response: The raw LLM response
            session_id: The session ID associated with this request
            context: Optional request context with processing metadata

        Returns:
            A processed response object
        """

    @abstractmethod
    def process_streaming_response(
        self,
        response_iterator: AsyncIterator[Any],
        session_id: str,
        context: RequestContext | None = None,
    ) -> AsyncIterator[ProcessedResponse]:
        """Process a streaming LLM response.

        Args:
            response_iterator: An async iterator of response chunks
            session_id: The session ID associated with this request
            context: Optional request context with processing metadata

        Returns:
            An async iterator of processed response chunks
        """

    @abstractmethod
    async def register_middleware(
        self, middleware: IResponseMiddleware, priority: int = 0
    ) -> None:
        """Register a middleware component to process responses.

        Args:
            middleware: The middleware component to register
            priority: The priority of the middleware (higher numbers run first)
        """


class IResponseMiddleware(ABC):
    """Interface for response middleware components.

    Response middleware components can modify or enhance responses
    before they are returned to the client.
    """

    def __init__(self, priority: int = 0) -> None:
        self._priority = priority

    @property
    def priority(self) -> int:
        return self._priority

    @abstractmethod
    async def process(
        self,
        response: Any,
        session_id: str,
        context: dict[str, object],
        is_streaming: bool = False,
        stop_event: Any = None,
    ) -> Any:
        """Process a response or response chunk.
        Args:
            response: The response or chunk to process
            session_id: The session ID associated with this request
            context: Additional context for processing (JSON-serializable values)
            is_streaming: A boolean indicating if the middleware is applied during streaming.
            stop_event: An optional event to signal early termination during streaming.
        Returns:
            The processed response or chunk
        """


class FeatureCapability:
    """Capability flags for feature middleware.

    These flags indicate what capabilities a feature supports,
    enabling runtime validation of feature parity.
    """

    STREAMING = "streaming"
    NON_STREAMING = "non_streaming"
    BOTH = "both"


class IResponseFeature(ABC):
    """Interface for response feature middleware with a single canonical path.

    Features implement :meth:`process_chunk` once; :meth:`process` forwards to it
    with the requested streaming flag. Mode-specific behavior uses
    ``is_streaming`` and typed lifecycle data attached to ``context`` (see
    ``FEATURE_LIFECYCLE_CONTEXT_KEY`` in ``feature_lifecycle_context``).

    Use this interface for features in the unified response pipeline. For
    components that only expose the legacy shape, use :class:`IResponseMiddleware`.

    Example:
        class MyFeature(IResponseFeature):
            async def process_chunk(self, payload, session_id, context, *, is_streaming: bool):
                return self._apply_feature(payload)

            def _apply_feature(self, data: Any) -> Any:
                ...
    """

    def __init__(self, priority: int = 0) -> None:
        """Initialize the feature middleware.

        Args:
            priority: Execution priority (higher numbers run first)
        """
        self._priority = priority

    @property
    def priority(self) -> int:
        """Get the feature priority."""
        return self._priority

    @property
    def feature_name(self) -> str:
        """Get the feature name for registration and logging.

        Default implementation returns the class name.
        Override for custom feature names.
        """
        return self.__class__.__name__

    @property
    def capability(self) -> str:
        """Get the feature capability.

        Returns FeatureCapability.BOTH by default. Override when the feature
        intentionally no-ops for one mode (see :class:`FeatureCapability`).
        """
        return FeatureCapability.BOTH

    @abstractmethod
    async def process_chunk(
        self,
        payload: Any,
        session_id: str,
        context: dict[str, object],
        *,
        is_streaming: bool,
    ) -> Any:
        """Process one response unit (full non-streaming response or streaming chunk).

        Sole required implementation path. Use ``is_streaming`` and lifecycle
        fields in ``context`` for mode-sensitive logic.

        Args:
            payload: Response or chunk to process
            session_id: Session identifier for this request
            context: Processing context (may include ``stop_event`` from :meth:`process`)
            is_streaming: True when invoked on the streaming chunk path

        Returns:
            Processed payload
        """

    async def process(
        self,
        response: Any,
        session_id: str,
        context: dict[str, object],
        is_streaming: bool = False,
        stop_event: Any = None,
    ) -> Any:
        """Forward to :meth:`process_chunk` (do not override in subclasses).

        Args:
            response: The response or chunk to process
            session_id: The session ID associated with this request
            context: Additional context for processing (JSON-serializable values)
            is_streaming: Whether this is a streaming chunk
            stop_event: Optional event to signal early termination

        Returns:
            The processed response or chunk
        """
        effective_context = (
            {**context, "stop_event": stop_event} if stop_event is not None else context
        )
        return await self.process_chunk(
            response,
            session_id,
            effective_context,
            is_streaming=is_streaming,
        )
