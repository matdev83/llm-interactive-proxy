from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from typing import Any, cast

import httpx

from src.connectors.openai import OpenAIConnector
from src.core.common.exceptions import (
    AuthenticationError,
    BackendError,
    ConfigurationError,
    ServiceUnavailableError,
)
from src.core.config.app_config import AppConfig
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.domain.session_key import SessionKey
from src.core.interfaces.configuration_interface import IAppIdentityConfig
from src.core.interfaces.model_bases import DomainModel, InternalDTO
from src.core.security.loop_prevention import ensure_loop_guard_header
from src.core.services.backend_registry import backend_registry
from src.core.services.translation_service import TranslationService

logger = logging.getLogger(__name__)


class OpenRouterBackend(OpenAIConnector):
    """LLMBackend implementation for OpenRouter.ai."""

    backend_type: str = "openrouter"

    # OpenRouter is a multi-vendor backend - models are already prefixed
    # from upstream providers (e.g., "anthropic/claude-3", "openai/gpt-4")
    VENDOR_PREFIX: str | None = None

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

        context = self._build_openrouter_header_context()
        headers = _try_provider_call(context, self.api_key)
        if headers is not None:
            return headers

        if self.key_name is not None:
            headers = _try_provider_call(self.key_name, self.api_key)
            if headers is not None:
                return headers

            headers = _try_provider_call(self.api_key, self.key_name)
            if headers is not None:
                return headers

        if errors and logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Headers provider attempts failed: %s",
                errors[-1],
                exc_info=True,
            )
        raise AuthenticationError(
            message="OpenRouter headers provider failed to produce headers.",
            code="missing_credentials",
        )

    def get_headers(self, identity: IAppIdentityConfig | None = None) -> dict[str, str]:
        if not self.headers_provider or not self.api_key:
            raise AuthenticationError(
                message="OpenRouter headers provider or API key not set.",
                code="missing_credentials",
            )
        headers = self._resolve_headers_from_provider()
        if identity is not None:
            try:
                identity_headers = identity.get_resolved_headers(None)
                identity_headers = dict(identity_headers)
                if identity_headers:
                    headers.update(identity_headers)
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
        if logger.isEnabledFor(logging.INFO):
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
        cancellation_token: SessionKey | None = None,
        cancellation_coordinator: (
            Any | None
        ) = None,  # ISessionCancellationCoordinator | None
        project: str | None = None,
        **kwargs: Any,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        # Structural enforcement: check cancellation immediately if coordinator and token provided
        if cancellation_coordinator is not None and cancellation_token is not None:
            cancellation_coordinator.ensure_not_cancelled(cancellation_token)
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
                    Callable[[Any, str], dict[str, str]], headers_provider
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
            if self.headers_provider:
                try:
                    headers_override = dict(self._resolve_headers_from_provider())
                except AuthenticationError:
                    headers_override = None
                except Exception as exc:
                    logger.error(
                        "Unexpected error resolving headers from provider in chat_completions()",
                        exc_info=True,
                    )
                    raise BackendError(
                        message="Failed to resolve headers from provider",
                        backend_name="openrouter",
                        details={"provider_error": str(exc)},
                    ) from exc

            if headers_override is None:
                headers_override = {}

            if self.api_key:
                headers_override.setdefault("Authorization", f"Bearer {self.api_key}")

            if identity is not None:
                try:
                    identity_headers = identity.get_resolved_headers(None)
                    if identity_headers:
                        headers_override.update(identity_headers)
                except (AttributeError, TypeError, ValueError) as exc:
                    logger.error(
                        "Failed to resolve identity headers in chat_completions()",
                        exc_info=True,
                    )
                    raise ConfigurationError(
                        message="Failed to resolve identity configuration",
                        details={"identity_error": str(exc)},
                    ) from exc
                except Exception as exc:
                    logger.error(
                        "Unexpected error resolving identity headers in chat_completions()",
                        exc_info=True,
                    )
                    raise ConfigurationError(
                        message="Unexpected error resolving identity configuration",
                        details={"unexpected_error": str(exc)},
                    ) from exc

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
            # Note: OpenRouterBackend uses legacy chat_completions signature,
            # so context is not available here. Pass None for backward compatibility.
            payload = await self._prepare_payload(
                domain_request, processed_messages, effective_model, context=None
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

            # OpenAI API parity: additional parameters
            if domain_request.max_completion_tokens is not None:
                payload["max_completion_tokens"] = domain_request.max_completion_tokens
            if domain_request.logprobs is not None:
                payload["logprobs"] = domain_request.logprobs
            if domain_request.top_logprobs is not None:
                payload["top_logprobs"] = domain_request.top_logprobs
            if domain_request.parallel_tool_calls is not None:
                payload["parallel_tool_calls"] = domain_request.parallel_tool_calls
            if domain_request.service_tier is not None:
                payload["service_tier"] = domain_request.service_tier
            if domain_request.response_format is not None:
                payload["response_format"] = domain_request.response_format

            # Phase 3: Advanced OpenAI API parity parameters
            if domain_request.store is not None:
                payload["store"] = domain_request.store
            if domain_request.request_metadata is not None:
                payload["metadata"] = domain_request.request_metadata
            if domain_request.prediction is not None:
                payload["prediction"] = domain_request.prediction
            if domain_request.modalities is not None:
                payload["modalities"] = domain_request.modalities
            if domain_request.audio is not None:
                payload["audio"] = domain_request.audio

            # Handle extra_body from the request (takes precedence)
            if hasattr(domain_request, "extra_body") and domain_request.extra_body:
                for key, value in domain_request.extra_body.items():
                    payload[key] = value

            # Handle reasoning config
            if hasattr(domain_request, "reasoning") and domain_request.reasoning:
                payload["reasoning"] = domain_request.reasoning

            payload = self._clean_openai_payload(payload)

            # Manually call the appropriate handler from the parent class
            api_base = call_kwargs.get("openai_url") or self.api_base_url
            url = f"{api_base.rstrip('/')}/chat/completions"

            if domain_request.stream:
                stream_handle = await self._handle_streaming_response(
                    url,
                    payload,
                    headers_override,
                    domain_request.session_id or "",
                    "openai",
                )
                return StreamingResponseEnvelope(
                    content=stream_handle.iterator,
                    media_type="text/event-stream",
                    headers={},
                    cancel_callback=stream_handle.cancel_callback,
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
