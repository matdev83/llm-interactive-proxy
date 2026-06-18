"""
Anthropic backend connector - provides chat_completions and model discovery for the Anthropic Messages API.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncGenerator, Iterator
from typing import Any

import httpx

from src.connectors.base import LLMBackend, add_vendor_prefix, strip_vendor_prefix
from src.connectors.contracts import (
    ConnectorChatCompletionsRequest,
    ConnectorRequestContext,
)
from src.core.app.constants.logging_constants import TRACE_LEVEL
from src.core.common.capture_aware_httpx import (
    CaptureAwareAsyncClient,
    HttpxBoundaryCaptureContext,
)
from src.core.common.exceptions import (
    AuthenticationError,
    BackendError,
    ConfigurationError,
    InvalidRequestError,
    RateLimitExceededError,
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
from src.core.domain.responses_native_wiring import (
    RESPONSES_NATIVE_PROJECTED_PAYLOAD_KEY,
)
from src.core.interfaces.configuration_interface import IAppIdentityConfig
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.security.loop_prevention import ensure_loop_guard_header
from src.core.services.backend_registry import backend_registry
from src.core.services.translation_service import TranslationService

# Legacy ChatCompletionRequest removed from connector signatures; use domain ChatRequest

# API key redaction is handled by middleware.
# Command filtering is handled by the non-forwardable message tagging system.

logger = logging.getLogger(__name__)


ANTHROPIC_VERSION_HEADER = "2023-06-01"
ANTHROPIC_DEFAULT_BASE_URL = "https://api.anthropic.com/v1"

# Vendor prefix for Anthropic models in unified model naming convention
ANTHROPIC_VENDOR_PREFIX = "anthropic"
_NON_FORWARDABLE_EXTRA_BODY_KEYS = frozenset(
    {
        "session_id",
        "backend_type",
        "a_session_id",
        "b_session_id",
        "b_seq",
        "auth_scope_id",
        "client_session_id",
    }
)
_LLM_PROXY_REQUEST_ID_KEY = "_llm_proxy_request_id"
_LLM_PROXY_SESSION_ID_KEY = "_llm_proxy_session_id"
_LLM_PROXY_CLIENT_HOST_KEY = "_llm_proxy_client_host"


def _retry_after_metadata_from_httpx_headers(
    headers: Any,
) -> tuple[dict[str, Any], int | None]:
    """Extract Retry-After for resilience (same ``details['headers']`` shape as OpenAI).

    ``RateLimitErrorHandler`` reads ``details['headers']['retry-after']`` when
    ``reset_at`` is not a usable wall-clock hint, so we populate that structure here.
    """

    if not hasattr(headers, "get"):
        return {}, None

    retry_after_raw = headers.get("retry-after")
    if retry_after_raw is None:
        return {}, None

    retry_after = str(retry_after_raw).strip()
    if not retry_after:
        return {}, None

    details: dict[str, Any] = {"headers": {"retry-after": retry_after}}
    reset_hint: int | None = None
    with contextlib.suppress(ValueError, TypeError):
        reset_hint = int(retry_after.split(",", 1)[0].strip())
    return details, reset_hint


def _message_tool_calls(msg: Any) -> list[Any] | None:
    raw = (
        msg.get("tool_calls")
        if isinstance(msg, dict)
        else getattr(msg, "tool_calls", None)
    )
    if isinstance(raw, list) and raw:
        return raw
    return None


def _message_tool_call_id(msg: Any) -> str | None:
    raw = (
        msg.get("tool_call_id")
        if isinstance(msg, dict)
        else getattr(msg, "tool_call_id", None)
    )
    if raw is None:
        return None
    s = str(raw).strip()
    return s or None


def _tool_result_content_as_string(content: Any) -> str:
    if isinstance(content, str):
        return content
    if content is None:
        return ""
    if isinstance(content, list | dict):
        return json.dumps(content, ensure_ascii=False)
    return str(content)


def _anthropic_stream_error_status(error_type: str) -> int:
    normalized = error_type.strip().lower()
    mapping = {
        "invalid_request_error": 400,
        "authentication_error": 401,
        "permission_error": 403,
        "not_found_error": 404,
        "rate_limit_error": 429,
        "overloaded_error": 529,
    }
    return mapping.get(normalized, 500)


def _openai_tool_call_to_anthropic_tool_use(tc: Any) -> dict[str, Any]:
    if hasattr(tc, "model_dump"):
        tc = tc.model_dump()
    if not isinstance(tc, dict):
        return {"type": "tool_use", "id": "", "name": "", "input": {}}
    fn = tc.get("function")
    if not isinstance(fn, dict):
        fn = {}
    name = fn.get("name") or ""
    args_raw = fn.get("arguments")
    input_obj: Any
    if isinstance(args_raw, str):
        s = args_raw.strip()
        if not s:
            input_obj = {}
        else:
            try:
                input_obj = json.loads(s)
            except json.JSONDecodeError:
                input_obj = {"_raw_arguments": args_raw}
    elif isinstance(args_raw, dict):
        input_obj = args_raw
    else:
        input_obj = {}
    if not isinstance(input_obj, dict):
        input_obj = {"value": input_obj}
    tid = tc.get("id")
    return {
        "type": "tool_use",
        "id": str(tid) if tid is not None else "",
        "name": str(name) if name is not None else "",
        "input": input_obj,
    }


def _openai_list_content_to_anthropic_parts(
    content: list[Any], *, log_extra: dict[str, Any] | None = None
) -> list[Any]:
    """Convert OpenAI-style list content (parts) to Anthropic message content blocks."""

    parts: list[Any] = []
    for part in content:
        if isinstance(part, dict):
            part_obj = part.copy()
            part_type = part_obj.get("type")

            if part_type == "text" and "text" in part_obj:
                parts.append(part_obj)
            elif part_type == "image":
                source = part_obj.get("source", {})
                if source:
                    parts.append(part_obj)
            elif part_type == "image_url":
                image_url_data = part_obj.get("image_url", {})
                url = (
                    image_url_data.get("url", "")
                    if isinstance(image_url_data, dict)
                    else str(image_url_data)
                )
                if url.startswith("data:"):
                    try:
                        header, data = url.split(",", 1)
                        media_type = header.split(";")[0].replace("data:", "")
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
                        if logger.isEnabledFor(logging.WARNING):
                            logger.warning(
                                "Invalid data URI format: %s",
                                url[:50],
                                exc_info=True,
                                extra=log_extra if log_extra else None,
                            )
                elif url.startswith(("http://", "https://")):
                    parts.append(
                        {"type": "image", "source": {"type": "url", "url": url}}
                    )
            elif part_type == "document" or part_type in ("tool_use", "tool_result"):
                parts.append(part_obj)
            else:
                parts.append(part_obj)
        else:
            parts.append({"type": "text", "text": str(part)})
    return parts


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
        self._capture_http_client = CaptureAwareAsyncClient(client)
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
                    str(m.name or m.id) for m in data.data if m.name or m.id
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
    def _get_log_extra(self, context: ConnectorRequestContext | None) -> dict[str, str]:
        """Extract correlation identifiers from context for logging.

        Args:
            context: Connector request context, may be None

        Returns:
            Dictionary with request_id, session_id, client_host if available
        """
        log_extra: dict[str, str] = {}
        if context:
            if context.request_id:
                log_extra["request_id"] = context.request_id
            if context.session_id:
                log_extra["session_id"] = context.session_id
            if context.client_host:
                log_extra["client_host"] = context.client_host
        return log_extra

    def _http_boundary_capture(
        self,
        *,
        model: str,
        context: ConnectorRequestContext | None,
        key_name: str | None = None,
    ) -> HttpxBoundaryCaptureContext:
        return HttpxBoundaryCaptureContext(
            backend=self.backend_type,
            model=model,
            key_name=self.backend_type if key_name is None else key_name,
            context=context,
        )

    async def _chat_completions_canonical(
        self, request: ConnectorChatCompletionsRequest
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Canonical connector API implementation.

        Extracts fields from ConnectorChatCompletionsRequest and delegates
        to the existing implementation logic.

        Uses request.context for logging correlation identifiers (request_id,
        session_id, client_host) when available.
        """
        # Extract fields from canonical request
        domain_request = request.request
        processed_messages = list(request.processed_messages)
        effective_model = request.effective_model
        identity = request.identity
        cancellation_token = request.cancellation_token
        cancellation_coordinator = request.cancellation_coordinator
        context = request.context

        # Extract provider-specific options from request.options (JSON-safe)
        options = request.options
        openrouter_api_base_url = options.get("openrouter_api_base_url")
        if not isinstance(openrouter_api_base_url, str):
            openrouter_api_base_url = None

        key_name = options.get("key_name")
        if not isinstance(key_name, str):
            key_name = None

        api_key = options.get("api_key")
        if not isinstance(api_key, str):
            api_key = None

        project = options.get("project")
        if not isinstance(project, str):
            project = None

        agent = options.get("agent")
        if not isinstance(agent, str):
            agent = None

        headers = options.get("headers")
        if isinstance(headers, dict):
            headers = {str(k): str(v) for k, v in headers.items()}
        else:
            headers = None

        # Structural enforcement: check cancellation immediately if coordinator and token provided
        if cancellation_coordinator is not None and cancellation_token is not None:
            cancellation_coordinator.ensure_not_cancelled(cancellation_token)

        # Continue with existing implementation logic
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
        # request_headers = ... (existing code)

        extra_body_for_native = domain_request.extra_body or {}
        native_anthropic_payload = extra_body_for_native.get(
            RESPONSES_NATIVE_PROJECTED_PAYLOAD_KEY
        )
        if isinstance(native_anthropic_payload, dict):
            anthropic_payload = dict(native_anthropic_payload)
            anthropic_payload["model"] = effective_model.replace("anthropic:", "")
            anthropic_payload["stream"] = bool(domain_request.stream)
        else:
            anthropic_payload = self._prepare_anthropic_payload(
                request_data=domain_request,
                processed_messages=processed_messages,
                effective_model=effective_model,
                project=project,
                context=context,
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

        # Use context for correlation identifiers in logs
        context = request.context
        log_extra = self._get_log_extra(context)

        logger.info(
            "Forwarding to Anthropic. Model: %s Stream: %s%s",
            effective_model,
            domain_request.stream,
            f" {log_extra}" if log_extra else "",
            extra=log_extra if log_extra else None,
        )
        if logger.isEnabledFor(TRACE_LEVEL):
            logger.log(
                TRACE_LEVEL,
                "Anthropic payload: %s",
                json.dumps(anthropic_payload, indent=2),
                extra=log_extra if log_extra else None,
            )

        if domain_request.stream:
            if isinstance(native_anthropic_payload, dict):
                stream_handle = await self._handle_streaming_response(
                    url,
                    anthropic_payload,
                    request_headers,
                    effective_model,
                    context,
                    yield_native_json_events=True,
                )
                return StreamingResponseEnvelope(
                    content=stream_handle.iterator,
                    media_type="text/event-stream",
                    headers=stream_handle.headers or {},
                    cancel_callback=stream_handle.cancel_callback,
                )
            try:
                raw_stream = self.stream_completion(domain_request)

                prompt_tokens = 0
                try:
                    from src.core.utils.token_count import (
                        count_tokens,
                        extract_prompt_text,
                    )

                    prompt_text = extract_prompt_text(processed_messages)
                    prompt_tokens = count_tokens(prompt_text, model=effective_model)
                except (
                    ImportError,
                    AttributeError,
                    TypeError,
                    KeyError,
                    ValueError,
                ) as e:
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning(
                            "Failed to calculate prompt tokens: %s",
                            e,
                            exc_info=True,
                            extra=log_extra if log_extra else None,
                        )
                except Exception as e:
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning(
                            "Failed to calculate prompt tokens (unexpected error): %s",
                            e,
                            exc_info=True,
                            extra=log_extra if log_extra else None,
                        )

                from src.core.ports.streaming_integration import (
                    integrate_streaming_pipeline,
                )

                return await integrate_streaming_pipeline(
                    raw_stream=raw_stream,
                    provider=self.get_provider_name(),
                    stream_id=getattr(domain_request, "session_id", None),
                    enable_tool_call_repair=True,
                    enable_think_tags=True,
                    prompt_tokens=prompt_tokens,
                    model_name=effective_model,
                    vtc_enabled=getattr(domain_request, "vtc_enabled", False) or False,
                    yield_interval=self.config.streaming_yield_interval,
                    domain_request=domain_request,
                )
            except AuthenticationError:
                raise
        else:
            response_envelope = await self._handle_non_streaming_response(
                url, anthropic_payload, request_headers, domain_request.model, context
            )
            # Return a domain-level ResponseEnvelope
            return response_envelope

    async def chat_completions(  # type: ignore[override]
        self, request: ConnectorChatCompletionsRequest
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Invoke Anthropic chat completions using ``ConnectorChatCompletionsRequest`` only.

        Implements :class:`ICanonicalChatCompletionsBackend`. The proxy invokes backends
        through :class:`ConnectorChatCompletionsRequest`; legacy positional call shapes
        are not supported at this boundary.
        """
        if not isinstance(request, ConnectorChatCompletionsRequest):  # type: ignore[unreachable]
            raise InvalidRequestError(
                message=(
                    f"chat_completions requires ConnectorChatCompletionsRequest, "
                    f"got {type(request).__name__}"
                ),
                details={"connector": "anthropic"},
            )
        return await self._chat_completions_canonical(request)

    # -----------------------------------------------------------
    # Payload helpers
    # -----------------------------------------------------------
    def _prepare_anthropic_payload(
        self,
        request_data: ChatRequest,
        processed_messages: list[Any],
        effective_model: str,
        project: str | None,
        context: ConnectorRequestContext | None = None,
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
                    log_extra_payload = (
                        self._get_log_extra(context) if context else None
                    )
                    logger.debug(
                        "Skipping message without role: %r",
                        msg,
                        extra=log_extra_payload if log_extra_payload else None,
                    )
                continue

            if role == "system":
                if isinstance(content, str):
                    system_prompt = content
                else:
                    # If list/parts, flatten to string for system
                    system_prompt = json.dumps(content)
                continue

            log_extra_payload = self._get_log_extra(context) if context else None

            if role == "tool":
                tcid = _message_tool_call_id(msg)
                anth_messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": tcid or "",
                                "content": _tool_result_content_as_string(content),
                            }
                        ],
                    }
                )
                continue

            if role == "assistant":
                tc_list = _message_tool_calls(msg)
                if tc_list:
                    asst_parts: list[Any] = []
                    if isinstance(content, list):
                        asst_parts.extend(
                            _openai_list_content_to_anthropic_parts(
                                content, log_extra=log_extra_payload
                            )
                        )
                    elif isinstance(content, str) and content.strip():
                        asst_parts.append({"type": "text", "text": content})
                    elif content is not None:
                        asst_parts.append({"type": "text", "text": str(content)})
                    for tc in tc_list:
                        asst_parts.append(_openai_tool_call_to_anthropic_tool_use(tc))
                    anth_messages.append({"role": "assistant", "content": asst_parts})
                    continue

            # Map content - content is already processed by middleware
            if isinstance(content, str):
                anth_messages.append({"role": role, "content": content})
            elif isinstance(content, list):
                parts = _openai_list_content_to_anthropic_parts(
                    content, log_extra=log_extra_payload
                )
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
        log_extra = self._get_log_extra(context)
        if request_data.seed is not None and logger.isEnabledFor(logging.WARNING):
            logger.warning(
                "AnthropicBackend does not support the 'seed' parameter.",
                extra=log_extra if log_extra else None,
            )
        if request_data.presence_penalty is not None and logger.isEnabledFor(
            logging.WARNING
        ):
            logger.warning(
                "AnthropicBackend does not support the 'presence_penalty' parameter.",
                extra=log_extra if log_extra else None,
            )
        if request_data.frequency_penalty is not None and logger.isEnabledFor(
            logging.WARNING
        ):
            logger.warning(
                "AnthropicBackend does not support the 'frequency_penalty' parameter.",
                extra=log_extra if log_extra else None,
            )
        if request_data.logit_bias is not None and logger.isEnabledFor(logging.WARNING):
            logger.warning(
                "AnthropicBackend does not support the 'logit_bias' parameter.",
                extra=log_extra if log_extra else None,
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
        filtered_extra_body = {
            k: v
            for k, v in extra_body.items()
            if v is not None and k not in _NON_FORWARDABLE_EXTRA_BODY_KEYS
        }
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
        self,
        url: str,
        payload: dict,
        headers: dict,
        original_model: str,
        context: ConnectorRequestContext | None = None,
    ) -> ResponseEnvelope:
        headers = ensure_loop_guard_header(headers)
        log_extra = self._get_log_extra(context)
        request = self.client.build_request("POST", url, json=payload, headers=headers)
        try:
            if logger.isEnabledFor(logging.INFO):
                logger.info(
                    f"Sending request to {url} with headers: {headers} and payload: {payload}",
                    extra=log_extra if log_extra else None,
                )
            response = await self._capture_http_client.send(
                request,
                stream=False,
                capture=self._http_boundary_capture(
                    model=str(original_model), context=context
                ),
            )
        except httpx.RequestError as e:
            raise ServiceUnavailableError(
                message=f"Could not connect to Anthropic API: {e}"
            ) from e

        # Let httpx raise for HTTP errors so callers/tests receive HTTPStatusError
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError:
            # Re-raise HTTP errors as-is for proper error handling
            raise
        except Exception as e:
            if logger.isEnabledFor(logging.ERROR):
                logger.error(
                    "Unexpected error in Anthropic response handling: %s",
                    e,
                    exc_info=True,
                    extra=log_extra if log_extra else None,
                )
            raise ServiceUnavailableError(f"Anthropic API error: {e}") from e

        data = response.json()
        converted_response = self.translation_service.to_domain_response(
            data, source_format="anthropic"
        )
        try:
            response_headers = dict(response.headers)
        except Exception:
            try:
                response_headers = dict(getattr(response, "headers", {}) or {})
            except Exception:
                response_headers = {}
        return ResponseEnvelope(
            content=converted_response.model_dump(),
            headers=response_headers,
            status_code=response.status_code,
            usage=converted_response.usage,
            metadata={"allow_usage_recalculation": True},
        )

    def _iter_native_sse_json_events(self, chunk: str) -> Iterator[ProcessedResponse]:
        for line in chunk.splitlines():
            line_s = line.strip()
            if not line_s.startswith("data:"):
                continue
            data_part = line_s[5:].strip()
            if not data_part or data_part == "[DONE]":
                continue
            try:
                obj = json.loads(data_part)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                if obj.get("type") == "error":
                    error_info = obj.get("error", {})
                    error_msg = (
                        error_info.get("message", "Unknown error")
                        if isinstance(error_info, dict)
                        else "Unknown error"
                    )
                    error_type = (
                        error_info.get("type", "unknown")
                        if isinstance(error_info, dict)
                        else "unknown"
                    )
                    raise BackendError(
                        message=f"Anthropic API error: {error_msg}",
                        code=f"anthropic_error_{error_type}",
                        status_code=_anthropic_stream_error_status(error_type),
                        details={"error_data": obj},
                    )
                yield ProcessedResponse(content=obj)

    # -----------------------------------------------------------
    # Streaming handling
    # -----------------------------------------------------------
    async def _handle_streaming_response(  # noqa: C901
        self,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str],
        model: str,
        context: ConnectorRequestContext | None = None,
        *,
        yield_native_json_events: bool = False,
    ) -> StreamingResponseHandle:
        """Handle a streaming response from Anthropic and provide cancellation support."""

        log_extra = self._get_log_extra(context)
        request_headers = ensure_loop_guard_header(headers)
        request = self.client.build_request(
            "POST", url, json=payload, headers=request_headers
        )
        try:
            response = await self._capture_http_client.send(
                request,
                stream=True,
                capture=self._http_boundary_capture(model=str(model), context=context),
            )
        except httpx.RequestError as e:
            raise ServiceUnavailableError(
                message=f"Could not connect to Anthropic API: {e}"
            ) from e

        if response.status_code >= 400:
            try:
                # Read only first 10MB of error body to prevent DoS (consistent with other middleware)
                # Use list + join to avoid O(n^2) bytes concatenation
                body_chunks: list[bytes] = []
                total_len = 0
                if hasattr(response, "aiter_bytes"):
                    async for chunk in response.aiter_bytes():
                        body_chunks.append(chunk)
                        total_len += len(chunk)
                        if (
                            total_len > 10 * 1024 * 1024
                        ):  # 10MB limit (consistent with other middleware)
                            break
                    body_bytes = b"".join(body_chunks)
                elif hasattr(response, "aread"):
                    # Fallback
                    body_bytes = await response.aread()
                else:
                    body_bytes = b""

                body_text = body_bytes.decode("utf-8", errors="ignore")
                if logger.isEnabledFor(logging.ERROR):
                    logger.error(
                        "Anthropic API error %s: %s",
                        response.status_code,
                        body_text,
                        extra=log_extra if log_extra else None,
                    )
            except (UnicodeDecodeError, httpx.ReadError) as e:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Failed to read Anthropic error response body: %s",
                        e,
                        exc_info=True,
                        extra=log_extra if log_extra else None,
                    )
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
        cancel_model = str(model)

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
                    logger.debug(
                        "Failed to parse message ID from chunk: %s",
                        e,
                        extra=log_extra if log_extra else None,
                    )
                return

        async def cancel_stream() -> None:
            async with cancel_lock:
                if cancel_state["called"]:
                    return
                cancel_state["called"] = True

            logger.debug(
                "upstream_stream_cancel_requested backend=%s model=%s method=protocol_cancel_then_close",
                "anthropic",
                cancel_model,
                extra=log_extra if log_extra else None,
            )

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
                logger.debug(
                    "upstream_protocol_cancel_requested backend=%s model=%s message_id=%s",
                    "anthropic",
                    cancel_model,
                    message_id,
                    extra=log_extra if log_extra else None,
                )
                try:
                    cancel_request = self.client.build_request(
                        "POST",
                        cancel_url,
                        headers=ensure_loop_guard_header(cancel_headers),
                    )
                except Exception as exc:
                    logger.debug(
                        "upstream_protocol_cancel_failed backend=%s model=%s message_id=%s error=%s",
                        "anthropic",
                        cancel_model,
                        message_id,
                        exc,
                        extra=log_extra if log_extra else None,
                    )
                else:
                    try:
                        cancel_response = await self._capture_http_client.send(
                            cancel_request,
                            stream=False,
                            capture=self._http_boundary_capture(
                                model="anthropic-cancel", context=context
                            ),
                        )
                    except Exception as exc:
                        logger.warning(
                            "upstream_protocol_cancel_failed backend=%s model=%s message_id=%s error=%s",
                            "anthropic",
                            cancel_model,
                            message_id,
                            exc,
                            extra=log_extra if log_extra else None,
                        )
                    else:
                        with contextlib.suppress(Exception):
                            await cancel_response.aclose()
                        logger.debug(
                            "upstream_protocol_cancel_completed backend=%s model=%s message_id=%s",
                            "anthropic",
                            cancel_model,
                            message_id,
                            extra=log_extra if log_extra else None,
                        )
            else:
                logger.debug(
                    "upstream_protocol_cancel_skipped backend=%s model=%s reason=message_id_unavailable",
                    "anthropic",
                    cancel_model,
                    extra=log_extra if log_extra else None,
                )

            try:
                await response.aclose()
            except Exception as exc:
                logger.debug(
                    "upstream_stream_close_failed backend=%s model=%s error=%s",
                    "anthropic",
                    cancel_model,
                    exc,
                    extra=log_extra if log_extra else None,
                )
            else:
                logger.debug(
                    "upstream_stream_close_completed backend=%s model=%s",
                    "anthropic",
                    cancel_model,
                    extra=log_extra if log_extra else None,
                )

        async def event_stream() -> AsyncGenerator[ProcessedResponse, None]:
            try:
                async for chunk in response.aiter_text():
                    _capture_message_id(chunk)

                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Raw Anthropic chunk: %s",
                            chunk[:200],
                            extra=log_extra if log_extra else None,
                        )

                    if yield_native_json_events:
                        for pr in self._iter_native_sse_json_events(chunk):
                            yield pr
                        continue

                    if (
                        "event: error" in chunk
                        or '"type": "error"' in chunk
                        or '"type":"error"' in chunk
                    ):
                        try:
                            for line in chunk.split("\n"):
                                if line.startswith("data:"):
                                    error_data = json.loads(line[5:].strip())
                                    if error_data.get("type") == "error":
                                        error_info = error_data.get("error", {})
                                        error_msg = error_info.get(
                                            "message", "Unknown error"
                                        )
                                        error_type = error_info.get("type", "unknown")

                                        raise BackendError(
                                            message=f"Anthropic API error: {error_msg}",
                                            code=f"anthropic_error_{error_type}",
                                            status_code=_anthropic_stream_error_status(
                                                error_type
                                            ),
                                            details={"error_data": error_data},
                                        )
                        except (json.JSONDecodeError, KeyError) as e:
                            if logger.isEnabledFor(logging.WARNING):
                                logger.warning(
                                    "Failed to parse error event: %s",
                                    e,
                                    exc_info=True,
                                    extra=log_extra if log_extra else None,
                                )

                    domain_chunk = self.translation_service.to_domain_stream_chunk(
                        chunk, "anthropic"
                    )
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Translated chunk delta: %s",
                            domain_chunk.get("choices", [{}])[0].get("delta", {}),
                            extra=log_extra if log_extra else None,
                        )
                    yield ProcessedResponse(content=domain_chunk)

                if not yield_native_json_events:
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
        except (TypeError, AttributeError) as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Failed to convert response.headers to dict: %s",
                    e,
                    exc_info=True,
                    extra=log_extra if log_extra else None,
                )
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
            ) from e

        if response.status_code >= 400:
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
        """Cancel an in-progress message.

        Note: This method appears to be unused. Cancellation is handled by
        the cancel_stream callback in _handle_streaming_response, which has
        access to context via closure. If this method is ever called, it
        would benefit from receiving ConnectorRequestContext for logging
        correlation, but currently it's not part of the canonical API path.
        """
        base_url = (
            getattr(self, "anthropic_api_base_url", None) or ANTHROPIC_DEFAULT_BASE_URL
        )
        url = f"{base_url}/messages/{message_id}/cancel"
        headers = self._get_headers()

        try:
            await self.client.post(url, headers=headers)
        except Exception as e:
            if logger.isEnabledFor(logging.WARNING):
                # Note: This method doesn't receive context (appears unused).
                # If called, cancellation logs cannot be correlated with request/session.
                logger.warning(
                    "Failed to cancel Anthropic message %s: %s",
                    message_id,
                    e,
                    exc_info=True,
                )

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

        # request is expected to be CanonicalChatRequest from StreamProducer protocol
        extra_body = getattr(request, "extra_body", None) or {}
        connector_context: ConnectorRequestContext | None = None
        if isinstance(extra_body, dict):
            proxy_request_id = extra_body.get(_LLM_PROXY_REQUEST_ID_KEY)
            if isinstance(proxy_request_id, str) and proxy_request_id:
                proxy_session_id = extra_body.get(_LLM_PROXY_SESSION_ID_KEY)
                proxy_client_host = extra_body.get(_LLM_PROXY_CLIENT_HOST_KEY)
                connector_context = ConnectorRequestContext(
                    request_id=proxy_request_id,
                    session_id=(
                        proxy_session_id
                        if isinstance(proxy_session_id, str) and proxy_session_id
                        else None
                    ),
                    client_host=(
                        proxy_client_host
                        if isinstance(proxy_client_host, str) and proxy_client_host
                        else None
                    ),
                    extensions={},
                )
        if connector_context is None:
            fallback_session = getattr(request, "session_id", None)
            if isinstance(fallback_session, str) and fallback_session:
                connector_context = ConnectorRequestContext(
                    request_id=fallback_session,
                    session_id=fallback_session,
                    client_host=None,
                    extensions={},
                )

        # Get processed messages and effective model
        processed_messages = getattr(request, "messages", [])
        effective_model = getattr(request, "model", "claude-3-5-sonnet-20241022")

        project = getattr(request, "project", None)
        # Note: stream_completion doesn't have context access (protocol method)
        payload = self._prepare_anthropic_payload(
            request, processed_messages, effective_model, project, context=None
        )

        # Ensure streaming is enabled
        payload["stream"] = True

        # Build and send request
        http_request = self.client.build_request(
            "POST", url, json=payload, headers=request_headers
        )

        try:
            response = await self._capture_http_client.send(
                http_request,
                stream=True,
                capture=self._http_boundary_capture(
                    model=str(effective_model), context=connector_context
                ),
            )
        except httpx.RequestError as e:
            raise ServiceUnavailableError(
                message=f"Could not connect to Anthropic API: {e}"
            ) from e

        # Check for errors before streaming
        if response.status_code >= 400:
            status_code = response.status_code
            rate_limit_details, retry_after_seconds = (
                _retry_after_metadata_from_httpx_headers(response.headers)
            )

            try:
                # Read only first 10MB of error body to prevent DoS (consistent with other middleware)
                # Use list + join to avoid O(n^2) bytes concatenation
                body_chunks: list[bytes] = []
                total_len = 0
                if hasattr(response, "aiter_bytes"):
                    async for chunk in response.aiter_bytes():
                        body_chunks.append(chunk)
                        total_len += len(chunk)
                        if (
                            total_len > 10 * 1024 * 1024
                        ):  # 10MB limit (consistent with other middleware)
                            break
                    body_bytes = b"".join(body_chunks)
                elif hasattr(response, "aread"):
                    # Fallback
                    body_bytes = await response.aread()
                else:
                    body_bytes = b""

                body_text = body_bytes.decode("utf-8", errors="ignore")

                # Operational HTTP errors: never use exc_info=True here — under concurrent
                # asyncio work, sys.exc_info() can belong to another task and produces a
                # misleading traceback on this log line.
                preview = (
                    (body_text[:500] + "...") if len(body_text) > 500 else body_text
                )
                if status_code == 429:
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning(
                            "Anthropic API rate limited (HTTP 429): %s",
                            preview or "(empty body)",
                        )
                elif 400 <= status_code < 500:
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning(
                            "Anthropic API client error %s: %s",
                            status_code,
                            preview or "(empty body)",
                        )
                elif logger.isEnabledFor(logging.ERROR):
                    logger.error(
                        "Anthropic API server error %s: %s",
                        status_code,
                        preview or "(empty body)",
                    )
            except (UnicodeDecodeError, httpx.ReadError) as e:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Failed to read Anthropic error response body: %s",
                        e,
                        exc_info=True,
                    )
                body_text = ""
            finally:
                await response.aclose()

            if status_code == 429:
                raise RateLimitExceededError(
                    message=body_text or "Anthropic rate limit exceeded",
                    details=rate_limit_details,
                    reset_at=retry_after_seconds,
                )
            raise BackendError(
                message=body_text, code="anthropic_error", status_code=status_code
            )
        # Stream SSE messages
        try:
            async for line in response.aiter_lines():
                if line:
                    # Yield raw SSE lines
                    yield line
        except httpx.RequestError as e:
            raise ServiceUnavailableError(
                message=f"Could not connect to Anthropic API: {e}"
            ) from e
        finally:
            with contextlib.suppress(BaseException):
                await response.aclose()

    def get_provider_name(self) -> str:
        """Return the provider name for logging/metrics.

        Returns:
            Provider name ("anthropic")
        """
        return "anthropic"


backend_registry.register_backend("anthropic", AnthropicBackend)
