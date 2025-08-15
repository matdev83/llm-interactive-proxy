from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from src.core.domain.chat import ChatRequest, ChatResponse, StreamingChatResponse
from src.core.interfaces.backend_service import BackendError, IBackendService

logger = logging.getLogger(__name__)


class LegacyBackendAdapter(IBackendService):
    """
    Adapter to connect the new architecture's backend service interface
    to the legacy backend implementations.
    """

    def __init__(self, legacy_backend):
        """
        Initialize the adapter with a legacy backend instance.

        Args:
            legacy_backend: A legacy backend class instance
        """
        self._legacy_backend = legacy_backend

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
            BackendError: If the backend call fails
        """
        # Get the model from the request
        effective_model = request.model

        # Create the list of processed messages from the request
        processed_messages = request.messages

        # Prepare options based on request attributes
        options = {}
        if request.temperature is not None:
            options["temperature"] = request.temperature

        # Call the legacy backend
        if hasattr(self._legacy_backend, "chat_completions"):
            try:
                response = await self._legacy_backend.chat_completions(
                    request_data=request.to_legacy_format(),
                    processed_messages=processed_messages,
                    effective_model=effective_model,
                    stream=stream,
                    **options,
                )

                # Convert the response to a ChatResponse
                return ChatResponse.from_legacy_response(response)
            except Exception as e:
                raise BackendError(f"Backend call failed: {e!s}") from e

        # If chat_completions doesn't exist, try to use a different method
        # This is a fallback mechanism for older backends
        logger.warning(
            "Legacy backend does not implement chat_completions method, falling back. "
            f"Backend: {self._legacy_backend.__class__.__name__}"
        )

        # Default error response
        return ChatResponse(
            content="Error: Backend incompatible with new architecture",
            model=effective_model,
            usage={"total_tokens": 0, "prompt_tokens": 0, "completion_tokens": 0},
        )

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
        # Check if the legacy backend has a validate_model method
        if hasattr(self._legacy_backend, "validate_model"):
            try:
                is_valid = await self._legacy_backend.validate_model(model)
                if not is_valid:
                    return False, f"Model {model} is not valid for backend {backend}"
                return True, None
            except Exception as e:
                return False, str(e)

        # If no validation method exists, assume it's valid
        # This is a fallback mechanism for older backends
        return True, None
