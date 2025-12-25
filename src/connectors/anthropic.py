"""
Anthropic backend connector - provides chat_completions and model discovery for the Anthropic Messages API.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncGenerator, Callable
from typing import Any, cast

import httpx

from src.connectors.base import LLMBackend, add_vendor_prefix, strip_vendor_prefix
from src.core.common.exceptions import (
    AuthenticationError,
    ConfigurationError,
    ServiceUnavailableError,
)
from src.core.config.app_config import AppConfig
from src.core.domain.chat import CanonicalChatRequest, ChatRequest
from src.core.domain.models_listing import ModelInfo, ModelsListingResponse
from src.core.domain.responses import (

    ResponseEnvelope,
    StreamingResponseEnvelope,
    StreamingResponseHandle,
)
from src.core.domain.session_key import SessionKey
from src.core.interfaces.configuration_interface import IAppIdentityConfig
from src.core.interfaces.model_bases import DomainModel, InternalDTO
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.security.loop_prevention import ensure_loop_guard_header
from src.core.services.backend_registry import backend_registry
from src.core.services.translation_service import TranslationService

# Legacy ChatCompletionRequest removed from connector signatures; use domain ChatRequest

# API key redaction and command filtering are now handled by middleware

logger = logging.getLogger(__name__)


ANTHROPIC_VERSION_HEADER = "2023-06-01"
ANTHROPIC_DEFAULT_BASE_URL = "https://api.anthropic.com/v1"

# Vendor prefix for Anthropic models in unified model naming convention
ANTHROPIC_VENDOR_PREFIX = "anthropic"


class AnthropicBackend(LLMBackend):
    """LLMBackend implementation for Anthropic's Messages API.

    Implements StreamProducer protocol for streaming pipeline integration.
    """

    backend_type: str = "anthropic"

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
        self.auth_header_name = "x-api-key"

    # -----------------------------------------------------------
    # Public helpers
    # -----------------------------------------------------------
    async def initialize(self, **kwargs: Any) -> None:
        """Store configuration for lazy initialization."""
        self.anthropic_api_base_url = kwargs.get("anthropic_api_base_url")
        self.key_name = kwargs.get("key_name")
        self.api_key = kwargs.get("api_key")
        self.auth_header_name = kwargs.get("auth_header_name", "x-api-key")

        if not self.key_name or not self.api_key:
            raise ConfigurationError(
                message="key_name and api_key are required for AnthropicBackend",
                code="missing_config",
            )

        # Don't make HTTP calls during initialization
        # Models will be fetched on first use

    async def _ensure_models_loaded(self) -> None:
        """Fetch models if not already cached."""
        if (
            not self.available_models
            and hasattr(self, "api_key")
            and self.key_name
            and self.api_key
        ):
            base_url = self.anthropic_api_base_url or ANTHROPIC_DEFAULT_BASE_URL
            try:
                data = await self.list_models(
                    base_url=base_url, key_name=self.key_name, api_key=self.api_key
                )
                self.available_models = [
                    str(m.get("name", m.get("id")))
                    for m in data
                    if isinstance(m, dict) and m.get("name", m.get("id")) is not None
                ]
            except Exception as e:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Failed to fetch Anthropic models: %s", e, exc_info=True
                    )
                # Return empty list on failure, don't crash
                self.available_models = []

    def get_available_models(self) -> list[str]:
        """Return cached Anthropic model names with vendor prefix.

        Returns:
            List of model names with 'anthropic/' vendor prefix.
            For example: ['anthropic/claude-3-opus', 'anthropic/claude-3-sonnet']
        """
        return [
            add_vendor_prefix(m, ANTHROPIC_VENDOR_PREFIX) for m in self.available_models
        ]

    async def get_available_models_async(self) -> list[str]:
        """Return Anthropic model names with vendor prefix, fetching them if not cached.

        Returns:
            List of model names with 'anthropic/' vendor prefix.
        """
        await self._ensure_models_loaded()
        return [
            add_vendor_prefix(m, ANTHROPIC_VENDOR_PREFIX) for m in self.available_models
        ]

    # -----------------------------------------------------------
    # Core entry - called by proxy
    # -----------------------------------------------------------
    async def chat_completions(  # type: ignore[override]
        self,
        request_data: DomainModel | InternalDTO | dict[str, Any],
        processed_messages: list,
        effective_model: str,
        identity: IAppIdentityConfig | None = None,
        cancellation_token: SessionKey | None = None,
        cancellation_coordinator: (
            Any | None
        ) = None,  # ISessionCancellationCoordinator | None
        openrouter_api_base_url: str | None = None,
        openrouter_headers_provider: Callable[[str, str], dict[str, str]] | None = None,
        key_name: str | None = None,
        api_key: str | None = None,
        project: str | None = None,
        agent: str | None = None,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        # Structural enforcement: check cancellation immediately if coordinator and token provided
        if cancellation_coordinator is not None and cancellation_token is not None:
            cancellation_coordinator.ensure_not_cancelled(cancellation_token)
        """Send request to Anthropic Messages endpoint and return domain response envelope."""
        # Strip vendor prefix (e.g., "anthropic/") for unified model naming
        effective_model = strip_vendor_prefix(effective_model, ANTHROPIC_VENDOR_PREFIX)

        # Allow per-call api_key or fall back to instance-api_key set during initialize
        effective_api_key = api_key or getattr(self, "api_key", None)
        if effective_api_key is None:
            raise AuthenticationError(
                message="Anthropic API key not configured", code="missing_api_key"
            )

        url = self._get_request_url(
            openrouter_api_base_url or getattr(self, "anthropic_api_base_url", None)
        )

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

        # request_data is a domain ChatRequest; connectors can rely on adapter helpers
        anthropic_payload = self._prepare_anthropic_payload(
            request_data=domain_request,
            processed_messages=processed_messages,
            effective_model=effective_model,
            project=project,
        )

        request_headers = {
            self.auth_header_name: effective_api_key,
            "anthropic-version": ANTHROPIC_VERSION_HEADER,
            "content-type": "application/json",
        }

        # Add anthropic-beta header for beta features
        beta_features: list[str] = []
        extra_body = domain_request.extra_body or {}

        # Extended thinking requires beta header
        if extra_body.get("thinking") or anthropic_payload.get("thinking"):
            beta_features.append("interleaved-thinking-2025-05-14")

        # Add any explicit beta features from extra_body
        explicit_betas = extra_body.get("anthropic_beta", [])
        if isinstance(explicit_betas, str):
            explicit_betas = [explicit_betas]
        beta_features.extend(explicit_betas)

        if beta_features:
            request_headers["anthropic-beta"] = ",".join(beta_features)

        if headers:
            # Merge any caller-supplied headers without losing mandatory
            # authentication defaults.  Copy the mapping to avoid mutating the
            # caller-owned dictionary.
            request_headers.update(headers)
        if identity:
            request_headers.update(identity.get_resolved_headers(None))

        request_headers = ensure_loop_guard_header(request_headers)

        if logger.isEnabledFor(logging.INFO):
            logger.info(
                "Forwarding to Anthropic. Model: %s Stream: %s",
                effective_model,
                domain_request.stream,
            )
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Anthropic payload: %s", json.dumps(anthropic_payload, indent=2)
            )

        if domain_request.stream:
            # Use the new streaming pipeline orchestrator
            # This integrates: Backend → Normalizer → Processors → Assembler
            try:
                # Get raw stream from backend via StreamProducer protocol
                raw_stream = self.stream_completion(domain_request)

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
                        logger.warning(
                            "Failed to calculate prompt tokens", exc_info=True
                        )

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
            except AuthenticationError:
                raise
        else:
            response_envelope = await self._handle_non_streaming_response(
                url, anthropic_payload, request_headers, domain_request.model
            )
            # Return a domain-level ResponseEnvelope
            return response_envelope

    # -----------------------------------------------------------
    # Payload helpers
    # -----------------------------------------------------------
    def _prepare_anthropic_payload(
        self,
        request_data: ChatRequest,
        processed_messages: list[Any],
        effective_model: str,
        project: str | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": effective_model.replace("anthropic:", ""),
            "max_tokens": request_data.max_tokens or 8192,
            "stream": bool(request_data.stream),
        }

        metadata_payload: Any | None = None
        if project or request_data.user is not None:
            metadata_payload = {}
            if project:
                metadata_payload["project"] = project
            if request_data.user is not None:
                metadata_payload["user_id"] = request_data.user

        # System message extraction (Anthropic expects it separately)
        system_prompt = None
        anth_messages: list[dict[str, Any]] = []
        for msg in processed_messages:
            if isinstance(msg, dict):
                role = msg.get("role")
                content = msg.get("content")
            else:
                role = getattr(msg, "role", None)
                content = getattr(msg, "content", None)

            if not role:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug("Skipping message without role: %r", msg)
                continue

            if role == "system":
                if isinstance(content, str):
                    system_prompt = content
                else:
                    # If list/parts, flatten to string for system
                    system_prompt = json.dumps(content)
                continue

            # Map content - content is already processed by middleware
            if isinstance(content, str):
                anth_messages.append({"role": role, "content": content})
            elif isinstance(content, list):
                # For list-of-parts, Anthropic supports various content block types
                parts: list[Any] = []
                for part in content:
                    if isinstance(part, dict):
                        part_obj = part.copy()
                        part_type = part_obj.get("type")

                        if part_type == "text" and "text" in part_obj:
                            # Text content is already processed by middleware
                            parts.append(part_obj)
                        elif part_type == "image":
                            # Anthropic image block - ensure proper source format
                            source = part_obj.get("source", {})
                            if source:
                                parts.append(part_obj)
                        elif part_type == "image_url":
                            # Convert OpenAI image_url format to Anthropic image format
                            image_url_data = part_obj.get("image_url", {})
                            url = (
                                image_url_data.get("url", "")
                                if isinstance(image_url_data, dict)
                                else str(image_url_data)
                            )
                            if url.startswith("data:"):
                                # Data URI - extract base64 and media type
                                try:
                                    header, data = url.split(",", 1)
                                    media_type = header.split(";")[0].replace(
                                        "data:", ""
                                    )
                                    parts.append(
                                        {
                                            "type": "image",
                                            "source": {
                                                "type": "base64",
                                                "media_type": media_type,
                                                "data": data,
                                            },
                                        }
                                    )
                                except ValueError:
                                    logger.warning(
                                        f"Invalid data URI format: {url[:50]}"
                                    )
                            elif url.startswith(("http://", "https://")):
                                # URL source
                                parts.append(
                                    {
                                        "type": "image",
                                        "source": {"type": "url", "url": url},
                                    }
                                )
                        elif part_type == "document":
                            # Document block (PDF) - pass through
                            parts.append(part_obj)
                        elif part_type in ("tool_use", "tool_result"):
                            # Tool-related blocks - pass through
                            parts.append(part_obj)
                        else:
                            # Unknown type - pass through
                            parts.append(part_obj)
                    else:
                        # unknown part type -> stringify
                        parts.append({"type": "text", "text": str(part)})
                anth_messages.append({"role": role, "content": parts})
            elif content is None:
                anth_messages.append({"role": role, "content": ""})
            else:
                anth_messages.append({"role": role, "content": str(content)})

        payload["messages"] = anth_messages
        if system_prompt:
            payload["system"] = system_prompt
        if request_data.temperature is not None:
            payload["temperature"] = request_data.temperature
        if request_data.top_p is not None:
            payload["top_p"] = request_data.top_p
        if request_data.stop is not None:
            stop_value = request_data.stop
            if isinstance(stop_value, str):
                payload["stop_sequences"] = [stop_value]
            else:
                payload["stop_sequences"] = list(stop_value)
        extra_body: dict[str, Any] = dict(request_data.extra_body or {})
        extra_metadata = extra_body.pop("metadata", None)
        if extra_metadata is not None:
            if metadata_payload is None:
                metadata_payload = (
                    dict(extra_metadata)
                    if isinstance(extra_metadata, dict)
                    else extra_metadata
                )
            elif isinstance(metadata_payload, dict) and isinstance(
                extra_metadata, dict
            ):
                metadata_payload.update(extra_metadata)
            else:
                metadata_payload = extra_metadata

        if metadata_payload is not None:
            payload["metadata"] = metadata_payload

        # Unsupported parameters
        if request_data.seed is not None and logger.isEnabledFor(logging.WARNING):
            logger.warning("AnthropicBackend does not support the 'seed' parameter.")
        if request_data.presence_penalty is not None and logger.isEnabledFor(
            logging.WARNING
        ):
            logger.warning(
                "AnthropicBackend does not support the 'presence_penalty' parameter."
            )
        if request_data.frequency_penalty is not None and logger.isEnabledFor(
            logging.WARNING
        ):
            logger.warning(
                "AnthropicBackend does not support the 'frequency_penalty' parameter."
            )
        if request_data.logit_bias is not None and logger.isEnabledFor(logging.WARNING):
            logger.warning(
                "AnthropicBackend does not support the 'logit_bias' parameter."
            )

        # Include tools and tool_choice when provided (tests set these fields)
        if request_data.tools is not None:
            payload["tools"] = request_data.tools

        # Handle extended thinking configuration from extra_body
        thinking_config = extra_body.pop("thinking", None)
        if thinking_config is not None:
            if isinstance(thinking_config, dict):
                payload["thinking"] = thinking_config
            elif hasattr(thinking_config, "model_dump"):
                payload["thinking"] = thinking_config.model_dump()
            else:
                # Assume it's a simple type indicator
                payload["thinking"] = {"type": str(thinking_config)}

        # Handle service_tier from extra_body
        service_tier = extra_body.pop("service_tier", None)
        if service_tier is not None:
            payload["service_tier"] = service_tier

        # Include extra params from domain extra_body directly (allows reasoning, etc.)
        # Filter out None values to prevent overriding defaults
        filtered_extra_body = {k: v for k, v in extra_body.items() if v is not None}
        payload.update(filtered_extra_body)

        # Ensure max_tokens is always a valid positive integer (never None)
        if payload.get("max_tokens") is None:
            payload["max_tokens"] = 8192

        # Include reasoning_effort when provided
        if getattr(request_data, "reasoning_effort", None) is not None:
            payload["reasoning_effort"] = request_data.reasoning_effort
        return payload

    def _get_request_url(self, api_base_url: str | None) -> str:
        """Construct the request URL, appending /messages."""
        base_url = (api_base_url or ANTHROPIC_DEFAULT_BASE_URL).rstrip("/")
        if base_url.endswith("/messages"):
            return base_url
        return f"{base_url}/messages"

    # -----------------------------------------------------------
    # Non-streaming handling
    # -----------------------------------------------------------
    async def _handle_non_streaming_response(
        self, url: str, payload: dict, headers: dict, original_model: str
    ) -> ResponseEnvelope:
        headers = ensure_loop_guard_header(headers)
        try:
            logger.info(
                f"Sending request to {url} with headers: {headers} and payload: {payload}"
            )
            response = await self.client.post(url, json=payload, headers=headers)
        except httpx.RequestError as e:
            raise ServiceUnavailableError(
                message=f"Could not connect to Anthropic API: {e}"
            )

        # Let httpx raise for HTTP errors so callers/tests receive HTTPStatusError
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError:
            # Re-raise HTTP errors as-is for proper error handling
            raise
        except Exception as e:
            if logger.isEnabledFor(logging.ERROR):
                logger.error(f"Unexpected error in Anthropic response handling: {e}")
            raise ServiceUnavailableError(f"Anthropic API error: {e}") from e

        data = response.json()
        converted_response = self.translation_service.to_domain_response(
            data, source_format="anthropic"
        )
        return ResponseEnvelope(
            content=converted_response.model_dump(),
            headers=dict(response.headers),
            status_code=response.status_code,
            usage=converted_response.usage,
            metadata={"allow_usage_recalculation": True},
        )

    # -----------------------------------------------------------
    # Streaming handling
    # -----------------------------------------------------------
    async def _handle_streaming_response(
        self, url: str, payload: dict[str, Any], headers: dict[str, str], model: str
    ) -> StreamingResponseHandle:
        """Handle a streaming response from Anthropic and provide cancellation support."""

        request_headers = ensure_loop_guard_header(headers)
        request = self.client.build_request(
            "POST", url, json=payload, headers=request_headers
        )
        try:
            response = await self.client.send(request, stream=True)
        except httpx.RequestError as e:
            raise ServiceUnavailableError(
                message=f"Could not connect to Anthropic API: {e}"
            )

        if response.status_code >= 400:
            from src.core.common.exceptions import BackendError

            try:
                # Read only first 10MB of error body to prevent DoS (consistent with other middleware)
                body_bytes = b""
                if hasattr(response, "aiter_bytes"):
                    async for chunk in response.aiter_bytes():
                        body_bytes += chunk
                        if (
                            len(body_bytes) > 10 * 1024 * 1024
                        ):  # 10MB limit (consistent with other middleware)
                            break
                elif hasattr(response, "aread"):
                    # Fallback
                    body_bytes = await response.aread()
                else:
                    body_bytes = b""

                body_text = body_bytes.decode("utf-8", errors="ignore")
                if logger.isEnabledFor(logging.ERROR):
                    logger.error(
                        f"Anthropic API error {response.status_code}: {body_text}"
                    )
            except (UnicodeDecodeError, httpx.ReadError) as e:
                logger.warning(f"Failed to read Anthropic error response body: {e}")
                body_text = ""
            finally:
                await response.aclose()

            raise BackendError(
                message=body_text,
                code="anthropic_error",
                status_code=response.status_code,
            )

        loop = asyncio.get_running_loop()
        message_id_future: asyncio.Future[str | None] = loop.create_future()
        cancel_lock = asyncio.Lock()
        cancel_state = {"called": False}
        cancel_headers = dict(request_headers)

        def _capture_message_id(chunk_text: str) -> None:
            if message_id_future.done():
                return

            try:
                data_segments: list[str] = []
                for line in chunk_text.splitlines():
                    if line.startswith("data:"):
                        value = line[5:].strip()
                        if value:
                            data_segments.append(value)
                if not data_segments:
                    stripped = chunk_text.strip()
                    if stripped:
                        data_segments.append(stripped)

                for segment in data_segments:
                    if segment in {"[DONE]", ""}:
                        continue
                    try:
                        payload_obj = json.loads(segment)
                    except json.JSONDecodeError:
                        continue

                    message_obj = payload_obj.get("message")
                    if isinstance(message_obj, dict):
                        message_id = message_obj.get("id")
                        if isinstance(message_id, str) and message_id:
                            message_id_future.set_result(message_id)
                            return

                    message_id = payload_obj.get("message_id") or payload_obj.get("id")
                    if isinstance(message_id, str) and message_id.startswith("msg_"):
                        message_id_future.set_result(message_id)
                        return
            except (json.JSONDecodeError, KeyError, AttributeError) as e:
                # Best effort capture; ignore expected parsing errors
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(f"Failed to parse message ID from chunk: {e}")
                return

        async def cancel_stream() -> None:
            async with cancel_lock:
                if cancel_state["called"]:
                    return
                cancel_state["called"] = True

            message_id: str | None
            if message_id_future.done():
                message_id = message_id_future.result()
            else:
                try:
                    message_id = await asyncio.wait_for(message_id_future, 0.5)
                except asyncio.TimeoutError:
                    message_id = None

            if message_id:
                cancel_url = f"{url.rstrip('/')}/{message_id}/cancel"
                try:
                    cancel_request = self.client.build_request(
                        "POST",
                        cancel_url,
                        headers=ensure_loop_guard_header(cancel_headers),
                    )
                except Exception as exc:
                    logger.debug(
                        "Failed to build Anthropic cancel request - url=%s error=%s",
                        cancel_url,
                        exc,
                        exc_info=True,
                    )
                else:
                    try:
                        cancel_response = await self.client.send(
                            cancel_request, stream=False
                        )
                    except Exception as exc:
                        logger.warning(
                            "Failed to send Anthropic cancel request - url=%s error=%s",
                            cancel_url,
                            exc,
                            exc_info=True,
                        )
                    else:
                        with contextlib.suppress(Exception):
                            await cancel_response.aclose()

            with contextlib.suppress(Exception):
                await response.aclose()

        async def event_stream() -> AsyncGenerator[ProcessedResponse, None]:
            try:
                async for chunk in response.aiter_text():
                    _capture_message_id(chunk)

                    # Log raw chunk for debugging
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(f"Raw Anthropic chunk: {chunk[:200]}")

                    # Check for error events from backend
                    if (
                        "event: error" in chunk
                        or '"type": "error"' in chunk
                        or '"type":"error"' in chunk
                    ):
                        # Extract error message
                        import json

                        try:
                            # Parse the data line
                            for line in chunk.split("\n"):
                                if line.startswith("data:"):
                                    error_data = json.loads(line[5:].strip())
                                    if error_data.get("type") == "error":
                                        error_info = error_data.get("error", {})
                                        error_msg = error_info.get(
                                            "message", "Unknown error"
                                        )
                                        error_type = error_info.get("type", "unknown")
                                        from src.core.common.exceptions import (
                                            BackendError,
                                        )

                                        raise BackendError(
                                            message=f"Anthropic API error: {error_msg}",
                                            code=f"anthropic_error_{error_type}",
                                            status_code=400,
                                            details={"error_data": error_data},
                                        )
                        except (json.JSONDecodeError, KeyError) as e:
                            if logger.isEnabledFor(logging.WARNING):
                                logger.warning(f"Failed to parse error event: {e}")

                    # Translate Anthropic SSE chunk to domain format
                    # The translation function handles both SSE format (with event:/data: lines)
                    # and plain JSON chunks
                    domain_chunk = self.translation_service.to_domain_stream_chunk(
                        chunk, "anthropic"
                    )
                    logger.debug(
                        f"Translated chunk delta: {domain_chunk.get('choices', [{}])[0].get('delta', {})}"
                    )
                    yield ProcessedResponse(content=domain_chunk)

                # Translate final [DONE] marker to domain format
                done_chunk = self.translation_service.to_domain_stream_chunk(
                    "data: [DONE]\n\n", "anthropic"
                )
                yield ProcessedResponse(content=done_chunk)
            except httpx.HTTPError as exc:
                raise ServiceUnavailableError(
                    message=f"Streaming connection interrupted ({exc})"
                ) from exc
            finally:
                if not message_id_future.done():
                    message_id_future.set_result(None)
                with contextlib.suppress(Exception):
                    await response.aclose()

        try:
            response_headers = dict(response.headers)
        except Exception:
            response_headers = {}

        return StreamingResponseHandle(
            iterator=event_stream(),
            cancel_callback=cancel_stream,
            headers=response_headers,
        )

    # -----------------------------------------------------------
    # Converters
    # Translation is now handled by TranslationService

    # -----------------------------------------------------------
    # Model listing
    # -----------------------------------------------------------
    async def list_models(
        self,
        *,
        base_url: str | None = None,
        key_name: str | None = None,
        api_key: str | None = None,
    ) -> ModelsListingResponse:
        # Allow callers to omit args and use initialized instance values
        base = (
            base_url
            or getattr(self, "anthropic_api_base_url", None)
            or ANTHROPIC_DEFAULT_BASE_URL
        )
        key = key_name or getattr(self, "key_name", None)
        key_api = api_key or getattr(self, "api_key", None)
        if not key or not key_api:
            raise AuthenticationError(
                message="Anthropic list_models missing credentials",
                code="missing_api_key",
            )

        url = f"{base.rstrip('/')}/models"
        headers = ensure_loop_guard_header(
            {
                self.auth_header_name: key_api,
                "anthropic-version": ANTHROPIC_VERSION_HEADER,
            }
        )
        try:
            response = await self.client.get(url, headers=headers)
        except httpx.RequestError as e:
            raise ServiceUnavailableError(
                message=f"Could not connect to Anthropic API: {e}"
            )

        if response.status_code >= 400:
            from src.core.common.exceptions import BackendError

            try:
                detail = response.json()
            except json.JSONDecodeError:
                detail = response.text

            raise BackendError(
                message=str(detail),
                code="anthropic_error",
                status_code=response.status_code,
            )

        result = response.json()
        raw_models = result.get("data", result.get("models", result))
        if not isinstance(raw_models, list):
            raw_models = [raw_models] if isinstance(raw_models, dict) else []

        model_infos = []
        for m in raw_models:
            if isinstance(m, dict):
                model_infos.append(
                    ModelInfo(
                        id=m.get("id") or m.get("name") or "",
                        name=m.get("name") or m.get("id"),
                        object="model",
                        created=m.get("created_at"),
                        owned_by="anthropic",
                    )
                )

        # Cache available_models for later calls
        self.available_models = [mi.id for mi in model_infos if mi.id]

        return ModelsListingResponse(object="list", data=model_infos)


    def _get_headers(
        self, identity: IAppIdentityConfig | None = None
    ) -> dict[str, str]:
        """Get headers for Anthropic API requests."""
        headers = {
            self.auth_header_name: self.api_key or "",
            "anthropic-version": ANTHROPIC_VERSION_HEADER,
            "content-type": "application/json",
        }
        if identity:
            headers.update(identity.get_resolved_headers(None))
        return headers

    async def _cancel_message(self, message_id: str) -> None:
        """Cancel an in-progress message."""
        base_url = (
            getattr(self, "anthropic_api_base_url", None) or ANTHROPIC_DEFAULT_BASE_URL
        )
        url = f"{base_url}/messages/{message_id}/cancel"
        headers = self._get_headers()

        try:
            await self.client.post(url, headers=headers)
        except Exception as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(f"Failed to cancel Anthropic message {message_id}: {e}")

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
        # Build the request URL and payload
        base_url = (
            getattr(self, "anthropic_api_base_url", None) or ANTHROPIC_DEFAULT_BASE_URL
        )
        url = f"{base_url}/messages"

        # Get headers
        headers = self._get_headers()
        request_headers = ensure_loop_guard_header(headers)

        # Prepare payload
        from typing import cast

        from src.core.domain.chat import CanonicalChatRequest

        if not isinstance(request, CanonicalChatRequest):
            request = cast(CanonicalChatRequest, request)

        # Get processed messages and effective model
        processed_messages = getattr(request, "messages", [])
        effective_model = getattr(request, "model", "claude-3-5-sonnet-20241022")

        project = getattr(request, "project", None)
        payload = self._prepare_anthropic_payload(
            request, processed_messages, effective_model, project
        )

        # Ensure streaming is enabled
        payload["stream"] = True

        # Build and send request
        http_request = self.client.build_request(
            "POST", url, json=payload, headers=request_headers
        )

        try:
            response = await self.client.send(http_request, stream=True)
        except httpx.RequestError as e:
            raise ServiceUnavailableError(
                message=f"Could not connect to Anthropic API: {e}"
            )

        # Check for errors before streaming
        if response.status_code >= 400:
            from src.core.common.exceptions import BackendError

            try:
                # Read only first 10MB of error body to prevent DoS (consistent with other middleware)
                body_bytes = b""
                if hasattr(response, "aiter_bytes"):
                    async for chunk in response.aiter_bytes():
                        body_bytes += chunk
                        if (
                            len(body_bytes) > 10 * 1024 * 1024
                        ):  # 10MB limit (consistent with other middleware)
                            break
                elif hasattr(response, "aread"):
                    # Fallback
                    body_bytes = await response.aread()
                else:
                    body_bytes = b""

                body_text = body_bytes.decode("utf-8", errors="ignore")

                if logger.isEnabledFor(logging.ERROR):
                    logger.error(
                        f"Anthropic API error {response.status_code}: {body_text}"
                    )
            except (UnicodeDecodeError, httpx.ReadError) as e:
                logger.warning(f"Failed to read Anthropic error response body: {e}")
                body_text = ""
            finally:
                await response.aclose()

            raise BackendError(
                message=body_text,
                code="anthropic_error",
                status_code=response.status_code,
            )

        # Stream SSE messages
        try:
            async for line in response.aiter_lines():
                if line:
                    # Yield raw SSE lines
                    yield line
        except httpx.RequestError as e:
            raise ServiceUnavailableError(
                message=f"Streaming connection interrupted: {e}"
            )
        finally:
            with contextlib.suppress(Exception):
                await response.aclose()

    def get_provider_name(self) -> str:
        """Return the provider name for logging/metrics.

        Returns:
            Provider name ("anthropic")
        """
        return "anthropic"


backend_registry.register_backend("anthropic", AnthropicBackend)
