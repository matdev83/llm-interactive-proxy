from __future__ import annotations

import abc

from typing import TYPE_CHECKING, Any, Callable, Dict, Union

from starlette.responses import StreamingResponse

if TYPE_CHECKING:
    from src.models import (
        ChatCompletionRequest,
    )  # Corrected path assuming models.py is in src
    from src.security import APIKeyRedactor, ProxyCommandFilter


class LLMBackend(abc.ABC):
    """
    Abstract base class for Large Language Model (LLM) backends.
    Defines the interface for interacting with different LLM providers.
    """

    @abc.abstractmethod
    async def chat_completions(
        self,
        request_data: "ChatCompletionRequest",
        processed_messages: list,  # Messages after command processing
        effective_model: str,  # Model after considering override
        # This might need to be more generic if we have more backends
        openrouter_api_base_url: str,
        openrouter_headers_provider: Callable[
            [str, str], Dict[str, str]
        ],  # Same as above
        key_name: str,
        api_key: str,
        project: str | None = None,
        prompt_redactor: "APIKeyRedactor" | None = None,
        command_filter: "ProxyCommandFilter" | None = None,
    ) -> Union[StreamingResponse, Dict[str, Any]]:
        """
        Forwards a chat completion request to the LLM backend.

        Args:
            request_data: The request payload, conforming to ChatCompletionRequest model.
            processed_messages: The list of messages after command processing.
            effective_model: The model name to be used after considering any overrides.
            openrouter_api_base_url: The base URL for the OpenRouter API.
                                     (Will need generalization if supporting other backends)
            openrouter_headers_provider: A callable that returns a dictionary of headers
                                         required for OpenRouter API. (Needs generalization)
            key_name: The environment variable name of the API key in use.
            api_key: The secret value of the API key.
            prompt_redactor: Optional APIKeyRedactor used to sanitize messages.
            command_filter: Optional ProxyCommandFilter to remove leaked proxy commands.

        Returns:
            A StreamingResponse if the request is for a stream, or a dictionary
            representing the JSON response for a non-streaming request.
        """
        pass
