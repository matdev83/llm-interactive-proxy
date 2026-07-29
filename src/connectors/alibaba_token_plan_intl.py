"""Alibaba Cloud international Token Plan connector using Anthropic Messages."""

from __future__ import annotations

import os
from dataclasses import replace
from typing import Any

import httpx

from src.connectors.anthropic import AnthropicBackend
from src.connectors.base import add_vendor_prefix, strip_vendor_prefix
from src.connectors.contracts import ConnectorChatCompletionsRequest
from src.core.common.exceptions import ConfigurationError
from src.core.config.app_config import AppConfig
from src.core.domain.models_listing import ModelsListingResponse
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.services.backend_registry import backend_registry
from src.core.services.translation_service import TranslationService

ALIBABA_TOKEN_PLAN_INTL_BACKEND_TYPE = "alibaba-token-plan-intl"
ALIBABA_TOKEN_PLAN_INTL_API_KEY_ENV = "ALIBABA_TOKEN_PLAN_API_KEY"
ALIBABA_TOKEN_PLAN_INTL_DEFAULT_BASE_URL = (
    "https://token-plan.ap-southeast-1.maas.aliyuncs.com/apps/anthropic/v1"
)
ALIBABA_TOKEN_PLAN_INTL_MODELS_BASE_URL = (
    "https://token-plan.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1"
)


class AlibabaTokenPlanIntlBackend(AnthropicBackend):
    """Anthropic-compatible connector for Alibaba's international Token Plan."""

    backend_type = ALIBABA_TOKEN_PLAN_INTL_BACKEND_TYPE

    def __init__(
        self,
        client: httpx.AsyncClient,
        config: AppConfig,
        translation_service: TranslationService,
    ) -> None:
        super().__init__(client, config, translation_service)
        self.available_models = []

    async def initialize(self, **kwargs: Any) -> None:
        api_key = os.environ.get(ALIBABA_TOKEN_PLAN_INTL_API_KEY_ENV, "").strip()
        if not api_key:
            raise ConfigurationError(
                message=(
                    f"{ALIBABA_TOKEN_PLAN_INTL_API_KEY_ENV} is required for "
                    f"{ALIBABA_TOKEN_PLAN_INTL_BACKEND_TYPE}"
                ),
                code="missing_config",
            )

        base_url = str(
            kwargs.get("anthropic_api_base_url")
            or kwargs.get("api_base_url")
            or ALIBABA_TOKEN_PLAN_INTL_DEFAULT_BASE_URL
        ).rstrip("/")
        await super().initialize(
            anthropic_api_base_url=base_url,
            key_name=ALIBABA_TOKEN_PLAN_INTL_BACKEND_TYPE,
            api_key=api_key,
            auth_header_name="x-api-key",
        )
        # Core routing consumes the synchronous model snapshot after initialization.
        await self.list_models(key_name=self.key_name, api_key=self.api_key)

    async def list_models(
        self,
        *,
        base_url: str | None = None,
        key_name: str | None = None,
        api_key: str | None = None,
    ) -> ModelsListingResponse:
        # Alibaba exposes Token Plan discovery on the paired OpenAI-compatible
        # endpoint; reuse the standard Anthropic listing/parser contract.
        return await super().list_models(
            base_url=ALIBABA_TOKEN_PLAN_INTL_MODELS_BASE_URL,
            key_name=key_name,
            api_key=api_key,
        )

    def get_available_models(self) -> list[str]:
        return [
            add_vendor_prefix(model, ALIBABA_TOKEN_PLAN_INTL_BACKEND_TYPE)
            for model in self.available_models
        ]

    async def get_available_models_async(self) -> list[str]:
        await self._ensure_models_loaded()
        return self.get_available_models()

    def _prepare_anthropic_payload(
        self,
        request_data: Any,
        processed_messages: list[Any],
        effective_model: str,
        project: str | None,
        context: Any | None = None,
    ) -> dict[str, Any]:
        normalized_messages: list[Any] = []
        for message in processed_messages:
            role = (
                message.get("role")
                if isinstance(message, dict)
                else getattr(message, "role", None)
            )
            if role in {"user", "system"}:
                normalized_messages.append(message)
            elif isinstance(message, dict):
                normalized_messages.append({**message, "role": "user"})
            elif hasattr(message, "model_copy"):
                normalized_messages.append(message.model_copy(update={"role": "user"}))
            else:
                normalized_messages.append(message)

        return super()._prepare_anthropic_payload(
            request_data,
            normalized_messages,
            effective_model,
            project,
            context,
        )

    async def _chat_completions_canonical(
        self, request: ConnectorChatCompletionsRequest
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        raw_model = strip_vendor_prefix(
            request.effective_model, ALIBABA_TOKEN_PLAN_INTL_BACKEND_TYPE
        )
        env_api_key = os.environ.get(ALIBABA_TOKEN_PLAN_INTL_API_KEY_ENV, "").strip()
        options = dict(request.options)
        options["api_key"] = env_api_key
        normalized = replace(request, effective_model=raw_model, options=options)
        return await super()._chat_completions_canonical(normalized)


backend_registry.register_backend(
    ALIBABA_TOKEN_PLAN_INTL_BACKEND_TYPE, AlibabaTokenPlanIntlBackend
)
