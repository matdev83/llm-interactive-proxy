from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any


class ProcessedResponse:
    """Result of response processing."""

    def __init__(
        self,
        content: str = "",
        usage: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ):
        """Initialize a processed response.

        Args:
            content: The response content
            usage: Usage information
            metadata: Additional metadata
        """
        self.content = content
        self.usage = usage
        self.metadata = metadata or {}

    content: str | None
    usage: dict[str, Any] | None = None
    metadata: dict[str, Any] = {}


class IResponseProcessor(ABC):
    """Interface for response processing operations.

    This interface defines the contract for components that process
    LLM responses before returning them to clients.
    """

    @abstractmethod
    async def process_response(
        self, response: Any, session_id: str
    ) -> ProcessedResponse:
        """Process a complete LLM response.

        Args:
            response: The raw LLM response
            session_id: The session ID associated with this request

        Returns:
            A processed response object
        """

    @abstractmethod
    def process_streaming_response(
        self, response_iterator: AsyncIterator[Any], session_id: str
    ) -> AsyncIterator[ProcessedResponse]:
        """Process a streaming LLM response.

        Args:
            response_iterator: An async iterator of response chunks
            session_id: The session ID associated with this request

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
        self, response: Any, session_id: str, context: dict[str, Any]
    ) -> Any:
        """Process a response or response chunk.

        Args:
            response: The response or chunk to process
            session_id: The session ID associated with this request
            context: Additional context for processing

        Returns:
            The processed response or chunk
        """
