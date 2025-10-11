from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from src.connectors.base import LLMBackend
from src.core.domain.chat import ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import (
    ResponseEnvelope,
    StreamingResponseEnvelope,
)


class IBackendService(ABC):
    """Interface for LLM backend service operations.

    This interface defines the contract for components that interact with
    LLM backend services like OpenAI, Anthropic, etc.
    """

    @abstractmethod
    async def call_completion(
        self,
        request: ChatRequest,
        stream: bool = False,
        allow_failover: bool = True,
        context: RequestContext | None = None,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Call the LLM backend for a completion.

        Args:
            request: The chat completion request
            stream: Whether to stream the response

        Returns:
            Either a complete response or an async iterator of response chunks

        Raises:
            BackendError: If the backend call fails
        """

    @abstractmethod
    async def validate_backend_and_model(
        self, backend: str, model: str
    ) -> tuple[bool, str | None]:
        """Validate that a backend and model combination is valid.

        Args:
            backend: The backend identifier
            model: The model identifier

        Returns:
            A tuple of (is_valid, error_message)
        """

    async def chat_completions(
        self,
        request: ChatRequest,
        *,
        stream: bool = False,
        allow_failover: bool = True,
        context: RequestContext | None = None,
        **kwargs: Any,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Alias for :meth:`call_completion` used by legacy callers.

        Implementers may override this method, but by default it simply
        delegates to :meth:`call_completion` to avoid forcing duplicate
        implementations when only the primary entry point is customised.
        Additional keyword arguments are accepted for backward
        compatibility, though they are ignored by the default
        implementation.
        """

        return await self.call_completion(
            request,
            stream=stream,
            allow_failover=allow_failover,
            context=context,
        )

    def get_backend(self, backend_type: str) -> LLMBackend:
        """Get a backend instance synchronously (for testing purposes).

        Args:
            backend_type: The type of backend to get

        Returns:
            A backend instance
        """
        raise NotImplementedError("Subclasses must implement get_backend")
