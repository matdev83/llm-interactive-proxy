"""
Backend configuration service for managing backend-specific configurations.

This service provides methods for applying backend-specific configurations to requests.
"""

from __future__ import annotations

import logging

from src.constants import BackendType
from src.core.domain.configuration.gemini_config import GeminiGenerationConfig
from src.models import ChatCompletionRequest

logger = logging.getLogger(__name__)


class BackendConfigService:
    """Service for managing backend-specific configurations.

    This service applies backend-specific configurations to requests based on
    the backend type and available configuration options.
    """

    def apply_backend_config(
        self,
        request: ChatCompletionRequest,
        backend_type: str,
    ) -> ChatCompletionRequest:
        """Apply backend-specific configuration to a request.

        Args:
            request: The chat completion request
            backend_type: The backend type

        Returns:
            The updated request with backend-specific configuration applied
        """
        if backend_type == BackendType.GEMINI:
            return self._apply_gemini_config(request)
        elif backend_type == BackendType.OPENAI:
            return self._apply_openai_config(request)
        else:
            # No special handling for other backends
            return request

    def _apply_gemini_config(
        self, request: ChatCompletionRequest
    ) -> ChatCompletionRequest:
        """Apply Gemini-specific configuration to a request.

        Args:
            request: The chat completion request

        Returns:
            The updated request with Gemini-specific configuration applied
        """
        extra_body = dict(request.extra_params or {})

        # Create a base Gemini generation config
        gemini_config = GeminiGenerationConfig()

        # Apply thinking budget if specified
        if request.thinking_budget is not None:
            gemini_config = gemini_config.with_thinking_budget(request.thinking_budget)

        # Apply temperature if specified
        if request.temperature is not None:
            gemini_config = gemini_config.with_temperature(request.temperature)

        # Apply generation config if specified
        if request.generation_config:
            try:
                gemini_config = gemini_config.with_generation_config(
                    request.generation_config
                )
            except Exception as e:
                logger.warning(f"Failed to apply Gemini generation config: {e}")

        # Add the generation config to the extra params
        extra_body["gemini_generation_config"] = gemini_config.to_dict()

        # Create a new request with the updated extra params
        updated_request = ChatCompletionRequest(
            **{
                **request.model_dump(exclude={"extra_params"}),
                "extra_params": extra_body,
            }
        )

        return updated_request

    def _apply_openai_config(
        self, request: ChatCompletionRequest
    ) -> ChatCompletionRequest:
        """Apply OpenAI-specific configuration to a request.

        Args:
            request: The chat completion request

        Returns:
            The updated request with OpenAI-specific configuration applied
        """
        # No special handling for OpenAI requests yet
        return request
