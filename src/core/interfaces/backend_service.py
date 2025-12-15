from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from src.connectors.base import LLMBackend
from src.core.common.exceptions import BackendError
from src.core.domain.chat import ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope

__all__ = ["BackendError", "IBackendService"]


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

    @abstractmethod
    async def chat_completions(
        self, request: ChatRequest, **kwargs: Any
    ) -> ResponseEnvelope | StreamingResponseEnvelope: ...

    @abstractmethod
    def get_backend(self, backend_type: str) -> LLMBackend:
        """Get a backend instance synchronously (for testing purposes).

        Args:
            backend_type: The type of backend to get

        Returns:
            A backend instance
        """

    @abstractmethod
    def get_active_backends(self) -> dict[str, LLMBackend]:
        """Get all active backend instances.

        Returns:
             A dictionary mapping backend instance names to LLMBackend objects.
        """
