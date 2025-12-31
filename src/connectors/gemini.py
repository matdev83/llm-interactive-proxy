from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import uuid
from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass
from typing import Any, cast

import httpx
from fastapi import HTTPException

from src.connectors.base import LLMBackend, add_vendor_prefix
from src.connectors.mixins.usage_calculation_mixin import UsageCalculationMixin
from src.core.common.exceptions import (
    AuthenticationError,
    BackendError,
    ServiceUnavailableError,
)
from src.core.config.app_config import AppConfig  # Added
from src.core.domain.chat import (
    CanonicalChatRequest,
    ChatRequest,
    MessageContentPartImage,
    MessageContentPartText,
)
from src.core.domain.models_listing import ModelInfo, ModelsListingResponse
from src.core.domain.responses import (
    ResponseEnvelope,
    StreamingResponseEnvelope,
    StreamingResponseHandle,
)
from src.core.domain.session_key import SessionKey
from src.core.domain.usage_summary import UsageSummary
from src.core.interfaces.configuration_interface import IAppIdentityConfig
from src.core.interfaces.model_bases import DomainModel, InternalDTO
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.security.loop_prevention import ensure_loop_guard_header
from src.core.services.backend_registry import backend_registry
from src.core.services.translation_service import TranslationService

# Legacy ChatCompletionRequest removed from connector signatures; use domain ChatRequest

# API key redaction and command filtering are now handled by middleware
# from src.security import APIKeyRedactor, ProxyCommandFilter

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GeminiApiConfig:
    """Resolved configuration for Gemini API requests."""

    base_url: str
    headers: dict[str, str]


