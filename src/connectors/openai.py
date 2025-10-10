from __future__ import annotations

import contextlib
import inspect
import logging

logger = logging.getLogger(__name__)

from collections.abc import AsyncGenerator, AsyncIterator, Mapping
from typing import Any

import httpx
from fastapi import HTTPException

from src.connectors.base import LLMBackend
from src.core.common.exceptions import AuthenticationError, ServiceUnavailableError
from src.core.config.app_config import AppConfig
from src.core.domain.chat import CanonicalChatRequest
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.configuration_interface import IAppIdentityConfig
from src.core.interfaces.model_bases import DomainModel, InternalDTO
from src.core.interfaces.response_processor_interface import (
    IResponseProcessor,
    ProcessedResponse,
)
from src.core.security.loop_prevention import ensure_loop_guard_header
from src.core.services.backend_registry import backend_registry
from src.core.services.translation_service import TranslationService

# Legacy ChatCompletionRequest removed from connector signatures; use domain ChatRequest


class OpenAIConnector(LLMBackend):
    """Minimal OpenAI-compatible connector used by OpenRouterBackend in tests.

    It supports an optional `headers_override` kwarg and treats streaming
    responses that expose `aiter_bytes()` as streamable even if returned by
    test doubles.
    """

    backend_type: str = "openai"

    def __init__(
        self,
        client: httpx.AsyncClient,
        config: AppConfig,
        translation_service: TranslationService | None = None,
        response_processor: IResponseProcessor | None = None,
    ) -> None:
        super().__init__(config, response_processor)
        self.client = client
        # Allow callers/tests to omit TranslationService; create a default instance
        self.translation_service = (
            translation_service
            if translation_service is not None
            else TranslationService()
        )
        self.config = config  # Stored config
        self.available_models: list[str] = []
        self.api_key: str | None = None
        self.api_base_url: str = "https://api.openai.com/v1"
        self.identity: Any | None = None

        # Health check attributes
        self._health_checked: bool = False
        # Check environment variable to allow disabling health checks globally
        import os

        disable_health_checks = os.getenv("DISABLE_HEALTH_CHECKS", "false").lower() in (
            "true",
            "1",
            "yes",
        )

        # Health checks enabled by default unless explicitly disabled via env
        self._health_check_enabled: bool = not disable_health_checks

    def get_headers(self) -> dict[str, str]:
        """Return request headers including API key and per-request identity."""

        headers: dict[str, str] = {}

        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        if self.identity:
            try:
                identity_headers = self.identity.get_resolved_headers(None)
            except Exception:
                identity_headers = {}
            if identity_headers:
                headers.update(identity_headers)

        return ensure_loop_guard_header(headers)

    async def initialize(self, **kwargs: Any) -> None:
        self.api_key = kwargs.get("api_key")
        logger.info(
            "OpenAIConnector initialize called. api_key_provided=%s",
            "yes" if self.api_key else "no",
        )
        if "api_base_url" in kwargs:
            self.api_base_url = kwargs["api_base_url"]

        # Proceed to fetch models only when we have credentials; failures are non-fatal
        if not self.api_key:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Skipping OpenAI model listing during init; no API key configured"
                )
        else:
            try:
                headers = self.get_headers()
                response = await self.client.get(
                    f"{self.api_base_url}/models", headers=headers
                )
                # For mock responses in tests, status_code might not be accessible
                # or might not be 200, so we just try to access the data directly
                data = response.json()
                self.available_models = [model["id"] for model in data.get("data", [])]
            except Exception as e:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning("Failed to fetch models: %s", e, exc_info=True)
                # Log the error but don't fail initialization

    async def _perform_health_check(self) -> bool:
        """Perform a health check by testing API connectivity.

        This method tests actual API connectivity by making a simple request to verify
        the API key works and the service is accessible.

        Returns:
            bool: True if health check passes, False otherwise
        """
        try:
            # Test API connectivity with a simple models endpoint request
            if not self.api_key:
                logger.warning("Health check failed - no API key available")
                return False

            headers = self.get_headers()
            if not headers.get("Authorization"):
                logger.warning("Health check failed - no authorization header")
                return False

            url = f"{self.api_base_url}/models"
            response = await self.client.get(url, headers=headers)

            if response.status_code == 200:
                logger.info("Health check passed - API connectivity verified")
                self._health_checked = True
                return True
            else:
                logger.warning(
                    f"Health check failed - API returned status {response.status_code}"
                )
                return False

        except Exception as e:
            if logger.isEnabledFor(logging.ERROR):
                logger.error(
                    "Health check failed - unexpected error: %s", e, exc_info=True
                )
            return False

    async def _ensure_healthy(self) -> None:
        """Ensure the backend is healthy before use.

        This method performs health checks on first use, similar to how
        models are loaded lazily in the parent class.
        """
        if not self._health_check_enabled:
            # Health check is disabled, skip
            return

        if not hasattr(self, "_health_checked") or not self._health_checked:
            logger.info(
                f"Performing first-use health check for {self.backend_type} backend"
            )

            healthy = await self._perform_health_check()
            if not healthy:
                logger.warning(
                    "Health check did not pass; continuing with lazy verification on first request"
                )
            else:
                logger.info("Health check passed - backend is ready for use")

            self._health_checked = True

    def enable_health_check(self) -> None:
        """Enable health check functionality for this connector instance."""
        self._health_check_enabled = True
        self._health_checked = False  # Reset so it will check on next use
        logger.info(f"Health check enabled for {self.backend_type} backend")

    def disable_health_check(self) -> None:
        """Disable health check functionality for this connector instance."""
        self._health_check_enabled = False
        logger.info(f"Health check disabled for {self.backend_type} backend")

    async def chat_completions(
        self,
        request_data: DomainModel | InternalDTO | dict[str, Any],
        processed_messages: list[Any],
        effective_model: str,
        identity: IAppIdentityConfig | None = None,
        **kwargs: Any,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        # Perform health check if enabled (for subclasses that support it)
        await self._ensure_healthy()

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
        # Cast to CanonicalChatRequest for mypy compatibility with _prepare_payload signature
        domain_request: CanonicalChatRequest = cast(CanonicalChatRequest, request_data)

        # Ensure identity headers are scoped to the current request only.
        self.identity = identity

        # Prepare the payload using a helper so subclasses and tests can
        # override or patch payload construction logic easily.
        payload = await self._prepare_payload(
            domain_request, processed_messages, effective_model
        )
        headers_override = kwargs.pop("headers_override", None)
        headers: dict[str, str] | None = None

        if headers_override is not None:
            # Avoid mutating the caller-provided mapping while preserving any
            # Authorization header we compute from the configured API key.
            headers = dict(headers_override)

            try:
                base_headers = self.get_headers()
            except Exception:
                base_headers = None

            if base_headers:
                merged_headers = dict(base_headers)
                merged_headers.update(headers)
                headers = merged_headers
        else:
            try:
                # Always update the cached identity so that per-request
                # identity headers do not leak between calls. Downstream
                # callers rely on identity-specific headers being scoped to
                # a single request.
                self.identity = identity
                headers = self.get_headers()
            except Exception:
                headers = None

        api_base = kwargs.get("openai_url") or self.api_base_url
        url = f"{api_base.rstrip('/')}/chat/completions"

        if domain_request.stream:
            # Return a domain-level streaming envelope (raw bytes iterator)
            try:
                content_iterator = await self._handle_streaming_response(
                    url,
                    payload,
                    headers,
                    domain_request.session_id or "",
                    "openai",
                )
            except AuthenticationError as e:
                raise HTTPException(status_code=401, detail=str(e))
            return StreamingResponseEnvelope(
                content=content_iterator,
                media_type="text/event-stream",
                headers={},
            )
        else:
            # Return a domain ResponseEnvelope for non-streaming
            return await self._handle_non_streaming_response(
                url, payload, headers, domain_request.session_id or ""
            )

    async def _prepare_payload(
        self,
        request_data: CanonicalChatRequest,
        processed_messages: list[Any],
        effective_model: str,
    ) -> dict[str, Any]:
        """
        Default payload preparation for OpenAI-compatible backends.

        Subclasses or tests may patch/override this method to customize the
        final payload sent to the provider.
        """
        # request_data is expected to be a CanonicalChatRequest already
        # (the caller creates it via TranslationService.to_domain_request).
        payload = self.translation_service.from_domain_request(request_data, "openai")

        # Prefer processed_messages (these are the canonical, post-processed
        # messages ready to send). Convert them to plain dicts to ensure JSON
        # serializability without mutating the original Pydantic models.
        if processed_messages:
            try:
                normalized_messages: list[dict[str, Any]] = []

                def _get_value(message: Any, key: str) -> Any:
                    if isinstance(message, Mapping):
                        return message.get(key)
                    return getattr(message, key, None)

                def _normalize_content(value: Any) -> Any:
                    if isinstance(value, list | tuple):
                        normalized_parts: list[Any] = []
                        for part in value:
                            if hasattr(part, "model_dump") and callable(
                                part.model_dump
                            ):
                                normalized_parts.append(
                                    part.model_dump(exclude_none=True)
                                )
                            elif isinstance(part, Mapping):
                                normalized_parts.append(dict(part))
                            else:
                                normalized_parts.append(part)
                        return normalized_parts
                    return value

                for message in processed_messages:
                    if hasattr(message, "model_dump") and callable(message.model_dump):
                        normalized_messages.append(
                            dict(message.model_dump(exclude_none=False))
                        )
                        continue

                    msg: dict[str, Any]
                    if isinstance(message, Mapping):
                        msg = dict(message)
                    else:
                        msg = {}

                    role = _get_value(message, "role") or msg.get("role") or "user"
                    msg["role"] = role

                    content = _get_value(message, "content")
                    if content is None and "content" in msg:
                        content = msg["content"]
                    msg["content"] = _normalize_content(content)

                    name = _get_value(message, "name")
                    if name is not None:
                        msg["name"] = name

                    tool_calls = _get_value(message, "tool_calls")
                    if tool_calls is None and isinstance(message, Mapping):
                        tool_calls = msg.get("tool_calls")
                    if tool_calls:
                        normalized_tool_calls: list[Any] = []
                        for tool_call in tool_calls:
                            if hasattr(tool_call, "model_dump") and callable(
                                tool_call.model_dump
                            ):
                                normalized_tool_calls.append(
                                    tool_call.model_dump(exclude_none=True)
                                )
                            elif isinstance(tool_call, Mapping):
                                normalized_tool_calls.append(dict(tool_call))
                            else:
                                normalized_tool_calls.append(tool_call)
                        msg["tool_calls"] = normalized_tool_calls

                    tool_call_id = _get_value(message, "tool_call_id")
                    if tool_call_id is not None:
                        msg["tool_call_id"] = tool_call_id

                    normalized_messages.append(msg)

                payload["messages"] = normalized_messages
            except (KeyError, TypeError, AttributeError):
                # Fallback - leave whatever the converter produced
                pass

        # The caller may supply an "effective_model" which should override
        # the model value coming from the domain request. Many tests expect
        # the provider payload to use the effective_model.
        if effective_model:
            payload["model"] = effective_model

        # Allow request.extra_body to override or augment the final payload.
        extra = getattr(request_data, "extra_body", None)
        if isinstance(extra, dict):
            payload.update(extra)

        return payload  # type: ignore[no-any-return]

    async def _handle_non_streaming_response(
        self,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str] | None,
        session_id: str,
    ) -> ResponseEnvelope:
        if not headers or not headers.get("Authorization"):
            raise AuthenticationError(message="No auth credentials found")

        guarded_headers = ensure_loop_guard_header(headers)

        try:
            response = await self.client.post(
                url, json=payload, headers=guarded_headers
            )
        except httpx.RequestError as e:
            raise ServiceUnavailableError(message=f"Could not connect to backend ({e})")

        if int(response.status_code) >= 400:
            # For backwards compatibility with existing error handlers, still use HTTPException here.
            # This will be replaced in a future update with domain exceptions.
            try:
                err = response.json()
            except Exception:
                err = response.text
            raise HTTPException(status_code=response.status_code, detail=err)

        domain_response = self.translation_service.to_domain_response(
            response.json(), "openai"
        )
        # Some tests use mocks that set response.headers to AsyncMock or
        # other non-dict types; defensively coerce to a dict and fall back
        # to an empty dict on error so tests don't raise during header
        # extraction.
        try:
            response_headers = dict(response.headers)
        except Exception:
            try:
                response_headers = dict(getattr(response, "headers", {}) or {})
            except Exception:
                response_headers = {}

        return ResponseEnvelope(
            content=domain_response.model_dump(),
            status_code=response.status_code,
            headers=response_headers,
            usage=domain_response.usage,
        )

    async def _handle_streaming_response(
        self,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str] | None,
        session_id: str,
        stream_format: str,
    ) -> AsyncIterator[ProcessedResponse]:
        """Return an AsyncIterator of ProcessedResponse objects (transport-agnostic)"""

        if not headers or not headers.get("Authorization"):
            raise AuthenticationError(message="No auth credentials found")

        guarded_headers = ensure_loop_guard_header(headers)

        request = self.client.build_request(
            "POST", url, json=payload, headers=guarded_headers
        )
        try:
            response = await self.client.send(request, stream=True)
        except httpx.RequestError as exc:  # Normalize network failures
            raise ServiceUnavailableError(
                message=f"Could not connect to backend ({exc})"
            ) from exc

        status_code = (
            int(response.status_code) if hasattr(response, "status_code") else 200
        )
        if status_code >= 400:
            # For backwards compatibility with existing error handlers, still use HTTPException here.
            # This will be replaced in a future update with domain exceptions.
            close_callable = getattr(response, "aclose", None)
            try:
                body = (await response.aread()).decode("utf-8")
            except Exception:
                body = getattr(response, "text", "")
            finally:
                if callable(close_callable):
                    with contextlib.suppress(Exception):
                        maybe_awaitable = close_callable()
                        if inspect.isawaitable(maybe_awaitable):
                            await maybe_awaitable
            raise HTTPException(
                status_code=status_code,
                detail={
                    "message": body,
                    "type": (
                        "openrouter_error" if "openrouter" in url else "openai_error"
                    ),
                    "code": status_code,
                },
            )

        async def gen() -> AsyncGenerator[ProcessedResponse, None]:
            # Forward raw text stream; central pipeline will handle normalization/repairs
            async def text_generator() -> AsyncGenerator[str, None]:
                async for chunk in response.aiter_text():
                    yield self.translation_service.to_domain_stream_chunk(
                        chunk, stream_format
                    )

            try:
                async for chunk in text_generator():
                    yield ProcessedResponse(content=chunk)
            finally:
                import contextlib

                with contextlib.suppress(Exception):
                    await response.aclose()

        # For streaming responses, return raw bytes; response processing is
        # handled at the adapter layer if needed.
        return gen()

    async def responses(
        self,
        request_data: DomainModel | InternalDTO | dict[str, Any],
        processed_messages: list[Any],
        effective_model: str,
        identity: IAppIdentityConfig | None = None,
        **kwargs: Any,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Handle OpenAI Responses API calls.

        This method handles requests to the /v1/responses endpoint, which provides
        structured output generation with JSON schema validation.
        """
        # Perform health check if enabled
        await self._ensure_healthy()

        # Convert to domain request first
        # Note: The responses() method can be called directly with dicts (e.g., from tests),
        # unlike chat_completions() which only goes through the frontend->backend flow
        domain_request = self.translation_service.to_domain_request(
            request_data, "responses"
        )

        # Prepare the payload for Responses API
        payload = self.translation_service.from_domain_to_responses_request(
            domain_request
        )

        # Override model if effective_model is provided
        if effective_model:
            payload["model"] = effective_model

        # Ensure identity headers are scoped per request before computing headers.
        self.identity = identity

        # Update messages with processed_messages if available
        if processed_messages:
            try:
                normalized_messages: list[dict[str, Any]] = []
                for m in processed_messages:
                    # If the message is a pydantic model, use model_dump
                    if hasattr(m, "model_dump") and callable(m.model_dump):
                        normalized_messages.append(
                            dict(m.model_dump(exclude_none=False))
                        )
                        continue

                    # Fallback: build a minimal dict
                    msg: dict[str, Any] = {"role": getattr(m, "role", "user")}
                    content = getattr(m, "content", None)
                    msg["content"] = content

                    # Add other message fields if present
                    name = getattr(m, "name", None)
                    if name:
                        msg["name"] = name
                    tool_calls = getattr(m, "tool_calls", None)
                    if tool_calls:
                        msg["tool_calls"] = tool_calls
                    tool_call_id = getattr(m, "tool_call_id", None)
                    if tool_call_id:
                        msg["tool_call_id"] = tool_call_id
                    normalized_messages.append(msg)

                payload["messages"] = normalized_messages
            except (KeyError, TypeError, AttributeError):
                # Fallback - leave whatever the converter produced
                pass

        headers_override = kwargs.pop("headers_override", None)
        resolved_headers: dict[str, str] | None = None

        if headers_override is not None:
            resolved_headers = dict(headers_override)

        if identity:
            self.identity = identity

        base_headers: dict[str, str] | None
        try:
            base_headers = self.get_headers()
        except Exception:
            base_headers = None

        if base_headers is not None:
            merged_headers = dict(base_headers)
            if resolved_headers:
                merged_headers.update(resolved_headers)
            resolved_headers = merged_headers

        headers = resolved_headers

        api_base = kwargs.get("openai_url") or self.api_base_url
        url = f"{api_base.rstrip('/')}/responses"

        guarded_headers = ensure_loop_guard_header(headers)

        if domain_request.stream:
            # Return a domain-level streaming envelope
            try:
                content_iterator = await self._handle_streaming_response(
                    url,
                    payload,
                    guarded_headers,
                    domain_request.session_id or "",
                    "openai-responses",
                )
            except AuthenticationError as e:
                raise HTTPException(status_code=401, detail=str(e))
            return StreamingResponseEnvelope(
                content=content_iterator,
                media_type="text/event-stream",
                headers={},
            )
        else:
            # Return a domain ResponseEnvelope for non-streaming
            return await self._handle_responses_non_streaming_response(
                url, payload, guarded_headers, domain_request.session_id or ""
            )

    async def _handle_responses_non_streaming_response(
        self,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str] | None,
        session_id: str,
    ) -> ResponseEnvelope:
        """Handle non-streaming Responses API responses with proper format conversion."""
        if not headers or not headers.get("Authorization"):
            raise AuthenticationError(message="No auth credentials found")

        guarded_headers = ensure_loop_guard_header(headers)

        try:
            response = await self.client.post(
                url, json=payload, headers=guarded_headers
            )
        except httpx.RequestError as e:
            raise ServiceUnavailableError(message=f"Could not connect to backend ({e})")

        if int(response.status_code) >= 400:
            try:
                err = response.json()
            except Exception:
                err = response.text
            raise HTTPException(status_code=response.status_code, detail=err)

        # For Responses API, we need to handle the response differently
        # The response should already be in Responses API format from OpenAI
        response_data = response.json()

        # Convert to domain response first, then back to ensure consistency
        # We'll treat the Responses API response as a special case of OpenAI response
        domain_response = self.translation_service.to_domain_response(
            response_data, "openai-responses"
        )

        # Convert back to Responses API format for the final response
        responses_content = self.translation_service.from_domain_to_responses_response(
            domain_response
        )

        try:
            response_headers = dict(response.headers)
        except Exception:
            try:
                response_headers = dict(getattr(response, "headers", {}) or {})
            except Exception:
                response_headers = {}

        return ResponseEnvelope(
            content=responses_content,
            status_code=response.status_code,
            headers=response_headers,
            usage=domain_response.usage,
        )

    async def list_models(self, api_base_url: str | None = None) -> dict[str, Any]:
        headers = self.get_headers()
        base = api_base_url or self.api_base_url
        logger.info(f"OpenAIConnector list_models - base URL: {base}")
        response = await self.client.get(f"{base.rstrip('/')}/models", headers=headers)
        response.raise_for_status()
        result = response.json()
        return result  # type: ignore[no-any-return]  # type: ignore[no-any-return]


backend_registry.register_backend("openai", OpenAIConnector)
