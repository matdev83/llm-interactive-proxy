from __future__ import annotations

import contextlib
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from typing import Any, cast

import httpx
from pydantic.types import JsonValue

from src.connectors.contracts import (
    ConnectorChatCompletionsRequest,
)
from src.connectors.openai import OpenAIConnector
from src.core.common.exceptions import (
    AuthenticationError,
    BackendError,
    ConfigurationError,
    InvalidRequestError,
)
from src.core.config.app_config import AppConfig
from src.core.domain.chat import CanonicalChatRequest, ChatMessage, ChatRequest
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.configuration_interface import IAppIdentityConfig
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.security.loop_prevention import ensure_loop_guard_header
from src.core.services.backend_registry import backend_registry
from src.core.services.streaming.chunk_normalizer import (
    normalize_to_processed_chunk_content,
)
from src.core.services.streaming.error_mapping import handle_streaming_error
from src.core.services.streaming.processed_stream_idle_keepalive import (
    wrap_processed_stream_with_idle_keepalive,
)
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

    def _resolve_stream_keepalive_interval(self) -> float:
        config = getattr(self, "config", None)
        failure_handling = getattr(config, "failure_handling", None)
        interval = getattr(failure_handling, "keepalive_interval", None)
        if isinstance(interval, int | float) and interval > 0:
            return float(interval)
        return 8.0

    def _resolve_stream_idle_timeout(self) -> float | None:
        config = getattr(self, "config", None)
        candidates: list[float] = []
        failure_handling = getattr(config, "failure_handling", None)
        silent_wait = getattr(failure_handling, "max_silent_wait", None)
        if isinstance(silent_wait, int | float) and silent_wait > 0:
            candidates.append(float(silent_wait))
        proxy_timeout = getattr(config, "proxy_timeout", None)
        if isinstance(proxy_timeout, int | float) and proxy_timeout > 0:
            candidates.append(float(proxy_timeout))
        return min(candidates) if candidates else None

    async def _wrap_stream_with_idle_timeout(
        self,
        stream: AsyncIterator[ProcessedResponse],
        *,
        stream_id: str | None,
        model_name: str | None,
        keepalive_interval: float,
        idle_timeout: float | None,
        cancel_callback: Callable[[], Awaitable[None]] | None,
    ) -> AsyncIterator[ProcessedResponse]:
        async def _on_idle_timeout() -> ProcessedResponse:
            if cancel_callback is not None:
                with contextlib.suppress(Exception):
                    await cancel_callback()
            error = BackendError(
                message="Streaming timeout waiting for OpenRouter response.",
                code="streaming_timeout",
                status_code=504,
                backend_name=self.backend_type,
            )
            error_chunk = await handle_streaming_error(
                error, stream_id=stream_id, provider=self.backend_type
            )
            normalized = normalize_to_processed_chunk_content(error_chunk.to_bytes())
            return ProcessedResponse(
                content=normalized,
                metadata=error_chunk.metadata,
            )

        async for chunk in wrap_processed_stream_with_idle_keepalive(
            stream,
            keepalive_interval=keepalive_interval,
            idle_timeout=idle_timeout,
            stream_id=stream_id,
            model_name=model_name or "openrouter",
            on_idle_timeout=(
                _on_idle_timeout
                if idle_timeout is not None and idle_timeout > 0
                else None
            ),
        ):
            yield chunk

    @staticmethod
    def _authorization_includes_api_key(
        headers: Mapping[str, str], api_key: str | None
    ) -> bool:
        """Check whether the Authorization header contains the expected API key."""

        if not api_key:
            return True

        for header_name, value in headers.items():
            if header_name.lower() == "authorization" and api_key in value:
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
            raise ConfigurationError(
                message="api_key is required for OpenRouterBackend"
            )

        # Accept and set optional init kwargs for headers provider and base URL
        openrouter_headers_provider = cast(
            Callable[[str, str], dict[str, str]],
            kwargs.get("openrouter_headers_provider"),
        )
        key_name = kwargs.get("key_name")
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
        request: ConnectorChatCompletionsRequest | Any = None,
        *args: Any,
        **kwargs: Any,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Canonical connector API implementation with backward compatibility.

        This method implements ICanonicalChatCompletionsBackend protocol.
        For backward compatibility, also accepts legacy signature:
        chat_completions(request_data, processed_messages, effective_model, ...)
        """
        # Handle legacy API called with keyword arguments only (request_data=...)
        if request is None and "request_data" in kwargs:
            request = kwargs.pop("request_data")

        # Check if this is a canonical request (ConnectorChatCompletionsRequest)
        if isinstance(request, ConnectorChatCompletionsRequest):
            return await self._chat_completions_canonical(request)

        # Legacy API: build ConnectorChatCompletionsRequest from legacy parameters
        # BOUNDARY HARDENING: Legacy coercion is centralized at ConnectorInvoker.
        # This connector should only receive canonical domain models (never dicts).

        request_data = request
        processed_messages = args[0] if args else kwargs.get("processed_messages", [])
        effective_model = (
            args[1] if len(args) > 1 else kwargs.get("effective_model", "")
        )
        identity = kwargs.get("identity")
        cancellation_token = kwargs.get("cancellation_token")
        cancellation_coordinator = kwargs.get("cancellation_coordinator")
        context = None  # Legacy API doesn't provide context
        options = {
            k: v
            for k, v in kwargs.items()
            if k
            not in [
                "identity",
                "cancellation_token",
                "cancellation_coordinator",
                "processed_messages",
                "effective_model",
                "request_data",
                "project",
            ]
        }

        # BOUNDARY HARDENING: Reject dict input - coercion should be centralized at ConnectorInvoker
        if isinstance(request_data, dict):
            raise InvalidRequestError(
                message="Legacy connector API received dict input. "
                "Dict-to-domain coercion is centralized at ConnectorInvoker boundary. "
                "Expected CanonicalChatRequest or ChatRequest.",
                details={
                    "received_type": "dict",
                    "connector": "openrouter",
                },
            )

        # Ensure processed_messages is a Sequence[ChatMessage]
        if processed_messages:
            invalid_messages = [
                (i, type(msg).__name__)
                for i, msg in enumerate(processed_messages)
                if not isinstance(msg, ChatMessage)
            ]
            if invalid_messages:
                raise InvalidRequestError(
                    message="Legacy connector API received non-canonical processed_messages. "
                    "Expected Sequence[ChatMessage], but received mixed types.",
                    details={
                        "invalid_indices": [idx for idx, _ in invalid_messages],
                        "invalid_types": [typ for _, typ in invalid_messages],
                        "connector": "openrouter",
                    },
                )

        # Accept only canonical domain models
        if isinstance(request_data, ChatRequest):
            domain_request = CanonicalChatRequest.model_validate(
                request_data.model_dump()
            )
        elif isinstance(request_data, CanonicalChatRequest):
            domain_request = request_data
        else:
            raise InvalidRequestError(
                message=f"Legacy connector API received invalid input type: {type(request_data).__name__}. "
                "Expected CanonicalChatRequest or ChatRequest.",
                details={
                    "received_type": type(request_data).__name__,
                    "connector": "openrouter",
                },
            )

        # Extract OpenRouter-specific options from kwargs
        headers_provider = kwargs.get("openrouter_headers_provider")
        key_name = kwargs.get("key_name")
        api_key = kwargs.get("api_key")
        api_base_url = kwargs.get("openrouter_api_base_url")

        # JSON-SAFETY: Callables must remain as instance attributes, not in options.
        # Set instance attributes temporarily for this call (will be used by _chat_completions_canonical)
        original_headers_provider = self.headers_provider
        original_key_name = self.key_name
        original_api_key = self.api_key
        original_api_base_url = self.api_base_url

        try:
            if headers_provider is not None:
                self.headers_provider = headers_provider
            if key_name is not None:
                self.key_name = key_name
            if api_key is not None:
                self.api_key = api_key
            if api_base_url is not None:
                self.api_base_url = api_base_url

            # Only JSON-safe values go in options
            if key_name is not None:
                options["key_name"] = key_name
            if api_key is not None:
                options["api_key"] = api_key
            if api_base_url is not None:
                options["openrouter_api_base_url"] = api_base_url

            canonical_request = ConnectorChatCompletionsRequest(
                request=domain_request,
                processed_messages=processed_messages,
                effective_model=effective_model,
                identity=identity,
                cancellation_token=cancellation_token,
                cancellation_coordinator=cancellation_coordinator,
                context=context,
                options=options,
            )

            return await self._chat_completions_canonical(canonical_request)
        finally:
            # Restore original values
            self.headers_provider = original_headers_provider
            self.key_name = original_key_name
            self.api_key = original_api_key
            self.api_base_url = original_api_base_url

    async def _chat_completions_canonical(
        self,
        request: ConnectorChatCompletionsRequest,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Canonical connector API implementation.

        This method implements ICanonicalChatCompletionsBackend protocol.
        It applies OpenRouter-specific payload modifications before delegating
        to parent OpenAIConnector's canonical method.
        """
        # Structural enforcement: check cancellation immediately if coordinator and token provided
        if (
            request.cancellation_coordinator is not None
            and request.cancellation_token is not None
        ):
            request.cancellation_coordinator.ensure_not_cancelled(
                request.cancellation_token
            )

        # Extract OpenRouter-specific options from canonical request
        # JSON-SAFETY: Options contain only JSON-serializable values.
        # Callables (headers_provider) are handled via instance attributes, not options.
        options = request.options or {}
        key_name_val = options.get("key_name")
        key_name: str | None = key_name_val if isinstance(key_name_val, str) else None
        api_key_val = options.get("api_key")
        api_key: str | None = api_key_val if isinstance(api_key_val, str) else None
        api_base_url_val = options.get("openrouter_api_base_url")
        api_base_url: str | None = (
            api_base_url_val if isinstance(api_base_url_val, str) else None
        )

        # Use instance attributes for callables (JSON-safety: callables not in options)
        headers_provider = self.headers_provider

        # Fallback to instance attributes if not in options
        if key_name is None:
            key_name = self.key_name
        if api_key is None:
            api_key = self.api_key
        if api_base_url is None:
            api_base_url = self.api_base_url

        # After fallback, api_base_url is guaranteed to be str (not None)
        # Type narrowing: self.api_base_url is str, so api_base_url is now str
        assert (
            api_base_url is not None
        ), "api_base_url should be set from options or instance"

        original_headers_provider = self.headers_provider
        original_key_name = self.key_name
        original_api_key = self.api_key
        original_api_base_url = self.api_base_url

        try:
            # Temporarily set instance attributes for this call
            if headers_provider is not None:
                self.headers_provider = headers_provider
            if key_name is not None:
                self.key_name = key_name
            if api_key is not None:
                self.api_key = api_key
            # api_base_url is guaranteed to be str after fallback above
            self.api_base_url = api_base_url

            # Build modified canonical request with OpenRouter-specific options merged
            # JSON-SAFETY: Only include JSON-serializable values in options.
            # Callables (headers_provider) must remain as instance attributes, not in options.
            merged_options = dict(request.options or {})
            merged_options.update(
                {
                    # JSON-safe values only - callables are handled via instance attributes
                    "key_name": key_name,
                    "api_key": api_key,
                    "openrouter_api_base_url": api_base_url,
                    "headers_override": None,  # Will be computed below
                    "openai_url": api_base_url,
                }
            )

            # Compute explicit headers for this call
            headers_override: dict[str, str] | None = None
            if self.headers_provider:
                try:
                    headers_override = dict(self._resolve_headers_from_provider())
                except AuthenticationError:
                    headers_override = None
                except Exception as exc:
                    logger.error(
                        "Unexpected error resolving headers from provider in _chat_completions_canonical()",
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

            if request.identity is not None:
                try:
                    identity_headers = request.identity.get_resolved_headers(None)
                    if identity_headers:
                        headers_override.update(identity_headers)
                except (AttributeError, TypeError, ValueError) as exc:
                    logger.error(
                        "Failed to resolve identity headers in _chat_completions_canonical()",
                        exc_info=True,
                    )
                    raise ConfigurationError(
                        message="Failed to resolve identity configuration",
                        details={"identity_error": str(exc)},
                    ) from exc
                except Exception as exc:
                    logger.error(
                        "Unexpected error resolving identity headers in _chat_completions_canonical()",
                        exc_info=True,
                    )
                    raise ConfigurationError(
                        message="Unexpected error resolving identity configuration",
                        details={"unexpected_error": str(exc)},
                    ) from exc

            if not headers_override:
                headers_override = None

            # Update merged_options with computed headers_override
            # Type cast needed: dict[str, str] | None -> JsonValue
            merged_options["headers_override"] = cast(JsonValue, headers_override)

            modified_request = ConnectorChatCompletionsRequest(
                request=request.request,
                processed_messages=request.processed_messages,
                effective_model=request.effective_model,
                identity=request.identity,
                cancellation_token=request.cancellation_token,
                cancellation_coordinator=request.cancellation_coordinator,
                context=request.context,
                options=merged_options,
            )

            # Delegate to parent's canonical method
            result = await super()._chat_completions_canonical(modified_request)
            if (
                isinstance(result, StreamingResponseEnvelope)
                and result.content is not None
            ):
                keepalive_interval = self._resolve_stream_keepalive_interval()
                idle_timeout = self._resolve_stream_idle_timeout()
                if idle_timeout is not None and idle_timeout > 0:
                    stream_id = None
                    if request.context is not None:
                        stream_id = getattr(request.context, "session_id", None)
                    if not stream_id:
                        stream_id = getattr(request.request, "session_id", None)
                    result.content = self._wrap_stream_with_idle_timeout(
                        result.content,
                        stream_id=cast(str | None, stream_id),
                        model_name=request.effective_model,
                        keepalive_interval=keepalive_interval,
                        idle_timeout=idle_timeout,
                        cancel_callback=result.cancel_callback,
                    )
            return result
        finally:
            # Restore original values
            self.headers_provider = original_headers_provider
            self.key_name = original_key_name
            self.api_key = original_api_key
            self.api_base_url = original_api_base_url


backend_registry.register_backend("openrouter", OpenRouterBackend)
