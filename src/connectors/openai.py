from __future__ import annotations

import asyncio
import contextlib
import inspect
import json
import logging

logger = logging.getLogger(__name__)

from collections.abc import (
    AsyncGenerator,
    Mapping,
)
from json import JSONDecodeError
from typing import Any

import httpx
from fastapi import HTTPException

from src.core.common.exceptions import (
    AuthenticationError,
    ServiceResolutionError,
    ServiceUnavailableError,
)
from src.core.config.app_config import AppConfig
from src.core.domain.chat import CanonicalChatRequest
from src.core.domain.responses import (
    ResponseEnvelope,
    StreamingResponseEnvelope,
    StreamingResponseHandle,
)
from src.core.interfaces.configuration_interface import IAppIdentityConfig
from src.core.interfaces.model_bases import DomainModel, InternalDTO
from src.core.interfaces.response_processor_interface import (
    IResponseProcessor,
    ProcessedResponse,
)
from src.core.security.loop_prevention import ensure_loop_guard_header
from src.core.services.backend_registry import backend_registry
from src.core.services.translation_service import TranslationService

from .base import LLMBackend

# Legacy ChatCompletionRequest removed from connector signatures; use domain ChatRequest


class OpenAIConnector(LLMBackend):
    """Minimal OpenAI-compatible connector used by OpenRouterBackend in tests.

    It supports an optional `headers_override` kwarg and treats streaming
    responses that expose `aiter_bytes()` as streamable even if returned by
    test doubles.
    """

    backend_type: str = "openai"
    SUPPORTED_CUSTOM_PARAMETERS: frozenset[str] = frozenset()

    def __init__(
        self,
        client: httpx.AsyncClient,
        config: AppConfig,
        translation_service: TranslationService | None = None,
        response_processor: IResponseProcessor | None = None,
    ) -> None:
        super().__init__(config, response_processor)
        self.client = client
        # Allow callers/tests to omit TranslationService; resolve through DI for consistency
        self.translation_service = (
            translation_service
            if translation_service is not None
            else self._resolve_translation_service()
        )
        self.config = config  # Stored config
        self.available_models: list[str] = []
        self.api_key: str | None = None
        self._api_base_url: str = "https://api.openai.com/v1"

        # Health check attributes
        self._health_checked: bool = False
        import os

        disable_health_checks_env = os.getenv(
            "DISABLE_HEALTH_CHECKS", "false"
        ).lower() in ("true", "1", "yes")

        disable_health_checks_config = bool(
            getattr(self.config, "disable_health_checks", False)
        )

        # Enable health checks only when neither config nor env disable them
        self._health_check_enabled = not (
            disable_health_checks_env or disable_health_checks_config
        )

    @property
    def api_base_url(self) -> str:
        """Return the API base URL."""
        return self._api_base_url

    @api_base_url.setter
    def api_base_url(self, value: str) -> None:
        """Set the API base URL."""
        self._api_base_url = value

    @staticmethod
    def _resolve_translation_service() -> TranslationService:
        """Resolve TranslationService from the DI container."""

        from src.core.di.services import get_or_build_service_provider

        provider = get_or_build_service_provider()
        service = provider.get_service(TranslationService)
        if service is None:
            raise ServiceResolutionError(
                "TranslationService is not registered in the service provider",
                service_name="TranslationService",
            )
        return service

    def get_headers(self, identity: IAppIdentityConfig | None = None) -> dict[str, str]:
        """Return request headers including API key and optional request identity."""

        headers: dict[str, str] = {}

        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        if identity is not None:
            try:
                identity_headers = identity.get_resolved_headers(None)
            except Exception:
                identity_headers = {}
            else:
                identity_headers = dict(identity_headers)
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
            logger.debug(
                "Skipping OpenAI model listing during init; no API key configured"
            )
        else:
            try:
                headers = self.get_headers()
                response = await self.client.get(
                    f"{self.api_base_url}/models", headers=headers
                )
                data = self._decode_json_payload(response)
                if isinstance(data, dict):
                    self.available_models = [
                        model["id"]
                        for model in data.get("data", [])
                        if isinstance(model, Mapping) and "id" in model
                    ]
                else:
                    logger.debug(
                        "Unexpected models payload type from OpenAI: %s",
                        type(data).__name__,
                    )
                    self.available_models = []
            except Exception as e:
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
            logger.error("Health check failed - unexpected error: %s", e, exc_info=True)
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

    _XSSI_PREFIXES = (
        ")]}',\n",
        ")]}',",
        ")]}'",
        "while(1);",
        "while (1);",
    )

    def _decode_json_payload(self, response: httpx.Response) -> Any:
        """Safely decode JSON payloads that may include XSSI guards or trailing data."""
        try:
            return response.json()
        except JSONDecodeError:
            text = response.text or ""
            sanitized = self._strip_xssi_prefix(text)
            if sanitized != text:
                try:
                    return json.loads(sanitized)
                except JSONDecodeError:
                    pass
            candidate = self._extract_first_json_value(sanitized)
            if candidate:
                try:
                    return json.loads(candidate)
                except JSONDecodeError:
                    logger.debug(
                        "Failed to decode sanitized JSON payload; candidate snippet=%s",
                        candidate[:200],
                    )
            logger.warning(
                "Unable to decode JSON payload from OpenAI response (status=%s, preview=%r)",
                getattr(response, "status_code", "unknown"),
                (sanitized or text)[:200],
            )
            return None

    def _strip_xssi_prefix(self, payload: str) -> str:
        stripped = payload.lstrip()
        for prefix in self._XSSI_PREFIXES:
            if stripped.startswith(prefix):
                return stripped[len(prefix) :]
        return stripped

    def _extract_first_json_value(self, payload: str) -> str | None:
        candidate = payload.strip()
        if not candidate:
            return None

        opening = candidate[0]
        if opening not in ("{", "["):
            # Attempt to locate the first JSON object within the payload
            for idx, ch in enumerate(candidate):
                if ch in ("{", "["):
                    candidate = candidate[idx:]
                    opening = candidate[0]
                    break
            else:
                return None

        stack = []
        in_string = False
        escape = False
        for idx, ch in enumerate(candidate):
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                continue

            if ch == '"':
                in_string = True
                continue

            if ch in ("{", "["):
                stack.append("]" if ch == "[" else "}")
            elif ch in ("}", "]"):
                if not stack or stack.pop() != ch:
                    return None
                if not stack:
                    return candidate[: idx + 1]

        return None

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

        # Prepare the payload using a helper so subclasses and tests can
        # override or patch payload construction logic easily.
        payload = await self._prepare_payload(
            domain_request, processed_messages, effective_model
        )
        headers_override = kwargs.pop("headers_override", None)
        headers: dict[str, str] | None = None

        base_headers: dict[str, str] | None
        try:
            base_headers = self.get_headers(identity=identity)
        except Exception:
            base_headers = None

        if headers_override is not None:
            # Avoid mutating the caller-provided mapping while preserving any
            # Authorization header we compute from the configured API key.
            headers = dict(headers_override)
            if base_headers:
                merged_headers = dict(base_headers)
                merged_headers.update(headers)
                headers = merged_headers
        else:
            headers = base_headers

        api_base = kwargs.get("openai_url") or self.api_base_url
        url = f"{api_base.rstrip('/')}/chat/completions"

        if domain_request.stream:
            # Return a domain-level streaming envelope (raw bytes iterator)
            try:
                stream_handle = await self._handle_streaming_response(
                    url,
                    payload,
                    headers,
                    domain_request.session_id or "",
                    "openai",
                )
            except AuthenticationError as e:
                raise HTTPException(status_code=401, detail=str(e))
            return StreamingResponseEnvelope(
                content=stream_handle.iterator,
                media_type="text/event-stream",
                headers={},
                cancel_callback=stream_handle.cancel_callback,
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
        if inspect.isawaitable(payload):
            payload = await payload

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
                        dumped = message.model_dump(exclude_none=False)
                        if isinstance(dumped, dict):
                            normalized_messages.append(dumped)
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
            logger.info(
                f"OpenAI DEBUG: Overriding model in payload from '{payload.get('model')}' to '{effective_model}'"
            )
            payload["model"] = effective_model

        # Allow request.extra_body to override or augment the final payload.
        extra = getattr(request_data, "extra_body", None)
        if isinstance(extra, dict):
            payload.update(extra)

        self._filter_unsupported_parameters(payload)

        return payload  # type: ignore[no-any-return]

    def _filter_unsupported_parameters(self, payload: dict[str, Any]) -> None:
        unsupported_parameters = []
        for param_name in ("repetition_penalty", "min_p"):
            if param_name in payload and param_name not in self.SUPPORTED_CUSTOM_PARAMETERS:
                unsupported_parameters.append(param_name)

        if not unsupported_parameters:
            return

        backend_name = self.backend_type or self.__class__.__name__
        for param_name in unsupported_parameters:
            value = payload.pop(param_name, None)
            if value is not None and logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "%s backend does not support the '%s' parameter; ignoring value %r",
                    backend_name,
                    param_name,
                    value,
                )

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
    ) -> StreamingResponseHandle:
        """Return a streaming handle with iterator and cancellation callback."""

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
            body: str = ""
            try:
                body_bytes = await response.aread()
            except Exception:
                fallback: str = str(getattr(response, "text", ""))
                body = fallback() if callable(fallback) else fallback
            else:
                try:
                    body = body_bytes.decode("utf-8")
                except Exception:
                    fallback_text: str = str(getattr(response, "text", ""))
                    body = fallback_text() if callable(fallback_text) else fallback_text
            finally:
                with contextlib.suppress(Exception):
                    await response.aclose()

            if not isinstance(body, str):
                body = str(body)
            logger.warning(
                "Backend %s returned HTTP %s with body: %s", url, status_code, body
            )
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

        loop = asyncio.get_running_loop()
        response_id_future: asyncio.Future[str] = loop.create_future()
        cancel_lock = asyncio.Lock()
        cancel_state = {"called": False}
        supports_protocol_cancel = stream_format in {"responses", "openai-responses"}
        cancel_headers = dict(guarded_headers)
        cancel_headers.setdefault("Content-Type", "application/json")
        cancel_base_url = url.rstrip("/")

        async def cancel_stream() -> None:
            async with cancel_lock:
                if cancel_state["called"]:
                    return
                cancel_state["called"] = True

            if supports_protocol_cancel:
                target_id: str | None = None
                if response_id_future.done():
                    target_id = response_id_future.result()
                else:
                    try:
                        target_id = await asyncio.wait_for(response_id_future, 0.5)
                    except asyncio.TimeoutError:
                        target_id = None

                if target_id:
                    await self._send_openai_responses_cancel(
                        base_url=cancel_base_url,
                        headers=cancel_headers,
                        response_id=target_id,
                        session_id=session_id,
                    )

            with contextlib.suppress(Exception):
                await response.aclose()

        async def gen() -> AsyncGenerator[ProcessedResponse, None]:
            async def text_generator() -> AsyncGenerator[dict[Any, Any] | Any, None]:
                async def iter_sse_messages() -> AsyncGenerator[str, None]:
                    buffer = ""
                    separator = "\n\n"
                    alt_separator = "\r\n\r\n"
                    try:
                        async for chunk_bytes in response.aiter_bytes():
                            chunk_text = (
                                chunk_bytes.decode("utf-8", errors="replace")
                                if isinstance(chunk_bytes, bytes | bytearray)
                                else str(chunk_bytes)
                            )
                            buffer += chunk_text
                            while True:
                                if alt_separator in buffer:
                                    event, buffer = buffer.split(alt_separator, 1)
                                    separator_used = alt_separator
                                elif separator in buffer:
                                    event, buffer = buffer.split(separator, 1)
                                    separator_used = separator
                                else:
                                    break
                                if event:
                                    yield event + separator_used
                        if buffer:
                            yield buffer
                            buffer = ""
                    except httpx.RequestError as exc:
                        if buffer:
                            yield buffer
                            buffer = ""
                        raise ServiceUnavailableError(
                            message=f"Streaming connection interrupted ({exc})"
                        ) from exc

                try:
                    if stream_format in {"openai", "responses", "openai-responses"}:
                        async for message in iter_sse_messages():
                            domain_chunk = (
                                self.translation_service.to_domain_stream_chunk(
                                    message, stream_format
                                )
                            )
                            if (
                                isinstance(domain_chunk, dict)
                                and domain_chunk.get("error")
                                and logger.isEnabledFor(logging.DEBUG)
                            ):
                                try:
                                    logger.debug(
                                        "Streaming chunk translation returned error=%s raw=%s",
                                        domain_chunk.get("error"),
                                        (
                                            message[:500]
                                            if isinstance(message, str)
                                            else str(message)
                                        ),
                                    )
                                except Exception:
                                    logger.debug(
                                        "Streaming chunk translation returned error but raw chunk not serializable"
                                    )
                            yield domain_chunk
                    else:
                        async for chunk in response.aiter_text():
                            domain_chunk = (
                                self.translation_service.to_domain_stream_chunk(
                                    chunk, stream_format
                                )
                            )
                            if (
                                isinstance(domain_chunk, dict)
                                and domain_chunk.get("error")
                                and logger.isEnabledFor(logging.DEBUG)
                            ):
                                try:
                                    logger.debug(
                                        "Streaming chunk translation returned error=%s raw=%s",
                                        domain_chunk.get("error"),
                                        chunk[:500],
                                    )
                                except Exception:
                                    logger.debug(
                                        "Streaming chunk translation returned error but raw chunk not serializable"
                                    )
                            yield domain_chunk
                except httpx.RequestError as exc:
                    raise ServiceUnavailableError(
                        message=f"Streaming connection interrupted ({exc})"
                    ) from exc

            pending_error: Exception | None = None
            try:
                async for chunk in text_generator():
                    if (
                        supports_protocol_cancel
                        and isinstance(chunk, dict)
                        and not response_id_future.done()
                    ):
                        chunk_id = chunk.get("id")
                        if isinstance(chunk_id, str) and chunk_id:
                            response_id_future.set_result(chunk_id)
                    yield ProcessedResponse(content=chunk)
            except ServiceUnavailableError as exc:
                pending_error = exc
            except httpx.HTTPError as exc:
                raise ServiceUnavailableError(
                    message=f"Streaming connection interrupted ({exc})"
                ) from exc
            finally:
                with contextlib.suppress(Exception):
                    await response.aclose()
            if pending_error:
                raise pending_error

        try:
            response_headers = dict(response.headers)
        except Exception:
            response_headers = {}

        return StreamingResponseHandle(
            iterator=gen(),
            cancel_callback=cancel_stream,
            headers=response_headers,
        )

    async def _send_openai_responses_cancel(
        self,
        base_url: str,
        headers: Mapping[str, str],
        response_id: str,
        session_id: str,
    ) -> None:
        cancel_url = f"{base_url}/{response_id}/cancel"
        try:
            request = self.client.build_request("POST", cancel_url, headers=headers)
        except Exception as exc:
            logger.debug(
                "Failed to build cancellation request - session_id=%s, url=%s, error=%s",
                session_id,
                cancel_url,
                exc,
                exc_info=True,
            )
            return

        try:
            cancel_response = await self.client.send(request, stream=False)
        except Exception as exc:
            logger.warning(
                "Failed to send cancellation request - session_id=%s, url=%s, error=%s",
                session_id,
                cancel_url,
                exc,
                exc_info=True,
            )
            return

        with contextlib.suppress(Exception):
            await cancel_response.aclose()

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

        # Update messages with processed_messages if available
        if processed_messages:
            try:
                normalized_messages: list[dict[str, Any]] = []
                for m in processed_messages:
                    # If the message is a pydantic model, use model_dump
                    if hasattr(m, "model_dump") and callable(m.model_dump):
                        dumped = m.model_dump(exclude_none=False)
                        if isinstance(dumped, dict):
                            normalized_messages.append(dumped)
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

        base_headers: dict[str, str] | None
        try:
            base_headers = self.get_headers(identity=identity)
        except Exception:
            base_headers = None

        headers: dict[str, str] | None = None
        if base_headers is not None:
            merged_headers = dict(base_headers)
            if resolved_headers:
                merged_headers.update(resolved_headers)
            headers = merged_headers
        else:
            headers = resolved_headers

        api_base = kwargs.get("openai_url") or self.api_base_url
        url = f"{api_base.rstrip('/')}/responses"

        guarded_headers = ensure_loop_guard_header(headers)

        if domain_request.stream:
            # Return a domain-level streaming envelope
            try:
                stream_handle = await self._handle_streaming_response(
                    url,
                    payload,
                    guarded_headers,
                    domain_request.session_id or "",
                    "openai-responses",
                )
            except AuthenticationError as e:
                raise HTTPException(status_code=401, detail=str(e))
            return StreamingResponseEnvelope(
                content=stream_handle.iterator,
                media_type="text/event-stream",
                headers={},
                cancel_callback=stream_handle.cancel_callback,
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
