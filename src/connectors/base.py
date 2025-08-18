from __future__ import annotations

import abc
from typing import TYPE_CHECKING, Any

from starlette.responses import StreamingResponse

if TYPE_CHECKING:
    from src.core.domain.chat import ChatRequest


class LLMBackend(abc.ABC):
    """
    Abstract base class for Large Language Model (LLM) backends.
    Defines the interface for interacting with different LLM providers.
    """

    backend_type: str

    @abc.abstractmethod
    async def chat_completions(
        self,
        request_data: ChatRequest,
        processed_messages: list,  # Messages after command processing (domain objects or dicts)
        effective_model: str,  # Model after considering override
        **kwargs: Any,
    ) -> StreamingResponse | tuple[dict[str, Any], dict[str, str]]:
        """
        Forwards a chat completion request to the LLM backend.

        Args:
            request_data: The request payload as a domain `ChatRequest`.
            processed_messages: The list of messages after command processing.
            effective_model: The model name to be used after considering any overrides.
            **kwargs: Additional keyword arguments for the backend.

        Returns:
            A StreamingResponse if the request is for a stream, or a tuple containing
            a dictionary representing the JSON response and a dictionary of headers
            for a non-streaming request.
        """

    @abc.abstractmethod
    async def initialize(self, **kwargs: Any) -> None:
        """
        Initialize the backend with configuration.

        Args:
            **kwargs: Configuration parameters for the backend.
        """

    def get_available_models(self) -> list[str]:
        """
        Get a list of available models for this backend.

        Returns:
            A list of model identifiers supported by this backend.
        """
        return []
