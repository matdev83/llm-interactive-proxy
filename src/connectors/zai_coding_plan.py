from __future__ import annotations

import os
from typing import Any

from src.connectors.openai import OpenAIConnector
from src.core.common.exceptions import AuthenticationError
from src.core.domain.model_utils import parse_model_backend
from src.core.interfaces.configuration_interface import IAppIdentityConfig
from src.core.services.backend_registry import backend_registry


class ZaiCodingPlanBackend(OpenAIConnector):
    """
    LLMBackend implementation for ZAI's coding plan API (OpenAI compatible).
    Uses the OpenAI-style API at https://api.z.ai/api/coding/paas/v4
    """

    backend_type: str = "zai-coding-plan"
    _DEFAULT_MODEL: str = "glm-4.6"
    _LEGACY_MODEL: str = "claude-sonnet-4-20250514"
    _SUPPORTED_MODELS: tuple[str, ...] = (_DEFAULT_MODEL, _LEGACY_MODEL)
    _KILO_VERSION: str = "4.111.0"
    _KILO_USER_AGENT: str = f"Kilo-Code/{_KILO_VERSION}"

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
        # ZAI coding plan exposes OpenAI-compatible models; seed with supported list
        self.available_models = list(self._SUPPORTED_MODELS)

    def get_headers(
        self, identity: IAppIdentityConfig | None = None
    ) -> dict[str, str]:
        """Return request headers including Kilo-specific metadata."""
        headers = super().get_headers(identity=identity)
        headers.setdefault("User-Agent", self._KILO_USER_AGENT)
        headers.setdefault("HTTP-Referer", "https://kilocode.ai")
        headers.setdefault("X-Title", "Kilo Code")
        headers.setdefault("X-KiloCode-Version", self._KILO_VERSION)
        return headers

    async def list_models(
        self, api_base_url: str | None = None, **kwargs: Any
    ) -> dict[str, Any]:
        """Return available models for ZAI coding plan."""
        # Return local model list (API mirrors OpenAI format)
        return {
            "data": [
                {
                    "id": model,
                    "name": model,
                    "object": "model",
                    "created": index,
                    "owned_by": "zai",
                }
                for index, model in enumerate(self._SUPPORTED_MODELS, start=1)
            ]
        }

    async def get_available_models_async(self) -> list[str]:
        """Return list of available model IDs."""
        return list(self._SUPPORTED_MODELS)

    def get_available_models(self) -> list[str]:
        """Return list of available model IDs."""
        return list(self._SUPPORTED_MODELS)

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
        # Use OpenAI-style payload preparation while preserving the requested model
        payload = await super()._prepare_payload(
            request_data, processed_messages, effective_model
        )

        # Ensure stream flag is preserved for compatibility with Anthropic routing
        if hasattr(request_data, "stream"):
            payload["stream"] = bool(request_data.stream)

        requested_model = (
            effective_model
            or getattr(request_data, "model", None)
            or self._DEFAULT_MODEL
        )
        _, model_name = parse_model_backend(
            str(requested_model), default_backend=self.backend_type
        )
        normalized_model = model_name or self._DEFAULT_MODEL
        payload["model"] = normalized_model

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
