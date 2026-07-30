"""Alibaba Cloud international Token Plan connector using Anthropic Messages."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import httpx

from src.connectors.anthropic import AnthropicBackend
from src.connectors.base import add_vendor_prefix, strip_vendor_prefix
from src.connectors.contracts import ConnectorChatCompletionsRequest
from src.core.common.env_utils import get_env_value_with_windows_persistent_fallback
from src.core.common.exceptions import ConfigurationError, InvalidRequestError
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


def _normalize_tool(tool: Any) -> dict[str, Any] | None:
    if hasattr(tool, "model_dump"):
        tool = tool.model_dump(exclude_none=True)
    if not isinstance(tool, dict):
        return None

    function = tool.get("function")
    source = function if isinstance(function, dict) else tool
    name = source.get("name")
    if not isinstance(name, str) or not name.strip():
        return None

    schema_key = "parameters" if isinstance(function, dict) else "input_schema"
    schema = source.get(schema_key)
    if not isinstance(schema, dict):
        schema = {"type": "object", "properties": {}}
    normalized: dict[str, Any] = {
        "name": name.strip(),
        "input_schema": schema,
    }
    description = source.get("description")
    if isinstance(description, str) and description.strip():
        normalized["description"] = description.strip()
    return normalized


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
        api_key, _ = get_env_value_with_windows_persistent_fallback(
            ALIBABA_TOKEN_PLAN_INTL_API_KEY_ENV
        )
        api_key = (api_key or "").strip()
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
            has_tool_calls = bool(
                message.get("tool_calls")
                if isinstance(message, dict)
                else getattr(message, "tool_calls", None)
            )
            has_tool_call_id = bool(
                message.get("tool_call_id")
                if isinstance(message, dict)
                else getattr(message, "tool_call_id", None)
            )
            if role in {"user", "system"} or (
                role == "assistant" and has_tool_calls
            ) or (role == "tool" and has_tool_call_id):
                normalized_messages.append(message)
            elif isinstance(message, dict):
                normalized_messages.append({**message, "role": "user"})
            elif hasattr(message, "model_copy"):
                normalized_messages.append(message.model_copy(update={"role": "user"}))
            else:
                normalized_messages.append(message)

        payload = super()._prepare_anthropic_payload(
            request_data,
            normalized_messages,
            effective_model,
            project,
            context,
        )
        tool_choice = request_data.tool_choice
        normalized_tool_choice = (
            tool_choice.strip().lower() if isinstance(tool_choice, str) else tool_choice
        )
        if normalized_tool_choice not in (None, "auto", "none"):
            # Token Plan accepts tools but currently rejects tool_choice.
            raise InvalidRequestError(
                message=(
                    "Alibaba Token Plan supports only tool_choice='auto' or "
                    "tool_choice='none'"
                ),
                code="unsupported_tool_choice",
            )

        if request_data.tools is not None:
            normalized_tools: list[dict[str, Any]] = []
            for index, tool in enumerate(request_data.tools):
                normalized_tool = _normalize_tool(tool)
                if normalized_tool is None:
                    raise InvalidRequestError(
                        message=f"Invalid tool definition at index {index}",
                        code="invalid_tool_definition",
                    )
                normalized_tools.append(normalized_tool)

            if normalized_tool_choice == "none":
                payload.pop("tools", None)
            else:
                payload["tools"] = normalized_tools
        payload.pop("tool_choice", None)

        reasoning_effort = getattr(request_data, "reasoning_effort", None)
        if isinstance(reasoning_effort, str) and reasoning_effort.strip():
            payload.pop("reasoning_effort", None)
            payload["thinking"] = {
                "type": (
                    "disabled"
                    if reasoning_effort.strip().lower() == "none"
                    else "enabled"
                )
            }
        return payload

    async def _chat_completions_canonical(
        self, request: ConnectorChatCompletionsRequest
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        raw_model = strip_vendor_prefix(
            request.effective_model, ALIBABA_TOKEN_PLAN_INTL_BACKEND_TYPE
        )
        # Alibaba's catalog uses bare model IDs, while some clients qualify
        # Model Studio models with the provider namespace.
        raw_model = strip_vendor_prefix(raw_model, "alibaba")
        extra_body = dict(request.request.extra_body or {})
        if "model" in extra_body:
            extra_body["model"] = raw_model
        domain_request = request.request.model_copy(
            update={"model": raw_model, "extra_body": extra_body}
        )
        env_api_key, _ = get_env_value_with_windows_persistent_fallback(
            ALIBABA_TOKEN_PLAN_INTL_API_KEY_ENV
        )
        env_api_key = (env_api_key or "").strip()
        options = dict(request.options)
        options["api_key"] = env_api_key
        normalized = replace(
            request,
            request=domain_request,
            effective_model=raw_model,
            options=options,
        )
        return await super()._chat_completions_canonical(normalized)


backend_registry.register_backend(
    ALIBABA_TOKEN_PLAN_INTL_BACKEND_TYPE, AlibabaTokenPlanIntlBackend
)
