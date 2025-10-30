from __future__ import annotations

import os
from typing import Any

from src.connectors.openai import OpenAIConnector
from src.core.common.exceptions import AuthenticationError
from src.core.services.backend_registry import backend_registry


class ZaiCodingPlanBackend(OpenAIConnector):
    """
    LLMBackend implementation for ZAI's coding plan API (OpenAI compatible).
    Uses the OpenAI-style API at https://api.z.ai/api/coding/paas/v4
    """

    backend_type: str = "zai-coding-plan"

    async def initialize(self, **kwargs: Any) -> None:
        """Initialize the ZAI coding plan backend."""
        # Get API key from environment or kwargs
        self.api_key = kwargs.get("api_key") or os.environ.get("ZAI_API_KEY")

        if not self.api_key:
            raise AuthenticationError(
                message="ZAI_API_KEY environment variable not set",
                code="missing_api_key",
            )

        # Set the OpenAI-compatible API base URL for ZAI
        self.api_base_url = kwargs.get(
            "api_base_url", "https://api.z.ai/api/coding/paas/v4"
        )

        # For backward compatibility with tests
        self.anthropic_api_base_url = self.api_base_url

        # ZAI supports up to 128K output tokens
        self._max_tokens_limit = 131072  # 128K

    async def list_models(
        self, api_base_url: str | None = None, **kwargs: Any
    ) -> dict[str, Any]:
        """Return available models for ZAI coding plan."""
        # Return claude model for backward compatibility
        return {
            "data": [
                {
                    "id": "claude-sonnet-4-20250514",
                    "name": "claude-sonnet-4-20250514",
                    "object": "model",
                    "created": 1,
                    "owned_by": "zai",
                }
            ]
        }

    async def get_available_models_async(self) -> list[str]:
        """Return list of available model IDs."""
        # Return claude model for backward compatibility
        return ["claude-sonnet-4-20250514"]

    def get_available_models(self) -> list[str]:
        """Return list of available model IDs."""
        # Return claude model for backward compatibility
        return ["claude-sonnet-4-20250514"]

    def _prepare_headers(self, **kwargs: Any) -> dict[str, str]:
        """Prepare headers for ZAI API requests."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "Kilo-Code/4.84.0",
            "HTTP-Referer": "https://kilocode.ai",
            "X-Title": "Kilo Code",
            "X-KiloCode-Version": "4.84.0",
        }

        # Allow override from kwargs
        if "headers" in kwargs:
            headers.update(kwargs["headers"])

        return headers

    async def _prepare_payload(
        self,
        request_data: Any,
        processed_messages: Any = None,
        effective_model: str | None = None,
    ) -> dict[str, Any]:
        """Prepare request payload for ZAI API.

        Args:
            request_data: The request data
            processed_messages: Processed messages (for compatibility)
            effective_model: The effective model name (for compatibility)
        """
        # Use OpenAI-style payload preparation
        # Always use claude-sonnet-4-20250514 as the actual model for ZAI
        payload = {
            "model": "claude-sonnet-4-20250514",
            "messages": (
                processed_messages
                if processed_messages is not None
                else (
                    request_data.messages if hasattr(request_data, "messages") else []
                )
            ),
            "stream": request_data.stream if hasattr(request_data, "stream") else False,
        }

        # Handle max_tokens with ZAI's limits
        if hasattr(request_data, "max_tokens") and request_data.max_tokens:
            requested_max_tokens = request_data.max_tokens
            if requested_max_tokens > 0:
                # Clamp to valid range (1K minimum, 128K maximum)
                if requested_max_tokens < 1024:
                    payload["max_tokens"] = 1024
                elif requested_max_tokens > self._max_tokens_limit:
                    payload["max_tokens"] = self._max_tokens_limit
                else:
                    payload["max_tokens"] = requested_max_tokens
            else:
                # Use ZAI's maximum
                payload["max_tokens"] = self._max_tokens_limit
        else:
            # Default to ZAI's maximum
            payload["max_tokens"] = self._max_tokens_limit

        # Copy other optional parameters
        if (
            hasattr(request_data, "temperature")
            and request_data.temperature is not None
        ):
            payload["temperature"] = request_data.temperature
        if hasattr(request_data, "top_p") and request_data.top_p is not None:
            payload["top_p"] = request_data.top_p
        if hasattr(request_data, "tools") and request_data.tools:
            payload["tools"] = request_data.tools
        if hasattr(request_data, "tool_choice") and request_data.tool_choice:
            payload["tool_choice"] = request_data.tool_choice

        return payload


backend_registry.register_backend("zai-coding-plan", ZaiCodingPlanBackend)
