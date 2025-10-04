"""
Anthropic backend connector - provides chat_completions and model discovery for the Anthropic Messages API.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from typing import Any, cast

import httpx

from src.connectors.base import LLMBackend
from src.core.common.exceptions import (
    AuthenticationError,
    ConfigurationError,
    ServiceUnavailableError,
)
from src.core.config.app_config import AppConfig
from src.core.domain.chat import ChatRequest
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
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


class AnthropicBackend(LLMBackend):
    """LLMBackend implementation for Anthropic's Messages API."""

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
        """Return cached Anthropic model names. For immediate use, prefer async version."""
        return list(self.available_models)

    async def get_available_models_async(self) -> list[str]:
        """Return Anthropic model names, fetching them if not cached."""
        await self._ensure_models_loaded()
        return list(self.available_models)

    # -----------------------------------------------------------
    # Core entry - called by proxy
    # -----------------------------------------------------------
    async def chat_completions(  # type: ignore[override]
        self,
        request_data: DomainModel | InternalDTO | dict[str, Any],
        processed_messages: list,
        effective_model: str,
        identity: IAppIdentityConfig | None = None,
        openrouter_api_base_url: str | None = None,
        openrouter_headers_provider: Callable[[str, str], dict[str, str]] | None = None,
        key_name: str | None = None,
        api_key: str | None = None,
        project: str | None = None,
        agent: str | None = None,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Send request to Anthropic Messages endpoint and return domain response envelope."""
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

        request_headers = headers or {
            self.auth_header_name: effective_api_key,
            "anthropic-version": ANTHROPIC_VERSION_HEADER,
            "content-type": "application/json",
        }
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
            stream_iterator = await self._handle_streaming_response(
                url, anthropic_payload, request_headers, effective_model
            )
            # Return a domain-level streaming envelope
            return StreamingResponseEnvelope(
                content=stream_iterator, media_type="text/event-stream", headers={}
            )
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
            "max_tokens": request_data.max_tokens or 1024,
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
            if msg.role == "system":
                if isinstance(msg.content, str):
                    system_prompt = msg.content
                else:
                    # If list/parts, flatten to string for system
                    system_prompt = json.dumps(msg.content)
                continue

            # Map content - content is already processed by middleware
            content = msg.content
            if isinstance(content, str):
                anth_messages.append({"role": msg.role, "content": content})
            else:
                # For list-of-parts, Anthropic only supports string or array of dict {"type":"text","text":...}
                parts: list[Any] = []
                for part in content:
                    if isinstance(part, dict):
                        # assume already valid
                        part_obj = part.copy()
                        if part_obj.get("type") == "text" and "text" in part_obj:
                            # Text content is already processed by middleware
                            pass
                        parts.append(part_obj)
                    else:
                        # unknown part type -> stringify
                        parts.append({"type": "text", "text": str(part)})
                anth_messages.append({"role": msg.role, "content": parts})

        payload["messages"] = anth_messages
        if system_prompt:
            payload["system"] = system_prompt
        if request_data.temperature is not None:
            payload["temperature"] = request_data.temperature
        if request_data.top_p is not None:
            payload["top_p"] = request_data.top_p
        if request_data.stop is not None:
            payload["stop_sequences"] = request_data.stop
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

        # Include extra params from domain extra_body directly (allows reasoning, etc.)
        payload.update(extra_body)

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
            if logger.isEnabledFor(logging.INFO):
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
        except Exception:
            # Re-raise to preserve httpx.HTTPStatusError
            raise

        data = response.json()
        converted_response = self.translation_service.to_domain_response(
            data, source_format="anthropic"
        )
        return ResponseEnvelope(
            content=converted_response,
            headers=dict(response.headers),
            status_code=response.status_code,
        )

    # -----------------------------------------------------------
    # Streaming handling
    # -----------------------------------------------------------
    async def _handle_streaming_response(
        self, url: str, payload: dict, headers: dict, model: str
    ) -> AsyncIterator[ProcessedResponse]:
        """Handle a streaming response from Anthropic and return an async iterator of ProcessedResponse objects."""
        headers = ensure_loop_guard_header(headers)
        request = self.client.build_request("POST", url, json=payload, headers=headers)
        try:
            response = await self.client.send(request, stream=True)
        except httpx.RequestError as e:
            raise ServiceUnavailableError(
                message=f"Could not connect to Anthropic API: {e}"
            )

        if response.status_code >= 400:
            from src.core.common.exceptions import BackendError

            try:
                body_text = (await response.aread()).decode("utf-8")
            except Exception:
                body_text = ""
            finally:
                await response.aclose()

            raise BackendError(
                message=body_text,
                code="anthropic_error",
                status_code=response.status_code,
            )

        async def event_stream() -> AsyncGenerator[ProcessedResponse, None]:
            # Forward raw text stream; central pipeline will handle normalization/repairs
            processed_stream = response.aiter_text()

            async for chunk in processed_stream:
                # If JSON repair is enabled centrally, the pipeline yields repaired content.
                # We need to ensure it's properly formatted as SSE.
                if chunk.startswith(("data: ", "id: ", ":")):
                    # Already SSE formatted or a comment, yield directly
                    yield ProcessedResponse(content=chunk)
                else:
                    # Assume it's a raw text chunk (either repaired JSON or non-JSON text)
                    # and format it as an SSE data event.
                    yield ProcessedResponse(content=f"data: {chunk}\n\n")

            yield ProcessedResponse(content="data: [DONE]\n\n")
            await response.aclose()

        return event_stream()

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
    ) -> list[dict[str, Any]]:
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
        models = result.get("models", result)
        # Cache available_models for later calls
        try:
            self.available_models = [
                m.get("name") or m.get("id") or ""
                for m in models
                if isinstance(m, dict)
            ]
        except Exception:
            self.available_models = []
        return cast(list[dict[str, Any]], models)


backend_registry.register_backend("anthropic", AnthropicBackend)
