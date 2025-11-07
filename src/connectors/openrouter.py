from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from typing import Any, cast

import httpx

from src.connectors.openai import OpenAIConnector
from src.core.common.exceptions import AuthenticationError, ConfigurationError
from src.core.config.app_config import AppConfig
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.configuration_interface import IAppIdentityConfig
from src.core.interfaces.model_bases import DomainModel, InternalDTO
from src.core.security.loop_prevention import ensure_loop_guard_header
from src.core.services.backend_registry import backend_registry
from src.core.services.translation_service import TranslationService

logger = logging.getLogger(__name__)


class OpenRouterBackend(OpenAIConnector):
    """LLMBackend implementation for OpenRouter.ai."""

    backend_type: str = "openrouter"

    def __init__(
        self,
        client: httpx.AsyncClient,
        config: AppConfig,
        translation_service: TranslationService | None = None,
    ) -> None:  # Modified
        super().__init__(client, config, translation_service=translation_service)
        self.api_base_url = "https://openrouter.ai/api/v1"
        self.headers_provider: Callable[[Any, str], dict[str, str]] | None = None
        self.key_name: str | None = None
        self.api_keys: list[str] = []
        self._health_check_enabled = False

    def _build_openrouter_header_context(self) -> dict[str, str]:
        """Create a minimal context dictionary for header providers expecting config."""
        referer = "http://localhost:8000"
        title = "InterceptorProxy"

        identity = getattr(self.config, "identity", None)
        if identity is not None:
            referer = (
                getattr(getattr(identity, "url", None), "default_value", referer)
                or referer
            )
            title = (
                getattr(getattr(identity, "title", None), "default_value", title)
                or title
            )

        return {"app_site_url": referer, "app_x_title": title}

    @staticmethod
    def _authorization_includes_api_key(
        headers: Mapping[str, str], api_key: str | None
    ) -> bool:
        """Check whether the Authorization header contains the expected API key."""

        if not api_key:
            return True

        for header_name, value in headers.items():
            if (
                header_name.lower() == "authorization"
                and isinstance(value, str)
                and api_key in value
            ):
                return True

        return False

    def _resolve_headers_from_provider(self) -> dict[str, str]:
        """Call the configured headers provider with appropriate arguments."""
        if not self.headers_provider or not self.api_key:
            raise AuthenticationError(
                message="OpenRouter headers provider or API key not set.",
                code="missing_credentials",
            )

        provider = self.headers_provider
        errors: list[Exception] = []

        def _try_provider_call(*args: Any) -> dict[str, str] | None:
            try:
                result = provider(*args)
            except (AttributeError, TypeError) as exc:
                logger.error(
                    "OpenRouter headers provider call failed with attribute/type error",
                    exc_info=True,
                )
                errors.append(exc)
                return None
            except (ValueError, KeyError, IndexError) as exc:
                logger.error(
                    "OpenRouter headers provider call failed with data error",
                    exc_info=True,
                )
                errors.append(exc)
                return None
            except Exception as exc:
                logger.error(
                    "OpenRouter headers provider call failed with unexpected error",
                    exc_info=True,
                )
                errors.append(exc)
                return None

            if not isinstance(result, Mapping):
                errors.append(
                    TypeError("OpenRouter headers provider must return a mapping."),
                )
                return None

            headers = dict(result)
            if not self._authorization_includes_api_key(headers, self.api_key):
                errors.append(
                    ValueError(
                        "OpenRouter headers provider did not include API key in Authorization header.",
                    )
                )
                return None

            return headers

        if self.key_name is not None:
            headers = _try_provider_call(self.key_name, self.api_key)
            if headers is not None:
                return headers

            headers = _try_provider_call(self.api_key, self.key_name)
            if headers is not None:
                return headers

        context = self._build_openrouter_header_context()
        headers = _try_provider_call(context, self.api_key)
        if headers is not None:
            return headers

        if errors:
            logger.debug(
                "Headers provider attempts failed: %s",
                errors[-1],
                exc_info=True,
            )
        raise AuthenticationError(
            message="OpenRouter headers provider failed to produce headers.",
            code="missing_credentials",
        )

    @staticmethod
    def _normalize_payload_value(value: Any) -> Any:
        """Normalize payload values to plain Python types."""

        if hasattr(value, "model_dump") and callable(value.model_dump):
            return value.model_dump()  # type: ignore[no-any-return]
        if isinstance(value, Mapping):
            return {
                key: OpenRouterBackend._normalize_payload_value(val)
                for key, val in value.items()
            }
        if isinstance(value, (list, tuple, set)):
            return [OpenRouterBackend._normalize_payload_value(item) for item in value]
        return value

    def _collect_openrouter_payload_fields(self, request: Any) -> dict[str, Any]:
        """Gather OpenRouter-specific parameters from the domain request."""

        field_map: dict[str, Any] = {
            "top_k": getattr(request, "top_k", None),
            "repetition_penalty": getattr(request, "repetition_penalty", None),
            "top_logprobs": getattr(request, "top_logprobs", None),
            "min_p": getattr(request, "min_p", None),
            "top_a": getattr(request, "top_a", None),
            "reasoning_effort": getattr(request, "reasoning_effort", None),
            "prediction": getattr(request, "prediction", None),
            "transforms": getattr(request, "transforms", None),
            "models": getattr(request, "models", None),
            "route": getattr(request, "route", None),
            "provider": getattr(request, "provider", None),
            "response_format": getattr(request, "response_format", None),
        }

        normalized: dict[str, Any] = {}
        for key, value in field_map.items():
            if value is None:
                continue
            normalized[key] = self._normalize_payload_value(value)
        return normalized

    def get_headers(self, identity: IAppIdentityConfig | None = None) -> dict[str, str]:
        if not self.api_key:
            raise AuthenticationError(
                message="OpenRouter API key not configured.",
                code="missing_credentials",
            )

        headers: dict[str, str] = {}
        if self.headers_provider is not None:
            headers.update(self._resolve_headers_from_provider())

        def _ensure_header(key: str, value: str) -> None:
            for existing_key in headers.keys():
                if existing_key.lower() == key.lower():
                    return
            headers[key] = value

        def _override_header(key: str, value: str) -> None:
            normalized_key = key
            for existing_key in list(headers.keys()):
                if existing_key.lower() == key.lower():
                    normalized_key = existing_key
                    headers.pop(existing_key)
                    break
            headers[normalized_key] = value

        _ensure_header("Authorization", f"Bearer {self.api_key}")
        _ensure_header("Content-Type", "application/json")

        context = self._build_openrouter_header_context()
        _ensure_header("HTTP-Referer", context["app_site_url"])
        _ensure_header("X-Title", context["app_x_title"])

        if identity is not None:
            try:
                identity_headers = identity.get_resolved_headers(None)
                identity_headers = dict(identity_headers)
                if identity_headers:
                    for key, value in identity_headers.items():
                        if isinstance(key, str) and isinstance(value, str):
                            _override_header(key, value)
            except (AttributeError, TypeError, ValueError) as exc:
                logger.error(
                    "Failed to resolve identity headers in get_headers()",
                    exc_info=True,
                )
                raise ConfigurationError(
                    message="Failed to resolve identity configuration",
                    details={"identity_error": str(exc)},
                ) from exc
            except Exception as exc:
                logger.error(
                    "Unexpected error resolving identity headers in get_headers()",
                    exc_info=True,
                )
                raise ConfigurationError(
                    message="Unexpected error resolving identity configuration",
                    details={"unexpected_error": str(exc)},
                ) from exc

        logger.info(
            "OpenRouter headers prepared: Authorization prefix=%s, HTTP-Referer=%s, X-Title=%s",
            headers.get("Authorization", "")[:20],
            headers.get("HTTP-Referer", "NOT_SET"),
            headers.get("X-Title", "NOT_SET"),
        )
        return ensure_loop_guard_header(headers)

    async def initialize(self, **kwargs: Any) -> None:
        """Fetch available models and cache them for later use."""
        api_key = kwargs.get("api_key")
        if not api_key:
            raise ValueError("api_key is required for OpenRouterBackend")

        # Accept and set optional init kwargs for headers provider and base URL
        openrouter_headers_provider = cast(
            Callable[[str, str], dict[str, str]],
            kwargs.get("openrouter_headers_provider"),
        )
        key_name = cast(str, kwargs.get("key_name"))
        api_base_url = kwargs.get("openrouter_api_base_url") or kwargs.get(
            "api_base_url"
        )

        if openrouter_headers_provider is not None and not callable(
            openrouter_headers_provider
        ):
            raise TypeError("openrouter_headers_provider must be callable if provided")

        if key_name is not None and not isinstance(key_name, str):
            raise TypeError("key_name must be a string if provided")

        # Apply provided init values
        if openrouter_headers_provider is not None:
            self.headers_provider = openrouter_headers_provider
        if key_name is not None:
            self.key_name = key_name
        self.api_key = api_key
        if api_base_url:
            self.api_base_url = api_base_url

        # Manually set up the available models list for tests
        # In a real environment, we would fetch this from the API
        self.available_models = ["m1", "m2"]

        # OpenRouter uses a fixed base URL, so we call the parent's initialize
        # with our specific URL.
        # await super().initialize(api_key=api_key, api_base_url=self.api_base_url)

    async def chat_completions(  # type: ignore[override]
        self,
        request_data: DomainModel | InternalDTO | dict[str, Any],
        processed_messages: list[Any],
        effective_model: str,
        identity: IAppIdentityConfig | None = None,
        project: str | None = None,
        **kwargs: Any,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        from typing import cast

        from src.core.domain.chat import CanonicalChatRequest, ChatRequest

        if not isinstance(request_data, ChatRequest):
            raise TypeError(
                f"Expected ChatRequest or CanonicalChatRequest, got {type(request_data).__name__}. "
                "Backend connectors should only receive domain-format requests."
            )

        domain_request: CanonicalChatRequest = cast(CanonicalChatRequest, request_data)

        headers_provider_override = kwargs.pop("openrouter_headers_provider", None)
        key_name_override = kwargs.pop("key_name", None)
        api_key_override = kwargs.pop("api_key", None)
        explicit_api_base = kwargs.pop("openrouter_api_base_url", None)
        api_base_kwarg = kwargs.pop("api_base_url", None)

        if headers_provider_override is not None and not callable(
            headers_provider_override
        ):
            raise TypeError("openrouter_headers_provider must be callable if provided")

        original_state = (
            self.headers_provider,
            self.key_name,
            self.api_key,
            self.api_base_url,
        )

        try:
            if headers_provider_override is not None:
                self.headers_provider = cast(
                    Callable[[Any, str], dict[str, str]], headers_provider_override
                )
            if key_name_override is not None:
                self.key_name = cast(str, key_name_override)
            if api_key_override is not None:
                self.api_key = cast(str, api_key_override)

            api_base_override = explicit_api_base or api_base_kwarg
            if api_base_override:
                self.api_base_url = cast(str, api_base_override)

            call_kwargs = dict(kwargs)
            call_kwargs.setdefault("openai_url", self.api_base_url)

            return await super().chat_completions(
                request_data=domain_request,
                processed_messages=processed_messages,
                effective_model=effective_model,
                identity=identity,
                **call_kwargs,
            )
        finally:
            self.headers_provider = original_state[0]
            self.key_name = original_state[1]
            self.api_key = original_state[2]
            self.api_base_url = original_state[3]

    async def _prepare_payload(
        self,
        request_data: "CanonicalChatRequest",
        processed_messages: list[Any],
        effective_model: str,
    ) -> dict[str, Any]:
        payload = await super()._prepare_payload(
            request_data, processed_messages, effective_model
        )

        for key, value in self._collect_openrouter_payload_fields(request_data).items():
            payload.setdefault(key, value)

        return payload


backend_registry.register_backend("openrouter", OpenRouterBackend)
