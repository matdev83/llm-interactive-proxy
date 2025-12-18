from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

from pydantic.types import JsonValue

from src.core.domain.usage_summary import UsageSummary


class ProcessedResponse:
    """Result of response processing."""

    def __init__(
        self,
        content: Any = "",
        usage: UsageSummary | None = None,
        metadata: dict[str, JsonValue] | None = None,
    ):
        """Initialize a processed response.

        Args:
            content: The response content
            usage: Usage information (canonical UsageSummary contract)
            metadata: Additional metadata (JSON-serializable values)
        """
        self.content = content
        self.usage = usage
        self.metadata = metadata or {}

    content: Any | None
    usage: UsageSummary | None = None
    metadata: dict[str, JsonValue] = {}


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
        context: dict[str, object] | None = None,
    ) -> ProcessedResponse:
        """Process a complete LLM response.

        Args:
            response: The raw LLM response
            session_id: The session ID associated with this request
            context: Optional contextual information for downstream middleware (JSON-serializable values)

        Returns:
            A processed response object
        """

    @abstractmethod
    def process_streaming_response(
        self,
        response_iterator: AsyncIterator[Any],
        session_id: str,
        context: dict[str, object] | None = None,
    ) -> AsyncIterator[ProcessedResponse]:
        """Process a streaming LLM response.

        Args:
            response_iterator: An async iterator of response chunks
            session_id: The session ID associated with this request
            context: Optional contextual information for downstream middleware (JSON-serializable values)

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
    """Interface for response feature middleware with enforced parity.

    This interface enforces explicit implementation of both streaming and
    non-streaming code paths through separate abstract methods. This ensures
    feature parity by design - developers MUST implement both paths.

    Use this interface for features that should work identically across
    streaming and non-streaming responses. For middleware that legitimately
    differs between paths, use IResponseMiddleware instead.

    The template method pattern is used: the process() method delegates to
    the appropriate path method based on is_streaming flag.

    Example:
        class MyFeature(IResponseFeature):
            async def process_non_streaming(self, response, session_id, context):
                # Non-streaming implementation
                return self._apply_feature(response)

            async def process_streaming(self, chunk, session_id, context):
                # Streaming implementation - must provide equivalent feature
                return self._apply_feature(chunk)

            def _apply_feature(self, data):
                # Shared logic for both paths
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

        Returns FeatureCapability.BOTH by default since this interface
        enforces dual-path implementation. Override only if the feature
        intentionally provides no-op for one path.
        """
        return FeatureCapability.BOTH

    @abstractmethod
    async def process_non_streaming(
        self,
        response: Any,
        session_id: str,
        context: dict[str, object],
    ) -> Any:
        """Process a non-streaming response.

        This method MUST be implemented to handle complete responses.
        It should provide equivalent functionality to process_streaming.

        Args:
            response: The complete response to process
            session_id: The session ID associated with this request
            context: Additional context for processing (JSON-serializable values)

        Returns:
            The processed response
        """

    @abstractmethod
    async def process_streaming(
        self,
        chunk: Any,
        session_id: str,
        context: dict[str, object],
    ) -> Any:
        """Process a streaming chunk.

        This method MUST be implemented to handle streaming chunks.
        It should provide equivalent functionality to process_non_streaming.

        Args:
            chunk: The streaming chunk to process
            session_id: The session ID associated with this request
            context: Additional context for processing (JSON-serializable values)

        Returns:
            The processed chunk
        """

    async def process(
        self,
        response: Any,
        session_id: str,
        context: dict[str, object],
        is_streaming: bool = False,
        stop_event: Any = None,
    ) -> Any:
        """Process a response using the appropriate path.

        This is the template method that delegates to the correct
        implementation based on the streaming flag. Do not override
        this method - implement process_streaming and process_non_streaming.

        Args:
            response: The response or chunk to process
            session_id: The session ID associated with this request
            context: Additional context for processing (JSON-serializable values)
            is_streaming: Whether this is a streaming chunk
            stop_event: Optional event to signal early termination

        Returns:
            The processed response or chunk
        """
        if is_streaming:
            return await self.process_streaming(response, session_id, context)
        return await self.process_non_streaming(response, session_id, context)
