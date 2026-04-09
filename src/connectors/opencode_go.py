from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any

import httpx

from src.connectors.anthropic import AnthropicBackend
from src.connectors.base import add_vendor_prefix, strip_vendor_prefix
from src.connectors.contracts import ConnectorChatCompletionsRequest
from src.connectors.openai import OpenAIConnector
from src.core.common.exceptions import ConfigurationError, RoutingError
from src.core.config.app_config import AppConfig
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.services.backend_registry import backend_registry
from src.core.services.translation_service import TranslationService

logger = logging.getLogger(__name__)

_OPENCODE_GO_DEFAULT_BASE_URL = "https://opencode.ai/zen/go/v1"
_OPENCODE_GO_VENDOR_PREFIX = "opencode-go"
_OPENCODE_GO_OPENAI_MODELS: tuple[str, ...] = (
    "glm-5",
    "glm-5.1",
    "kimi-k2.5",
    "mimo-v2-pro",
    "mimo-v2-omni",
)
_OPENCODE_GO_ANTHROPIC_MODELS: tuple[str, ...] = (
    "minimax-m2.5",
    "minimax-m2.7",
)
_OPENCODE_GO_SUPPORTED_PROTOCOLS = {"openai", "anthropic"}


def _normalize_model_name(model: str) -> str:
    """Normalize a public or backend-prefixed model identifier to its raw model id."""

    candidate = model.strip()
    if not candidate:
        return candidate
    if candidate.startswith(f"{_OPENCODE_GO_VENDOR_PREFIX}/"):
        return strip_vendor_prefix(candidate, _OPENCODE_GO_VENDOR_PREFIX)
    if candidate.startswith(f"{_OPENCODE_GO_VENDOR_PREFIX}:"):
        return candidate.split(":", 1)[1]
    return candidate


def _validate_protocol_name(protocol: Any) -> str | None:
    if not isinstance(protocol, str):
        return None
    normalized = protocol.strip().lower()
    if normalized in _OPENCODE_GO_SUPPORTED_PROTOCOLS:
        return normalized
    return None


class _OpencodeGoAnthropicDelegate(AnthropicBackend):
    """Private Anthropic-compatible delegate for opencode-go."""

    backend_type: str = _OPENCODE_GO_VENDOR_PREFIX

    async def initialize(self, **kwargs: Any) -> None:
        kwargs = dict(kwargs)
        kwargs.setdefault("key_name", _OPENCODE_GO_VENDOR_PREFIX)
        kwargs.setdefault("anthropic_api_base_url", _OPENCODE_GO_DEFAULT_BASE_URL)
        await super().initialize(**kwargs)

    def _prepare_anthropic_payload(
        self,
        request_data: Any,
        processed_messages: list[Any],
        effective_model: str,
        project: str | None,
        context: Any | None = None,
    ) -> dict[str, Any]:
        # The opencode-go backend requires the "opencode-go/" vendor prefix
        # on every outbound model name, including Anthropic-protocol requests.
        # Re-add the prefix if the base class stripped it away.
        prefixed = add_vendor_prefix(effective_model, _OPENCODE_GO_VENDOR_PREFIX)
        return super()._prepare_anthropic_payload(
            request_data, processed_messages, prefixed, project, context
        )


