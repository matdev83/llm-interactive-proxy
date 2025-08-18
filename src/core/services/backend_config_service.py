from __future__ import annotations

import logging
from typing import Any, cast

from src.core.config.app_config import AppConfig
from src.core.domain.chat import ChatRequest
from src.core.domain.configuration.gemini_config import GeminiGenerationConfig

logger = logging.getLogger(__name__)


class BackendConfigService:
    """Service for managing backend-specific configurations.

    This service applies backend-specific configurations to requests based on
    the backend type and available configuration options.
    """

    def apply_backend_config(
        self,
        request: ChatRequest,
        backend_type: str,
        config: AppConfig,
    ) -> ChatRequest:
        """Apply backend-specific configuration to a request.

        Args:
            request: The chat completion request
            backend_type: The backend type

        Returns:
            The updated request with backend-specific configuration applied
        """
        if backend_type == "gemini":
            return self._apply_gemini_config(request)
        elif backend_type == "openai":
            return self._apply_openai_config(request)
        else:
            # No special handling for other backends
            return request

    def _apply_gemini_config(self, request: ChatRequest) -> ChatRequest:
        """Apply Gemini-specific configuration to a request.

        Args:
            request: The chat completion request

        Returns:
            The updated request with Gemini-specific configuration applied
        """
        extra_body = dict(request.extra_body or {})

        # Create a base Gemini generation config
        gemini_config = GeminiGenerationConfig()

        # Apply thinking budget if specified
        if request.extra_body and request.extra_body.get("thinking_budget") is not None:
            gemini_config = gemini_config.with_thinking_budget(
                cast(int, request.extra_body.get("thinking_budget"))
            )

        # Apply temperature if specified
        if request.temperature is not None:
            gemini_config = gemini_config.with_temperature(request.temperature)

        # Apply generation config if specified
        if request.extra_body and request.extra_body.get("generation_config"):
            try:
                gemini_config = gemini_config.with_generation_config(
                    cast(
                        str | dict[str, Any],
                        request.extra_body.get("generation_config"),
                    )
                )
            except Exception as e:
                logger.warning(f"Failed to apply Gemini generation config: {e}")

        # Add the generation config to the extra params
        extra_body["gemini_generation_config"] = gemini_config.to_dict()

        # Create a new request with the updated extra params
        # Create a new ChatRequest-like dict and set extra_params in extra_body
        rd = request.model_dump(exclude_none=True)
        rd.setdefault("extra_body", {})
        rd["extra_body"]["gemini_generation_config"] = gemini_config.to_dict()
        # Convert back to domain ChatRequest
        return ChatRequest(**rd)

    def _apply_openai_config(self, request: ChatRequest) -> ChatRequest:
        """Apply OpenAI-specific configuration to a request.

        Args:
            request: The chat completion request

        Returns:
            The updated request with OpenAI-specific configuration applied
        """
        # No special handling for OpenAI requests yet; return domain request
        return request
