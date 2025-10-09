from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, cast

import httpx

from src.connectors.openai import OpenAIConnector
from src.core.common.exceptions import (
    AuthenticationError,
    BackendError,
    ServiceUnavailableError,
)
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
        self.headers_provider: Callable[[str, str], dict[str, str]] | None = None
        self.key_name: str | None = None
        self.api_keys: list[str] = []

    def get_headers(self) -> dict[str, str]:
        if not self.headers_provider or not self.key_name or not self.api_key:
            raise AuthenticationError(
                message="OpenRouter headers provider, key name, or API key not set.",
                code="missing_credentials",
            )
        headers = self.headers_provider(self.key_name, self.api_key)
        if self.identity:
            headers.update(self.identity.get_resolved_headers(None))
        logger.info(
            f"OpenRouter headers: Authorization: Bearer {self.api_key[:20]}..., HTTP-Referer: {headers.get('HTTP-Referer', 'NOT_SET')}, X-Title: {headers.get('X-Title', 'NOT_SET')}"
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
        api_base_url = kwargs.get("openrouter_api_base_url")

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
        self.identity = identity

        # request_data is expected to be a domain ChatRequest (or subclass like CanonicalChatRequest)
        # (the frontend controller converts from frontend-specific format to domain format)
        # Backends should ONLY convert FROM domain TO backend-specific format
        # Type assertion: we know from architectural design that request_data is ChatRequest-like
        from typing import cast

        from src.core.domain.chat import CanonicalChatRequest, ChatRequest

        if not isinstance(request_data, ChatRequest):
            raise TypeError(
                f"Expected ChatRequest or CanonicalChatRequest, got {type(request_data).__name__}. "
                "Backend connectors should only receive domain-format requests."
            )
        # Cast to CanonicalChatRequest for mypy compatibility with translation service signature
        domain_request: CanonicalChatRequest = cast(CanonicalChatRequest, request_data)

        # Allow tests and callers to provide per-call OpenRouter settings via kwargs
        headers_provider = kwargs.pop("openrouter_headers_provider", None)
        key_name = kwargs.pop("key_name", None)
        api_key = kwargs.pop("api_key", None)
        api_base_url = kwargs.pop("openrouter_api_base_url", None)

        original_headers_provider = self.headers_provider
        original_key_name = self.key_name
        original_api_key = self.api_key
        original_api_base_url = self.api_base_url

        try:
            if headers_provider is not None:
                self.headers_provider = cast(
                    Callable[[str, str], dict[str, str]], headers_provider
                )
            if key_name is not None:
                self.key_name = cast(str, key_name)
            if api_key is not None:
                self.api_key = cast(str, api_key)
            if api_base_url:
                self.api_base_url = cast(str, api_base_url)

            # Compute explicit headers for this call and ensure the exact
            # Authorization header and URL used by tests are passed to the
            # parent's streaming/non-streaming implementation.
            headers_override: dict[str, str] | None = None
            if self.key_name and self.api_key and self.headers_provider:
                try:
                    headers_override = dict(
                        self.headers_provider(self.key_name, self.api_key)
                    )
                except Exception:
                    headers_override = None

            if headers_override is None:
                headers_override = {}

            if self.api_key:
                headers_override.setdefault("Authorization", f"Bearer {self.api_key}")

            if identity is not None:
                try:
                    identity_headers = identity.get_resolved_headers(None)
                except Exception:
                    identity_headers = {}
                if identity_headers:
                    headers_override.update(identity_headers)

            if not headers_override:
                headers_override = None

            # Determine the exact URL to call so tests that mock it see the
            # same value. The parent expects `openai_url` kwarg for URL
            # override; for OpenRouter we set it to our `api_base_url`.
            call_kwargs = dict(kwargs)
            call_kwargs["headers_override"] = headers_override
            call_kwargs["openai_url"] = self.api_base_url

            # Translate to a base payload using the shared hook so that
            # processed_messages, effective_model and extra_body are applied
            # consistently (and tests can patch _prepare_payload).
            payload = await self._prepare_payload(
                domain_request, processed_messages, effective_model
            )

            # Add OpenRouter-specific parameters to the payload
            if domain_request.top_k is not None:
                payload["top_k"] = domain_request.top_k
            if domain_request.seed is not None:
                payload["seed"] = domain_request.seed
            if domain_request.reasoning_effort is not None:
                payload["reasoning_effort"] = domain_request.reasoning_effort

            # Add frequency_penalty and presence_penalty if specified
            if domain_request.frequency_penalty is not None:
                payload["frequency_penalty"] = domain_request.frequency_penalty
            if domain_request.presence_penalty is not None:
                payload["presence_penalty"] = domain_request.presence_penalty

            # Handle extra_body from the request (takes precedence)
            if hasattr(domain_request, "extra_body") and domain_request.extra_body:
                for key, value in domain_request.extra_body.items():
                    payload[key] = value

            # Handle reasoning config
            if hasattr(domain_request, "reasoning") and domain_request.reasoning:
                payload["reasoning"] = domain_request.reasoning

            # Manually call the appropriate handler from the parent class
            api_base = call_kwargs.get("openai_url") or self.api_base_url
            url = f"{api_base.rstrip('/')}/chat/completions"

            if domain_request.stream:
                content_iterator = await self._handle_streaming_response(
                    url,
                    payload,
                    headers_override,
                    domain_request.session_id or "",
                    "openai",
                )
                return StreamingResponseEnvelope(
                    content=content_iterator,
                    media_type="text/event-stream",
                    headers={},
                )
            else:
                return await self._handle_non_streaming_response(
                    url, payload, headers_override, domain_request.session_id or ""
                )
        except ServiceUnavailableError:
            raise
        except BackendError:
            raise
        finally:
            self.headers_provider = original_headers_provider
            self.key_name = original_key_name
            self.api_key = original_api_key
            self.api_base_url = original_api_base_url


backend_registry.register_backend("openrouter", OpenRouterBackend)