class GeminiBackend(LLMBackend, UsageCalculationMixin):
    """LLMBackend implementation for Google's Gemini API.

    Implements StreamProducer protocol for streaming pipeline integration.
    """

    backend_type: str = "gemini"

    # Vendor prefix for Google models in unified model routing
    VENDOR_PREFIX: str = "google"

    def __init__(
        self,
        client: httpx.AsyncClient,
        config: AppConfig,
        translation_service: TranslationService,
    ) -> None:
        self.client = client
        self.config = config  # Stored config
        self.translation_service = translation_service
        self.available_models: list[str] = []

    async def initialize(self, **kwargs: Any) -> None:
        """Store configuration for lazy initialization."""
        self.gemini_api_base_url = kwargs.get("gemini_api_base_url")
        self.key_name = kwargs.get("key_name")
        self.api_key = kwargs.get("api_key")

        if not self.gemini_api_base_url or not self.key_name or not self.api_key:
            raise ValueError(
                "gemini_api_base_url, key_name, and api_key are required for GeminiBackend"
            )

        # Don't make HTTP calls during initialization
        # Models will be fetched on first use

    async def _ensure_models_loaded(self) -> None:
        """Fetch models if not already cached."""
        if (
            not self.available_models
            and hasattr(self, "api_key")
            and self.gemini_api_base_url
            and self.key_name
            and self.api_key
        ):
            try:
                data = await self.list_models(
                    gemini_api_base_url=self.gemini_api_base_url,
                    key_name=self.key_name,
                    api_key=self.api_key,
                )
                self.available_models = [m.id for m in data.data if m.id]

            except (ServiceUnavailableError, BackendError) as e:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Failed to fetch Gemini models: %s", e, exc_info=True
                    )
                # Return empty list on failure, don't crash
                self.available_models = []
            except Exception as e:
                if logger.isEnabledFor(logging.ERROR):
                    logger.error(
                        "Unexpected error fetching Gemini models: %s", e, exc_info=True
                    )
                self.available_models = []

    def get_available_models(self) -> list[str]:
        """Return cached Gemini model names with vendor prefix.

        Returns:
            List of model names with 'google/' vendor prefix.
            For example: ['google/gemini-pro', 'google/gemini-pro-vision']
        """
        return [
            add_vendor_prefix(m, self.VENDOR_PREFIX)
            for m in (self.available_models or [])
        ]

    async def get_available_models_async(self) -> list[str]:
        """Return Gemini model names with vendor prefix, fetching them if not cached.

        Returns:
            List of model names with 'google/' vendor prefix.
        """
        await self._ensure_models_loaded()
        return [
            add_vendor_prefix(m, self.VENDOR_PREFIX)
            for m in (self.available_models or [])
        ]

    # Translation is now handled by TranslationService

    def _convert_part_for_gemini(
        self, part: MessageContentPartText | MessageContentPartImage
    ) -> dict[str, Any]:
        """Convert a MessageContentPart into Gemini API format."""
        if isinstance(part, MessageContentPartText):
            # Text content is already processed by middleware
            return {"text": part.text}

        # Must be MessageContentPartImage
        url = part.image_url.url
        # Data URL -> inlineData
        if url.startswith("data:"):
            try:
                header, b64_data = url.split(",", 1)
                mime = header.split(";")[0][5:]
            except (ValueError, IndexError) as parse_err:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Failed to parse data URL MIME type: %s", str(parse_err)
                    )
                mime = "application/octet-stream"
                b64_data = ""
            return {"inlineData": {"mimeType": mime, "data": b64_data}}
        # Otherwise treat as remote file URI
        return {"fileData": {"mimeType": "application/octet-stream", "fileUri": url}}
        data = part.model_dump(exclude_unset=True)
        if data.get("type") == "text" and "text" in data:
            # Text content is already processed by middleware
            data.pop("type", None)
        return data

    def _prepare_gemini_contents(
        self, processed_messages: list[Any]
    ) -> list[dict[str, Any]]:
        payload_contents = []
        for msg in processed_messages:
            # Handle both object and dict formats for backward compatibility
            if isinstance(msg, dict):
                role = msg.get("role")
                # For dict format, check if it's already in Gemini format (has "parts")
                # or in generic format (has "content")
                if "parts" in msg:
                    # Already in Gemini format, use directly
                    payload_contents.append({"role": role, "parts": msg["parts"]})
                    continue
                else:
                    content = msg.get("content")
            else:
                role = getattr(msg, "role", None)
                content = getattr(msg, "content", None)

            if role == "system":
                # Gemini API does not support system role
                continue

            if isinstance(content, str):
                # If this is a tool or function role, represent it as functionResponse for Gemini
                if role in ("tool", "function"):
                    # Try to parse JSON payload; otherwise wrap string
                    try:
                        input_obj = json.loads(content)
                    except json.JSONDecodeError as json_err:
                        if logger.isEnabledFor(logging.DEBUG):
                            logger.debug(
                                "Failed to parse tool content as JSON, wrapping as string: %s",
                                json_err,
                                exc_info=True,
                            )
                        input_obj = {"output": content}
                    except Exception as e:
                        if logger.isEnabledFor(logging.WARNING):
                            logger.warning(
                                "Unexpected error parsing tool content: %s",
                                e,
                                exc_info=True,
                            )
                        input_obj = {"output": content}
                    parts: list[dict[str, Any]] = [
                        {
                            "functionResponse": {
                                "name": (
                                    getattr(msg, "name", "tool") or "tool"
                                    if not isinstance(msg, dict)
                                    else msg.get("name", "tool")
                                ),
                                "response": input_obj,
                            }
                        }
                    ]
                else:
                    # Content is already processed by middleware
                    parts = [{"text": content}]
            elif content is not None:
                parts = [self._convert_part_for_gemini(part) for part in content]
            else:
                # Skip messages with no content
                continue

            # Map roles to 'user' or 'model' as required by Gemini API
            if role == "user":
                gemini_role = "user"
            elif role in ["tool", "function"]:
                # Tool/function results are treated as coming from the user side in Gemini
                gemini_role = "user"
            else:  # e.g., assistant
                gemini_role = "model"

            payload_contents.append({"role": gemini_role, "parts": parts})
        return payload_contents

    @staticmethod
    def _coerce_stream_chunk(raw_chunk: Any) -> dict[str, Any] | None:
        if isinstance(raw_chunk, dict):
            return raw_chunk

        if isinstance(raw_chunk, bytes | bytearray):
            raw_chunk = raw_chunk.decode("utf-8", errors="ignore")

        if not isinstance(raw_chunk, str):
            return None

        stripped_chunk = raw_chunk.strip()
        if not stripped_chunk:
            return None

        data_segments: list[str] = []
        for line in stripped_chunk.splitlines():
            line = line.strip()
            if not line or line.startswith(":"):
                continue
            if line.startswith("data:"):
                data_value = line[5:].strip()
                if not data_value:
                    continue
                if data_value == "[DONE]":
                    return None
                data_segments.append(data_value)
            else:
                data_segments.append(line)

        for segment in data_segments or [stripped_chunk]:
            try:
                parsed = json.loads(segment)
            except json.JSONDecodeError:
                continue

            if isinstance(parsed, dict):
                return parsed

            if isinstance(parsed, str):
                stripped_parsed = parsed.strip()
                if stripped_parsed:
                    return {
                        "candidates": [
                            {
                                "content": {"parts": [{"text": stripped_parsed}]},
                            }
                        ]
                    }

            # If parsed value is not usable, continue searching remaining segments
            continue

        # Fallback to treating the content as plain text
        return {
            "candidates": [
                {
                    "content": {"parts": [{"text": stripped_chunk}]},
                }
            ]
        }

    async def _handle_gemini_streaming_response(
        self,
        base_url: str,
        payload: dict[str, Any],
        headers: dict[str, str],
        effective_model: str,
    ) -> StreamingResponseHandle:
        request_headers = ensure_loop_guard_header(headers)
        request_id = request_headers.get("x-goog-request-id") or uuid.uuid4().hex
        request_headers.setdefault("x-goog-request-id", request_id)

        url = f"{base_url}/streamGenerateContent"
        try:
            request = self.client.build_request(
                "POST", url, json=payload, headers=request_headers
            )
            response = await self.client.send(request, stream=True)
        except httpx.RequestError as e:
            if logger.isEnabledFor(logging.ERROR):
                logger.error("Request error connecting to Gemini: %s", e, exc_info=True)
            raise ServiceUnavailableError(
                message=f"Could not connect to Gemini ({e})"
            ) from e
        except (AttributeError, TypeError):
            request = self.client.build_request(
                "POST", url, json=payload, headers=request_headers
            )
            try:
                response = await self.client.send(request, stream=True)
            except httpx.RequestError as e:
                if logger.isEnabledFor(logging.ERROR):
                    logger.error(
                        "Request error connecting to Gemini: %s", e, exc_info=True
                    )
                raise ServiceUnavailableError(
                    message=f"Could not connect to Gemini ({e})"
                ) from e

        if response.status_code >= 400:
            try:
                # Read only first 10MB of error body to prevent DoS.
                max_error_body_bytes = 10 * 1024 * 1024
                body_buffer = bytearray()
                if hasattr(response, "aiter_bytes"):
                    async for chunk in response.aiter_bytes():
                        remaining = max_error_body_bytes - len(body_buffer)
                        if remaining <= 0:
                            break
                        if len(chunk) > remaining:
                            body_buffer.extend(chunk[:remaining])
                            break
                        body_buffer.extend(chunk)
                    body_bytes = bytes(body_buffer)
                elif hasattr(response, "aread"):
                    body_bytes = await response.aread()
                else:
                    body_bytes = b""

                body_text = body_bytes.decode("utf-8", errors="ignore")
            except (UnicodeDecodeError, AttributeError) as decode_err:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Failed to decode error response body as UTF-8: %s",
                        decode_err,
                        exc_info=True,
                    )
                body_text = ""
            except Exception as e:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Unexpected error decoding error response body: %s",
                        e,
                        exc_info=True,
                    )
                body_text = ""
            finally:
                if hasattr(response, "aclose"):
                    await response.aclose()
            if logger.isEnabledFor(logging.ERROR):
                body_preview_limit = 4096
                body_preview = (
                    body_text
                    if len(body_text) <= body_preview_limit
                    else f"{body_text[:body_preview_limit]}...[truncated]"
                )
                logger.error(
                    "HTTP error during Gemini stream: %s - body_len=%s body_preview=%s",
                    response.status_code,
                    len(body_text),
                    body_preview,
                )
            raise BackendError(
                message=f"Gemini stream error: {response.status_code} - {body_text}",
                code="gemini_error",
                status_code=response.status_code,
            )

        # Prefer response-provided request identifiers when available
        response_request_id = response.headers.get("x-goog-request-id")
        if response_request_id:
            request_id = response_request_id

        cancel_lock = asyncio.Lock()
        cancel_state = {"called": False}

        async def cancel_stream() -> None:
            async with cancel_lock:
                if cancel_state["called"]:
                    return
                cancel_state["called"] = True

            cancel_url = f"{base_url}:cancel"
            cancel_headers = ensure_loop_guard_header(dict(request_headers))
            payload_body = {"requestId": request_id}

            try:
                cancel_response = await self.client.post(
                    cancel_url,
                    json=payload_body,
                    headers=cancel_headers,
                )
            except httpx.RequestError as exc:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Gemini cancel request failed - url=%s request_id=%s error=%s",
                        cancel_url,
                        request_id,
                        exc,
                        exc_info=True,
                    )
            except Exception as exc:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Unexpected error during Gemini cancel request - url=%s request_id=%s error=%s",
                        cancel_url,
                        request_id,
                        exc,
                        exc_info=True,
                    )
            else:
                with contextlib.suppress(Exception):
                    await cancel_response.aclose()

            with contextlib.suppress(Exception):
                await response.aclose()

        async def stream_generator() -> AsyncGenerator[ProcessedResponse, None]:
            processed_stream = response.aiter_text()

            try:
                async for raw_chunk in processed_stream:
                    parsed_chunk = self._coerce_stream_chunk(raw_chunk)
                    if parsed_chunk is None:
                        continue

                    yield ProcessedResponse(
                        content=self.translation_service.to_domain_stream_chunk(
                            parsed_chunk, source_format="gemini"
                        )
                    )

                done_chunk = {
                    "candidates": [
                        {
                            "content": {"parts": []},
                            "finishReason": "STOP",
                        }
                    ]
                }
                yield ProcessedResponse(
                    content=self.translation_service.to_domain_stream_chunk(
                        done_chunk, source_format="gemini"
                    )
                )
            except httpx.RequestError as stream_error:
                logger.error(
                    "Request error while streaming from Gemini: %s",
                    stream_error,
                    exc_info=True,
                )
                raise ServiceUnavailableError(
                    message=f"Gemini streaming connection error ({stream_error})"
                ) from stream_error
            finally:
                with contextlib.suppress(Exception):
                    await response.aclose()

        try:
            response_headers = dict(response.headers)
        except (TypeError, AttributeError) as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Failed to convert response.headers to dict: %s",
                    e,
                    exc_info=True,
                )
            response_headers = {}

        return StreamingResponseHandle(
            iterator=stream_generator(),
            cancel_callback=cancel_stream,
            headers=response_headers,
        )

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
        openrouter_api_base_url: str | None = None,
        openrouter_headers_provider: Callable[[Any, str], dict[str, str]] | None = None,
        key_name: str | None = None,
        api_key: str | None = None,
        project: str | None = None,
        agent: str | None = None,
        gemini_api_base_url: str | None = None,
        **kwargs: Any,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        # Structural enforcement: check cancellation immediately if coordinator and token provided
        if cancellation_coordinator is not None and cancellation_token is not None:
            cancellation_coordinator.ensure_not_cancelled(cancellation_token)
        # request_data is expected to be a domain ChatRequest (or subclass like CanonicalChatRequest)
        # (the frontend controller converts from frontend-specific format to domain format)
        # Backends should ONLY convert FROM domain TO backend-specific format
        # Type assertion: we know from architectural design that request_data is ChatRequest-like

        if not isinstance(request_data, ChatRequest):
            raise TypeError(
                f"Expected ChatRequest or CanonicalChatRequest, got {type(request_data).__name__}. "
                "Backend connectors should only receive domain-format requests."
            )
        # Cast to CanonicalChatRequest for mypy compatibility with translation service signature
        domain_request: CanonicalChatRequest = cast(CanonicalChatRequest, request_data)

        try:
            # Resolve base configuration
            api_config = await self._resolve_gemini_api_config(
                gemini_api_base_url,
                openrouter_api_base_url,
                api_key,
                openrouter_headers_provider=openrouter_headers_provider,
                key_name=key_name,
                **kwargs,
            )
        except Exception as e:

            # If streaming was requested, we must return a streaming error response
            # instead of letting the exception bubble up (which would result in a JSON response)
            if domain_request.stream:
                from src.core.ports.streaming_contracts import handle_streaming_error

                # Bind e to err to preserve it after except block exits
                async def error_generator(
                    err: Exception = e,
                ) -> AsyncGenerator[ProcessedResponse, None]:
                    chunk = await handle_streaming_error(
                        err,
                        getattr(domain_request, "session_id", None),
                        self.get_provider_name(),
                    )
                    # Convert to SSE bytes and wrap in ProcessedResponse
                    chunk_bytes = chunk.to_bytes()
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            f"Gemini streaming error chunk bytes: {chunk_bytes!r}"
                        )
                    yield ProcessedResponse(content=chunk_bytes)

                return StreamingResponseEnvelope(
                    content=error_generator(),
                    media_type="text/event-stream",
                    headers={},
                )
            raise

        if identity:
            api_config.headers.update(identity.get_resolved_headers(None))

        # Translate CanonicalChatRequest to Gemini request using the translation service
        payload = self.translation_service.from_domain_request(
            domain_request, target_format="gemini"
        )

        # Apply generation config including temperature clamping
        self._apply_generation_config(payload, domain_request)

        # Apply contents and extra_body
        payload["contents"] = self._prepare_gemini_contents(processed_messages)
        if domain_request.extra_body:
            # Merge extra_body with payload, but be careful with generationConfig.
            # We support both legacy placement under 'generation_config' and
            # the external 'generationConfig' key that Gemini expects.
            # Normalize: prefer explicit generation_config on ChatRequest, then
            # merge any 'generationConfig' present in extra_body on top.
            extra_body_copy = dict(domain_request.extra_body)

            # If caller placed generation_config on ChatRequest it was already
            # merged by _apply_generation_config into payload['generationConfig'].
            # Now merge any generationConfig from extra_body on top of what we
            # already have (extra body should be able to override specific keys).
            # Accept either CamelCase 'generationConfig' (as used in tests and
            # by external callers) or legacy snake_case 'generation_config'
            extra_gen_cfg = extra_body_copy.pop("generationConfig", None)
            if extra_gen_cfg is None:
                extra_gen_cfg = extra_body_copy.pop("generation_config", None)
            if extra_gen_cfg:
                # merge by creating a new dict so we don't retain old references
                existing = payload.get("generationConfig", {})
                merged = dict(existing)

                # Handle nested structures like thinkingConfig
                for key, value in extra_gen_cfg.items():
                    if (
                        key == "thinkingConfig"
                        and isinstance(value, dict)
                        and "thinkingConfig" in merged
                        and isinstance(merged["thinkingConfig"], dict)
                    ):
                        # Deep merge thinkingConfig
                        merged["thinkingConfig"].update(value)
                    elif key == "maxOutputTokens" and "maxOutputTokens" not in merged:
                        # Add maxOutputTokens if not present
                        merged["maxOutputTokens"] = value
                    else:
                        # Regular update for other keys
                        merged[key] = value

                # Ensure extra_body overrides win for temperature specifically
                if "temperature" in extra_gen_cfg:
                    merged["temperature"] = extra_gen_cfg["temperature"]
                payload["generationConfig"] = merged

            # Finally update payload with remaining extra body fields
            if extra_body_copy:
                payload.update(extra_body_copy)
        # Remove generation_config (legacy key) if present; we've migrated it
        # into 'generationConfig' in _apply_generation_config.
        payload.pop("generation_config", None)
        # Debug output
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Final payload: %s", payload)

        # Normalize model id and construct URL
        model_name = self._normalize_model_name(effective_model)
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Constructing Gemini API URL with model_name: %s", model_name)
        model_url = f"{api_config.base_url}/v1beta/models/{model_name}"

        # Streaming vs non-streaming

        if domain_request.stream:
            # Use the new streaming pipeline orchestrator
            # This integrates: Backend → Normalizer → Processors → Assembler
            # To pass protocol-constrained parameters to stream_completion,
            # we create a copy of the request and embed them in extra_body.
            extra_data: dict[str, Any] = {
                "gemini_api_base_url": gemini_api_base_url,
                "api_key": api_key,
                "key_name": key_name,
                "openrouter_api_base_url": openrouter_api_base_url,
            }

            new_extra_body = (domain_request.extra_body or {}).copy()
            new_extra_body.update(extra_data)

            streaming_request = domain_request.model_copy(
                update={"extra_body": new_extra_body}
            )

            # Get raw stream from backend via StreamProducer protocol
            raw_stream = self.stream_completion(streaming_request)

            # Integrate with streaming pipeline
            # Calculate prompt tokens for usage tracking
            prompt_tokens = 0
            try:
                from src.core.utils.token_count import (
                    count_tokens,
                    extract_prompt_text,
                )

                prompt_text = extract_prompt_text(processed_messages)
                prompt_tokens = count_tokens(prompt_text, model=effective_model)
            except Exception:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning("Failed to calculate prompt tokens", exc_info=True)

            # Integrate with streaming pipeline
            from src.core.ports.streaming_integration import (
                integrate_streaming_pipeline,
            )

            return await integrate_streaming_pipeline(
                raw_stream=raw_stream,
                provider=self.get_provider_name(),
                stream_id=getattr(domain_request, "session_id", None),
                enable_loop_detection=True,
                enable_tool_call_repair=True,
                enable_think_tags=True,
                prompt_tokens=prompt_tokens,
                model_name=effective_model,
                vtc_enabled=getattr(domain_request, "vtc_enabled", False) or False,
            )

        response_envelope = await self._handle_gemini_non_streaming_response(
            model_url, payload, api_config.headers, effective_model
        )

        # Ensure usage is calculated if missing
        return self.ensure_usage_in_response(
            response_envelope, processed_messages, effective_model
        )

    def _build_openrouter_header_context(self) -> dict[str, str]:
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

    async def _resolve_gemini_api_config(
        self,
        gemini_api_base_url: str | None,
        openrouter_api_base_url: str | None,
        api_key: str | None,
        *,
        openrouter_headers_provider: Callable[[Any, str], dict[str, str]] | None = None,
        key_name: str | None = None,
        **kwargs: Any,
    ) -> GeminiApiConfig:
        # Prefer explicit params, then kwargs, then instance attributes set during initialize
        base = (
            gemini_api_base_url
            or openrouter_api_base_url
            or kwargs.get("gemini_api_base_url")
            or getattr(self, "gemini_api_base_url", None)
        )
        key = api_key or kwargs.get("api_key") or getattr(self, "api_key", None)
        if not base or not key:
            raise HTTPException(
                status_code=500,
                detail="Gemini API base URL and API key must be provided.",
            )
        normalized_base = base.rstrip("/")

        # Only use OpenRouter mode if the chosen base is actually OpenRouter
        # OpenRouter mode should only be enabled when the resolved base URL is different
        # from the default Gemini API base URL, indicating we're actually routing to OpenRouter
        gemini_default_base = "https://generativelanguage.googleapis.com"
        using_openrouter = (
            openrouter_api_base_url is not None
            and normalized_base != gemini_default_base.rstrip("/")
        )

        headers: dict[str, str]
        if using_openrouter:
            headers = {}
            provided_headers: dict[str, str] | None = None

            if openrouter_headers_provider is not None:
                errors: list[Exception] = []

                if key_name is not None:
                    try:
                        candidate = openrouter_headers_provider(key_name, key)
                    except (AttributeError, TypeError) as exc:
                        errors.append(exc)
                    else:
                        if candidate:
                            provided_headers = dict(candidate)

                if provided_headers is None:
                    context = self._build_openrouter_header_context()
                    try:
                        candidate = openrouter_headers_provider(context, key)
                    except Exception as exc:  # pragma: no cover - defensive guard
                        if errors and logger.isEnabledFor(logging.DEBUG):
                            logger.debug(
                                "OpenRouter headers provider rejected key_name input: %s",
                                errors[-1],
                                exc_info=True,
                            )
                        raise AuthenticationError(
                            message="OpenRouter headers provider failed to produce headers.",
                            code="missing_credentials",
                        ) from exc
                    else:
                        provided_headers = dict(candidate)

            if provided_headers is None:
                context = self._build_openrouter_header_context()
                provided_headers = {
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": context["app_site_url"],
                    "X-Title": context["app_x_title"],
                }

            headers.update(provided_headers)
            context = self._build_openrouter_header_context()
            headers.setdefault("Authorization", f"Bearer {key}")
            headers.setdefault("Content-Type", "application/json")
            headers.setdefault("HTTP-Referer", context["app_site_url"])
            headers.setdefault("X-Title", context["app_x_title"])
        else:
            key_name_to_use = (
                key_name
                or kwargs.get("key_name")
                or getattr(self, "key_name", None)
                or "x-goog-api-key"
            )
            headers = {key_name_to_use: key}

        return GeminiApiConfig(
            base_url=normalized_base, headers=ensure_loop_guard_header(headers)
        )

    def _apply_generation_config(
        self, payload: dict[str, Any], request_data: ChatRequest
    ) -> None:
        # Initialize generationConfig
        generation_config = payload.setdefault("generationConfig", {})

        # thinking budget
        if getattr(request_data, "thinking_budget", None):
            thinking_config = generation_config.setdefault("thinkingConfig", {})
            thinking_config["thinkingBudget"] = request_data.thinking_budget  # type: ignore[index]

        # top_k
        if getattr(request_data, "top_k", None) is not None:
            generation_config["topK"] = request_data.top_k

        # reasoning_effort
        if getattr(request_data, "reasoning_effort", None) is not None:
            thinking_config = generation_config.setdefault("thinkingConfig", {})
            thinking_config["reasoning_effort"] = request_data.reasoning_effort

        # generation config blob - merge with existing config
        if getattr(request_data, "generation_config", None):
            # Deep merge the generation_config into generationConfig
            for key, value in request_data.generation_config.items():  # type: ignore[union-attr]
                generation_config[key] = value

        # temperature clamped to [0,1]
        temperature = getattr(request_data, "temperature", None)
        if temperature is not None:
            # Clamp temperature to [0,1] range for Gemini
            if float(temperature) > 1.0:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        f"Temperature {temperature} > 1.0 for Gemini, clamping to 1.0"
                    )
                temperature = 1.0
            generation_config["temperature"] = float(temperature)

        # top_p
        if request_data.top_p is not None:
            generation_config["topP"] = request_data.top_p

        # stop sequences
        if request_data.stop:
            generation_config["stopSequences"] = request_data.stop

        # Unsupported parameters
        if request_data.seed is not None and logger.isEnabledFor(logging.WARNING):
            logger.warning("GeminiBackend does not support the 'seed' parameter.")
        if request_data.presence_penalty is not None and logger.isEnabledFor(
            logging.WARNING
        ):
            logger.warning(
                "GeminiBackend does not support the 'presence_penalty' parameter."
            )
        if request_data.frequency_penalty is not None and logger.isEnabledFor(
            logging.WARNING
        ):
            logger.warning(
                "GeminiBackend does not support the 'frequency_penalty' parameter."
            )
        if request_data.logit_bias is not None and logger.isEnabledFor(logging.WARNING):
            logger.warning("GeminiBackend does not support the 'logit_bias' parameter.")
        if request_data.user is not None and logger.isEnabledFor(logging.WARNING):
            logger.warning("GeminiBackend does not support the 'user' parameter.")

    def _normalize_model_name(self, effective_model: str) -> str:
        model_name = effective_model
        if model_name.startswith("gemini:"):
            model_name = model_name.split(":", 1)[1]
        if model_name.startswith("models/"):
            model_name = model_name.split("/", 1)[1]
        if model_name.startswith("gemini/"):
            model_name = model_name.split("/", 1)[1]
        if "/" in model_name:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Detected provider prefix in model name '%s'. Using last path segment as Gemini model id.",
                    model_name,
                )
            model_name = model_name.rsplit("/", 1)[-1]
        return model_name

    async def _handle_gemini_non_streaming_response(
        self, base_url: str, payload: dict, headers: dict, effective_model: str
    ) -> ResponseEnvelope:
        headers = ensure_loop_guard_header(headers)
        url = f"{base_url}:generateContent"
        try:
            response = await self.client.post(url, json=payload, headers=headers)
            if response.status_code >= 400:
                try:
                    error_detail = response.json()
                except json.JSONDecodeError as json_err:
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning(
                            "Failed to parse error response as JSON, using text: %s",
                            json_err,
                            exc_info=True,
                        )
                    error_detail = response.text
                except Exception as e:
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning(
                            "Unexpected error parsing error response: %s",
                            e,
                            exc_info=True,
                        )
                    error_detail = response.text
                raise BackendError(
                    message=str(error_detail),
                    code="gemini_error",
                    status_code=response.status_code,
                )
            data = response.json()
            if logger.isEnabledFor(logging.DEBUG):
                safe_headers = dict(response.headers)
                for sensitive_key in ["Authorization", "Set-Cookie"]:
                    if sensitive_key in safe_headers:
                        safe_headers[sensitive_key] = "[REDACTED]"
                logger.debug("Gemini response headers: %s", safe_headers)

            # Extract usage from Gemini response
            usage = self._extract_gemini_usage(data)

            canonical_response = self.translation_service.to_domain_response(
                data, source_format="gemini"
            )

            content_dict = (
                canonical_response.model_dump() if canonical_response else None
            )
            return ResponseEnvelope(
                content=content_dict if isinstance(content_dict, dict | type(None)) else str(canonical_response),  # type: ignore[arg-type]
                headers=dict(response.headers),
                status_code=response.status_code,
                usage=usage,
            )

        except httpx.RequestError as e:
            logger.error("Request error connecting to Gemini: %s", e, exc_info=True)
            raise ServiceUnavailableError(
                message=f"Could not connect to Gemini ({e})"
            ) from e

    async def list_models(
        self, *, gemini_api_base_url: str, key_name: str, api_key: str
    ) -> ModelsListingResponse:
        headers = ensure_loop_guard_header({key_name: api_key})
        url = f"{gemini_api_base_url.rstrip('/')}/v1beta/models"
        try:
            response = await self.client.get(url, headers=headers)
            if response.status_code >= 400:
                try:
                    error_detail = response.json()
                except json.JSONDecodeError as json_err:
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning(
                            "Failed to parse error response as JSON, using text: %s",
                            json_err,
                            exc_info=True,
                        )
                    error_detail = response.text
                except Exception as e:
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning(
                            "Unexpected error parsing error response: %s",
                            e,
                            exc_info=True,
                        )
                    error_detail = response.text
                raise BackendError(
                    message=str(error_detail),
                    code="gemini_error",
                    status_code=response.status_code,
                )

            data = response.json()
            raw_models = data.get("models", [])
            model_infos = []
            for m in raw_models:
                if isinstance(m, dict):
                    model_infos.append(
                        ModelInfo(
                            id=m.get("name") or "",
                            name=m.get("displayName") or m.get("name"),
                            object="model",
                            owned_by="google",
                        )
                    )
            return ModelsListingResponse(object="list", data=model_infos)
        except httpx.RequestError as e:
            logger.error("Request error connecting to Gemini: %s", e, exc_info=True)
            raise ServiceUnavailableError(
                message=f"Could not connect to Gemini ({e})"
            ) from e

    def _extract_gemini_usage(
        self, response_data: dict[str, Any]
    ) -> UsageSummary | None:
        """Extract usage information from Gemini API response.

        Args:
            response_data: The response data from Gemini API

        Returns:
            UsageSummary or None if not found
        """
        try:
            usage_metadata = response_data.get("usageMetadata", {})
            if not usage_metadata:
                return None

            prompt_tokens = usage_metadata.get("promptTokenCount", 0)
            completion_tokens = usage_metadata.get("candidatesTokenCount", 0)
            total_tokens = usage_metadata.get("totalTokenCount", 0)

            # If all are zero, return None to trigger calculation
            if prompt_tokens == 0 and completion_tokens == 0 and total_tokens == 0:
                return None

            return UsageSummary(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
            )
        except Exception as e:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Failed to extract Gemini usage: %s", e)
            return None

    # StreamProducer protocol implementation
    async def stream_completion(
        self, request: CanonicalChatRequest
    ) -> AsyncGenerator[object, None]:
        """Yield raw streaming chunks from the backend.

        This method implements the StreamProducer protocol for integration
        with the streaming pipeline refactor.

        Args:
            request: The chat completion request

        Yields:
            Raw streaming chunks from the backend (opaque provider-specific data)
        """
        # Prepare payload

        # Get processed messages and effective model
        processed_messages = getattr(request, "messages", [])
        effective_model = getattr(request, "model", "gemini-1.5-flash")

        extra_body = getattr(request, "extra_body", {}) or {}

        try:
            api_config = await self._resolve_gemini_api_config(
                gemini_api_base_url=extra_body.get("gemini_api_base_url"),
                openrouter_api_base_url=extra_body.get("openrouter_api_base_url"),
                api_key=extra_body.get("api_key"),
                key_name=extra_body.get("key_name"),
                effective_model=effective_model,
            )
        except HTTPException as e:

            raise BackendError(
                message=e.detail, code="config_error", status_code=e.status_code
            ) from e

        # Prepare payload
        payload = self.translation_service.from_domain_request(
            request, target_format="gemini"
        )

        # Apply generation config including temperature clamping
        domain_request: ChatRequest = cast(ChatRequest, request)
        self._apply_generation_config(payload, domain_request)

        # Apply contents
        payload["contents"] = self._prepare_gemini_contents(processed_messages)

        # Normalize model name and build URL
        model_name = self._normalize_model_name(effective_model)
        url = f"{api_config.base_url}/v1beta/models/{model_name}:streamGenerateContent"

        # Prepare headers
        request_headers = ensure_loop_guard_header(api_config.headers)

        request_id = request_headers.get("x-goog-request-id") or uuid.uuid4().hex
        request_headers.setdefault("x-goog-request-id", request_id)

        # Build and send request
        try:
            http_request = self.client.build_request(
                "POST", url, json=payload, headers=request_headers
            )
            response = await self.client.send(http_request, stream=True)
        except httpx.RequestError as e:
            logger.error("Request error connecting to Gemini: %s", e, exc_info=True)
            raise ServiceUnavailableError(
                message=f"Could not connect to Gemini ({e})"
            ) from e

        # Check for errors
        if response.status_code >= 400:
            try:
                # Read only first 10MB of error body to prevent DoS.
                max_error_body_bytes = 10 * 1024 * 1024
                body_buffer = bytearray()
                if hasattr(response, "aiter_bytes"):
                    async for chunk in response.aiter_bytes():
                        remaining = max_error_body_bytes - len(body_buffer)
                        if remaining <= 0:
                            break
                        if len(chunk) > remaining:
                            body_buffer.extend(chunk[:remaining])
                            break
                        body_buffer.extend(chunk)
                    body_bytes = bytes(body_buffer)
                elif hasattr(response, "aread"):
                    body_bytes = await response.aread()
                else:
                    body_bytes = b""

                body_text = body_bytes.decode("utf-8", errors="ignore")
            except (UnicodeDecodeError, AttributeError) as decode_err:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Failed to decode error response body as UTF-8: %s",
                        decode_err,
                        exc_info=True,
                    )
                body_text = ""
            except Exception as e:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Unexpected error decoding error response body: %s",
                        e,
                        exc_info=True,
                    )
                body_text = ""
            finally:
                if hasattr(response, "aclose"):
                    await response.aclose()
            if logger.isEnabledFor(logging.ERROR):
                body_preview_limit = 4096
                body_preview = (
                    body_text
                    if len(body_text) <= body_preview_limit
                    else f"{body_text[:body_preview_limit]}...[truncated]"
                )
                logger.error(
                    "HTTP error during Gemini stream: %s - body_len=%s body_preview=%s",
                    response.status_code,
                    len(body_text),
                    body_preview,
                )
            raise BackendError(
                message=f"Gemini stream error: {response.status_code} - {body_text}",
                code="gemini_error",
                status_code=response.status_code,
            )

        # Stream JSON-lines chunks
        try:
            async for raw_chunk in response.aiter_text():
                # Yield raw chunks (JSON-lines format)
                yield raw_chunk
        except httpx.RequestError as stream_error:
            logger.error(
                "Request error while streaming from Gemini: %s",
                stream_error,
                exc_info=True,
            )
            raise ServiceUnavailableError(
                message=f"Gemini streaming connection error ({stream_error})"
            ) from stream_error
        finally:
            with contextlib.suppress(Exception):
                await response.aclose()

    def _get_base_url(self) -> str:
        """Get the base URL for Gemini API requests.

        Returns:
            The base URL for Gemini API requests
        """
        if not hasattr(self, "gemini_api_base_url") or self.gemini_api_base_url is None:
            raise AttributeError(
                "gemini_api_base_url is not set. Call initialize() first."
            )
        base_url: str = self.gemini_api_base_url
        return base_url

    def _get_headers(self) -> dict[str, str]:
        """Get the headers for Gemini API requests.

        Returns:
            Dictionary of headers for API requests
        """
        headers: dict[str, str] = {}
        if hasattr(self, "api_key") and self.api_key:
            key_name = getattr(self, "key_name", "x-goog-api-key")
            if isinstance(key_name, str):
                headers[key_name] = str(self.api_key)
        return headers

    async def _prepare_payload(
        self, request: Any, processed_messages: list[Any], effective_model: str
    ) -> dict[str, Any]:
        """Prepare the payload for Gemini API requests.

        Args:
            request: The chat completion request
            processed_messages: Processed message list
            effective_model: The model to use

        Returns:
            Prepared payload dictionary
        """
        # Resolve base configuration (validates config)
        await self._resolve_gemini_api_config(
            getattr(request, "gemini_api_base_url", None),
            getattr(request, "openrouter_api_base_url", None),
            getattr(request, "api_key", None),
            effective_model=effective_model,
        )

        # Apply generation config
        payload: dict[str, Any] = {
            "model": f"models/{effective_model}",
            "contents": self._prepare_gemini_contents(processed_messages),
        }

        # Apply generation config including temperature clamping
        # Type assertion: we know from architectural design that request_data is ChatRequest-like

        domain_request: ChatRequest = cast(ChatRequest, request)
        self._apply_generation_config(payload, domain_request)

        return payload

    def get_provider_name(self) -> str:
        """Return the provider name for logging/metrics.

        Returns:
            Provider name ("gemini")
        """
        return "gemini"


backend_registry.register_backend("gemini", GeminiBackend)