class OpencodeGoBackend(OpenAIConnector):
    """Hybrid OpenCode Go backend with OpenAI and Anthropic protocol routing."""

    backend_type: str = _OPENCODE_GO_VENDOR_PREFIX
    VENDOR_PREFIX: str | None = _OPENCODE_GO_VENDOR_PREFIX

    def __init__(
        self,
        client: httpx.AsyncClient,
        config: AppConfig,
        translation_service: TranslationService | None = None,
    ) -> None:
        super().__init__(client, config, translation_service=translation_service)
        self.api_key: str | None = None
        self.api_base_url = _OPENCODE_GO_DEFAULT_BASE_URL
        self.available_models = list(self._default_raw_models())
        self._model_protocol_overrides: dict[str, str] = {}
        self._anthropic_delegate = _OpencodeGoAnthropicDelegate(
            client=client,
            config=config,
            translation_service=translation_service or self.translation_service,
        )

    @staticmethod
    def _default_raw_models() -> tuple[str, ...]:
        return _OPENCODE_GO_OPENAI_MODELS + _OPENCODE_GO_ANTHROPIC_MODELS

    @classmethod
    def _build_advertised_raw_models(
        cls, overrides: dict[str, str] | None = None
    ) -> list[str]:
        ordered_models: list[str] = list(cls._default_raw_models())
        override_keys: list[str] = []
        if overrides:
            override_keys = [
                _normalize_model_name(model_name)
                for model_name in overrides
                if _normalize_model_name(model_name)
            ]

        for model_name in override_keys:
            if model_name not in ordered_models:
                ordered_models.append(model_name)
        return ordered_models

    @staticmethod
    def _build_protocol_override_map(
        overrides: Any,
    ) -> dict[str, str]:
        if overrides is None:
            return {}
        if not isinstance(overrides, dict):
            raise ConfigurationError(
                message="model_protocol_overrides must be a mapping of model -> protocol",
                code="invalid_config",
            )

        normalized: dict[str, str] = {}
        for raw_model, raw_protocol in overrides.items():
            model_name = _normalize_model_name(str(raw_model))
            if not model_name:
                continue
            protocol = _validate_protocol_name(raw_protocol)
            if protocol is None:
                raise ConfigurationError(
                    message=(
                        "model_protocol_overrides values must be 'openai' or 'anthropic'"
                    ),
                    details={
                        "model": model_name,
                        "protocol": raw_protocol,
                    },
                    code="invalid_config",
                )
            normalized[model_name] = protocol
        return normalized

    @classmethod
    def _resolve_protocol_for_model(
        cls,
        model_name: str,
        protocol_overrides: dict[str, str],
    ) -> str | None:
        normalized = _normalize_model_name(model_name)
        if not normalized:
            return None

        override = protocol_overrides.get(normalized)
        if override:
            return override

        if normalized in _OPENCODE_GO_OPENAI_MODELS:
            return "openai"
        if normalized in _OPENCODE_GO_ANTHROPIC_MODELS:
            return "anthropic"
        return None

    @staticmethod
    def _enforce_backend_vendor_prefix(raw_model: str) -> str:
        """Ensure the model name carries the opencode-go vendor prefix.

        The opencode-go backend requires every outbound model identifier to
        include ``opencode-go/`` as the vendor prefix so that the remote
        service can correctly distinguish its models.  This helper adds the
        prefix when the caller omitted it.
        """
        if raw_model.startswith(f"{_OPENCODE_GO_VENDOR_PREFIX}/"):
            return raw_model
        return f"{_OPENCODE_GO_VENDOR_PREFIX}/{raw_model}"

    def _normalize_request(
        self, request: ConnectorChatCompletionsRequest, raw_model: str
    ) -> ConnectorChatCompletionsRequest:
        prefixed = self._enforce_backend_vendor_prefix(raw_model)
        normalized_request = request.request.model_copy(update={"model": prefixed})
        return replace(request, request=normalized_request, effective_model=prefixed)

    def _build_unknown_model_error(self, model_name: str) -> RoutingError:
        supported_models = [
            add_vendor_prefix(model, self.backend_type)
            for model in self._build_advertised_raw_models(
                self._model_protocol_overrides
            )
        ]
        return RoutingError(
            message=f"Unsupported opencode-go model '{model_name}'.",
            details={
                "code": "unknown_model",
                "category": "validation",
                "retryable": False,
                "backend_type": self.backend_type,
                "model": model_name,
                "supported_models": supported_models,
            },
        )

    async def initialize(self, **kwargs: Any) -> None:
        self.api_key = kwargs.get("api_key")
        if not self.api_key:
            raise ConfigurationError(
                message="api_key is required for OpencodeGoBackend",
                code="missing_api_key",
            )

        shared_api_base_url = (
            kwargs.get("api_base_url") or _OPENCODE_GO_DEFAULT_BASE_URL
        )
        openai_api_base_url = kwargs.get("openai_api_base_url") or shared_api_base_url
        anthropic_api_base_url = (
            kwargs.get("anthropic_api_base_url") or shared_api_base_url
        )

        self.api_base_url = str(openai_api_base_url)
        self._model_protocol_overrides = self._build_protocol_override_map(
            kwargs.get("model_protocol_overrides")
        )
        self.available_models = self._build_advertised_raw_models(
            self._model_protocol_overrides
        )

        self._anthropic_delegate.api_key = self.api_key
        await self._anthropic_delegate.initialize(
            api_key=self.api_key,
            key_name=kwargs.get("key_name", self.backend_type),
            anthropic_api_base_url=anthropic_api_base_url,
            auth_header_name=kwargs.get("auth_header_name", "x-api-key"),
        )

        if logger.isEnabledFor(logging.INFO):
            logger.info(
                "Initialized opencode-go backend with openai_base=%s anthropic_base=%s",
                self.api_base_url,
                anthropic_api_base_url,
            )

    def get_available_models(self) -> list[str]:
        return [
            add_vendor_prefix(model, self.backend_type)
            for model in self.available_models
        ]

    async def get_available_models_async(self) -> list[str]:
        return self.get_available_models()

    def get_provider_name(self) -> str:
        return self.backend_type

    async def chat_completions(  # type: ignore[override]
        self,
        request: ConnectorChatCompletionsRequest,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        if not isinstance(request, ConnectorChatCompletionsRequest):
            raise TypeError(
                "OpencodeGoBackend.chat_completions requires ConnectorChatCompletionsRequest."
            )

        raw_model = _normalize_model_name(request.effective_model)
        if not raw_model:
            raw_model = _normalize_model_name(request.request.model)

        protocol = self._resolve_protocol_for_model(
            raw_model, self._model_protocol_overrides
        )
        if protocol is None:
            raise self._build_unknown_model_error(raw_model)

        normalized_request = self._normalize_request(request, raw_model)
        if protocol == "openai":
            return await super().chat_completions(normalized_request)

        return await self._anthropic_delegate.chat_completions(normalized_request)


backend_registry.register_backend("opencode-go", OpencodeGoBackend)
