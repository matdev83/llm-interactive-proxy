from __future__ import annotations

import logging
from typing import Any

from src.connectors.openai import OpenAIConnector
from src.core.services.backend_registry import backend_registry

logger = logging.getLogger(__name__)


class OpenAIResponsesConnector(OpenAIConnector):
    """OpenAI Responses API connector that extends the base OpenAI connector.

    This connector specifically handles the OpenAI Responses API endpoint (/v1/responses)
    for structured output generation with JSON schema validation.
    """

    backend_type: str = "openai-responses"

    async def chat_completions(
        self,
        request_data: Any,
        processed_messages: list[Any],
        effective_model: str,
        identity: Any = None,
        **kwargs: Any,
    ) -> Any:
        """Override chat_completions to use the Responses API endpoint."""
        # For the Responses API backend, we should use the responses endpoint
        # Convert the chat completions request to a responses request
        if hasattr(request_data, "model_dump"):
            request_dict = request_data.model_dump()
        else:
            request_dict = request_data if isinstance(request_data, dict) else {}

        # Add response_format if not present (default to text for chat completions)
        if "response_format" not in request_dict:
            request_dict["response_format"] = {"type": "text"}

        # Delegate to the responses method for all requests
        return await self.responses(
            request_dict, processed_messages, effective_model, identity, **kwargs
        )


# Register the OpenAI Responses API backend
backend_registry.register_backend("openai-responses", OpenAIResponsesConnector)
