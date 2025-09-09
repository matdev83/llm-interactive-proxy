from __future__ import annotations

import os
from typing import Any, cast

from src.connectors.anthropic import AnthropicBackend
from src.core.common.exceptions import AuthenticationError
from src.core.domain.chat import ChatRequest
from src.core.services.backend_registry import backend_registry


class ZaiCodingPlanBackend(AnthropicBackend):
    """
    LLMBackend implementation for ZAI's coding plan API (Anthropic compatible).
    """

    backend_type: str = "zai-coding-plan"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # The base URL is set in the `initialize` method.
        self.auth_header_name = "Authorization"

    async def initialize(self, **kwargs: Any) -> None:
        """Initialize the ZAI coding plan backend."""
        # Get API key from environment or kwargs
        self.api_key = kwargs.get("api_key") or os.environ.get("ZAI_API_KEY")
        self.key_name = (
            "zai_api_key"  # Dummy key name for AnthropicBackend compatibility
        )
        self.anthropic_api_base_url = kwargs.get(
            "anthropic_api_base_url", "https://api.z.ai/api/anthropic/v1"
        )
        ts = kwargs.get("translation_service")
        if ts is not None:
            from src.core.services.translation_service import TranslationService

            self.translation_service = cast(TranslationService, ts)
        self.auth_header_name = kwargs.get("auth_header_name", "Authorization")

        if not self.api_key:
            raise AuthenticationError(
                message="ZAI_API_KEY environment variable not set",
                code="missing_api_key",
            )

        # Don't call super().initialize() as it has different requirements

    def _prepare_anthropic_payload(
        self,
        request_data: ChatRequest,
        processed_messages: list[Any],
        effective_model: str,
        project: str | None,
    ) -> dict[str, Any]:
        payload = super()._prepare_anthropic_payload(
            request_data,
            processed_messages,
            effective_model,
            project,
        )
        payload["model"] = "claude-sonnet-4-20250514"
        # Remove non-Anthropic fields that may be injected via extra_body
        allowed_keys = {
            "model",
            "messages",
            "system",
            "max_tokens",
            "stream",
            "temperature",
            "top_p",
            "top_k",
            "metadata",
            "stop_sequences",
            "tools",
            "tool_choice",
        }
        filtered = {k: v for k, v in payload.items() if k in allowed_keys}
        return filtered

    async def list_models(self, **kwargs: Any) -> list[dict[str, Any]]:
        return [
            {
                "id": "claude-sonnet-4-20250514",
                "name": "claude-sonnet-4-20250514",
                "object": "model",
                "created": 1,
                "owned_by": "zai",
            }
        ]

    async def get_available_models_async(self) -> list[str]:
        return ["claude-sonnet-4-20250514"]

    def get_available_models(self) -> list[str]:
        return ["claude-sonnet-4-20250514"]

    async def chat_completions(self, *args: Any, **kwargs: Any) -> Any:
        if not self.api_key:
            raise AuthenticationError(
                message="ZAI_API_KEY environment variable not set",
                code="missing_api_key",
            )

        # Use exact KiloCode headers for ZAI server identification
        headers = {
            self.auth_header_name: f"Bearer {self.api_key}",
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
            "User-Agent": "Kilo-Code/4.84.0",
            "HTTP-Referer": "https://kilocode.ai",
            "X-Title": "Kilo Code",
            "X-KiloCode-Version": "4.84.0",
        }

        kwargs["headers"] = headers

        return await super().chat_completions(*args, **kwargs)

    async def _handle_non_streaming_response(
        self, url: str, payload: dict, headers: dict, original_model: str
    ) -> Any:
        """Override to handle ZAI-specific error responses."""
        from src.core.common.exceptions import BackendError
        from src.core.domain.responses import ResponseEnvelope

        try:
            response = await self.client.post(url, json=payload, headers=headers)
        except Exception as e:
            from src.core.common.exceptions import ServiceUnavailableError

            raise ServiceUnavailableError(message=f"Could not connect to ZAI API: {e}")

        # ZAI returns 200 status even for errors, so we need to check the response content
        try:
            import logging as _logging

            if _logging.getLogger(__name__).isEnabledFor(_logging.INFO):
                _logging.getLogger(__name__).info(
                    "ZAI POST %s headers=%s payload=%s", url, headers, payload
                )
            data = response.json()
        except Exception:
            # If we can't parse JSON, let the parent class handle it
            return await super()._handle_non_streaming_response(
                url, payload, headers, original_model
            )

        # Check if this is a ZAI error response
        if isinstance(data, dict) and data.get("success") is False:
            error_code = data.get("code", 500)
            error_msg = data.get("msg", "Unknown error from ZAI API")
            raise BackendError(
                message=f"ZAI API error: {error_msg}",
                code="zai_api_error",
                status_code=error_code,
                details={"zai_response": data},
            )

        response_envelope = ResponseEnvelope(
            content=data,
            headers=dict(response.headers),
            status_code=response.status_code,
        )

        # Rewrite the model in the response to include the zai-coding-plan prefix
        if (
            isinstance(response_envelope.content, dict)
            and "model" in response_envelope.content
        ):
            response_envelope.content["model"] = original_model
        return response_envelope


backend_registry.register_backend("zai-coding-plan", ZaiCodingPlanBackend)
