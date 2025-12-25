"""
ZAI connector for Zhipu AI's GLM models
"""

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
import yaml

from src.core.common.exceptions import AuthenticationError, ConfigurationError
from src.core.config.app_config import AppConfig
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.domain.session_key import SessionKey
from src.core.interfaces.configuration_interface import IAppIdentityConfig
from src.core.security.loop_prevention import ensure_loop_guard_header
from src.core.services.backend_registry import backend_registry

from .base import add_vendor_prefix
from .openai import OpenAIConnector

if TYPE_CHECKING:
    from src.core.services.translation_service import TranslationService


logger = logging.getLogger(__name__)


class ZAIConnector(OpenAIConnector):
    """ZAI backend connector for Zhipu AI's GLM models."""

    backend_type: str = "zai"

    # Vendor prefix for Zhipu AI models in unified model routing
    VENDOR_PREFIX: str | None = "zhipu"

    def __init__(
        self,
        client: httpx.AsyncClient,
        config: AppConfig,
        translation_service: "TranslationService | None" = None,
    ) -> None:
        super().__init__(client, config, translation_service=translation_service)
        self.api_base_url = "https://open.bigmodel.cn/api/paas/v4"
        self.name = "zai"
        # Load default models from YAML config file
        self._default_models = self._load_default_models()

    def _load_default_models(self) -> list[str]:
        """Load default models from YAML configuration file."""
        config_path = (
            Path(__file__).parent.parent.parent
            / "config"
            / "backends"
            / "zai"
            / "default_models.yaml"
        )
        try:
            with open(config_path, encoding="utf-8") as f:
                config = yaml.safe_load(f)
                models = config.get("models", []) if isinstance(config, dict) else []
                if isinstance(models, list) and models:
                    return models
                # If the config file exists but has no models, fall back to hardcoded defaults
                return ["glm-4.5", "glm-4.5-flash", "glm-4.5-air"]
        except Exception:
            # Fallback to hardcoded models if config file is not found or invalid
            return ["glm-4.5", "glm-4.5-flash", "glm-4.5-air"]

    async def initialize(self, **kwargs: Any) -> None:
        """Initialize the connector and fetch available models."""
        self.api_key = kwargs.get("api_key")
        if not self.api_key:
            raise ConfigurationError(
                message="api_key is required for ZAIConnector", code="missing_api_key"
            )

        api_base_url = kwargs.get("api_base_url")
        if api_base_url:
            self.api_base_url = api_base_url

        # Load models
        await self._ensure_models_loaded()

    async def _ensure_models_loaded(self) -> None:
        """Ensure models are loaded, either from API or defaults."""
        # Initialize available_models if not already set
        if not hasattr(self, "available_models"):
            self.available_models = []

        # If we already have models, no need to reload
        if self.available_models:
            return

        # Try to fetch models from /models endpoint
        try:
            data = await self.list_models()
            models = [m.id for m in data.data if m.id]

            # If we successfully fetched models, use them
            if models:
                self.available_models = models
                return
        except Exception as e:
            # Log the exception for debugging
            import logging

            logging.debug("Error fetching models from API: %s", e, exc_info=True)

        # If we get here, either the API call failed or returned no models
        # Use default models from config
        if not self.available_models:
            self.available_models = self._default_models.copy()

    def get_headers(self, identity: IAppIdentityConfig | None = None) -> dict[str, str]:
        """Get headers with ZAI API key."""
        if not self.api_key:
            raise AuthenticationError(
                message="ZAI API key is not set.", code="missing_api_key"
            )
        return ensure_loop_guard_header(
            {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
        )

    def get_available_models(self) -> list[str]:
        """Get available models with vendor prefix for unified model routing.

        Returns:
            List of model names with 'zhipu/' vendor prefix.
            For example: ['zhipu/glm-4', 'zhipu/glm-4-plus']
        """
        raw_models = (
            self.available_models
            if hasattr(self, "available_models") and self.available_models
            else self._default_models.copy()
        )
        if self.VENDOR_PREFIX is None:
            return raw_models
        return [add_vendor_prefix(m, self.VENDOR_PREFIX) for m in raw_models]

    async def _prepare_payload(
        self,
        request_data: Any,
        processed_messages: list[Any],
        effective_model: str,
    ) -> dict[str, Any]:
        """
        Prepare payload for ZAI backend with 200K max_tokens support.

        ZAI backend supports up to 200K output tokens. This method ensures
        max_tokens is set appropriately based on client request.
        """
        payload = await super()._prepare_payload(
            request_data, processed_messages, effective_model
        )

        def _extract_param(name: str) -> Any | None:
            value = getattr(request_data, name, None)
            if value is None and isinstance(request_data, dict):
                value = request_data.get(name)
            if value is None:
                extra_body = getattr(request_data, "extra_body", None)
                if isinstance(extra_body, dict):
                    value = extra_body.get(name)
            return value

        top_p = _extract_param("top_p")
        if top_p is not None:
            try:
                payload["top_p"] = float(top_p)
            except (TypeError, ValueError):
                logger.debug("Ignoring non-numeric top_p value for ZAI: %r", top_p)

        top_k = _extract_param("top_k")
        if top_k is not None:
            try:
                payload["top_k"] = int(top_k)
            except (TypeError, ValueError):
                logger.debug("Ignoring non-integer top_k value for ZAI: %r", top_k)

        # ZAI currently breaks tool calling when reasoning is enabled. The upstream
        # service does not support the OpenAI reasoning payload, so strip any
        # client-specified reasoning configuration before sending the request.
        removed_reasoning = bool(payload.pop("reasoning", None))
        removed_effort = bool(payload.pop("reasoning_effort", None))
        if removed_reasoning or removed_effort:
            logger.debug(
                "Dropping reasoning payload for ZAI backend because it is not supported"
            )

        # ZAI backend supports up to 200K output tokens
        # Override max_tokens only if client explicitly set a valid positive value
        requested_max_tokens = getattr(request_data, "max_tokens", None)

        if requested_max_tokens is not None and requested_max_tokens > 0:
            # Client explicitly requested a value - validate and clamp to valid range
            # Only enforce maximum limit, allow any positive value as minimum
            if requested_max_tokens > 200000:  # 200K
                payload["max_tokens"] = 200000
            else:
                payload["max_tokens"] = requested_max_tokens
        else:
            # No explicit request or invalid value (None, 0, negative) - use ZAI's max
            payload["max_tokens"] = 200000  # 200K default for ZAI

        return payload

    async def chat_completions(
        self,
        request_data: Any,
        processed_messages: list[Any],
        effective_model: str,
        identity: IAppIdentityConfig | None = None,
        cancellation_token: SessionKey | None = None,
        cancellation_coordinator: (
            Any | None
        ) = None,  # ISessionCancellationCoordinator | None
        **kwargs: Any,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        response_envelope = await super().chat_completions(
            request_data=request_data,
            processed_messages=processed_messages,
            effective_model=effective_model,
            identity=identity,
            cancellation_token=cancellation_token,
            cancellation_coordinator=cancellation_coordinator,
            **kwargs,
        )

        # If streaming, wrap the content (connector-agnostic pipeline will repair JSON)
        if (
            isinstance(response_envelope, StreamingResponseEnvelope)
            and self.config.session.json_repair_enabled
        ):
            from collections.abc import AsyncGenerator, AsyncIterator

            from src.core.interfaces.response_processor_interface import (
                ProcessedResponse,
            )

            # No-op helpers previously used for byte<->str conversions removed

            async def _process_stream(
                stream: AsyncIterator[ProcessedResponse],
            ) -> AsyncGenerator[ProcessedResponse, None]:
                async for item in stream:
                    if isinstance(item.content, bytes):
                        yield ProcessedResponse(
                            content=item.content.decode("utf-8", errors="ignore")
                        )
                    else:
                        yield item

            stream_content = response_envelope.content
            if stream_content is not None:
                response_envelope.content = _process_stream(stream_content)

        return response_envelope


backend_registry.register_backend("zai", ZAIConnector)
