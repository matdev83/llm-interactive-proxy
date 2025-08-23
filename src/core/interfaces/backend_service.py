from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

from src.core.domain.chat import ChatRequest, ChatResponse, StreamingChatResponse


class BackendError(Exception):
    """Exception raised when a backend operation fails."""


# Legacy alias for backward compatibility
BackendException = BackendError


class IBackendService(ABC):
    """Interface for LLM backend service operations.

    This interface defines the contract for components that interact with
    LLM backend services like OpenAI, Anthropic, etc.
    """

    @abstractmethod
    async def call_completion(
        self, request: ChatRequest, stream: bool = False
    ) -> ChatResponse | AsyncIterator[StreamingChatResponse]:
        """Call the LLM backend for a completion.

        Args:
            request: The chat completion request
            stream: Whether to stream the response

        Returns:
            Either a complete response or an async iterator of response chunks

        Raises:
            BackendException: If the backend call fails
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
    ) -> ChatResponse | AsyncIterator[StreamingChatResponse]: ...
