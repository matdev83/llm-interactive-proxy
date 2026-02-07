"""
InternLM connector for InternLM AI models via OpenAI-compatible API.

InternLM's API does not reliably support SSE streaming. This connector
forces all backend requests to use non-streaming mode and, when the
client originally requested streaming, synthesises an OpenAI-compatible
SSE stream from the complete response so that downstream middleware and
clients receive the expected ``text/event-stream`` format.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

import httpx

from src.connectors.contracts import ConnectorChatCompletionsRequest
from src.core.config.app_config import AppConfig
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.backend_registry import backend_registry

from .openai import OpenAIConnector

if TYPE_CHECKING:
    from src.core.services.translation_service import TranslationService


logger = logging.getLogger(__name__)


class InternLMConnector(OpenAIConnector):
    """InternLM backend connector for InternLM AI models."""

    backend_type: str = "internlm"

    # Vendor prefix for InternLM models in unified model routing
    VENDOR_PREFIX: str | None = "internlm"

    def __init__(
        self,
        client: httpx.AsyncClient,
        config: AppConfig,
        translation_service: TranslationService | None = None,
    ) -> None:
        super().__init__(client, config, translation_service=translation_service)
        self.api_base_url = "https://chat.intern-ai.org.cn/api/v1"
        self.name = "internlm"

        # Multiple API keys support
        self.api_keys: list[str] = []
        self._current_key_index: int = 0

        # InternLM API may not expose a /models listing endpoint; skip health checks
        self.disable_health_check()

    def get_headers(self, identity: Any = None) -> dict[str, str]:
        """Return request headers including API key from rotation."""
        headers: dict[str, str] = {}

        # Use current key from rotation if available, otherwise fall back to single api_key
        current_key = self._get_current_api_key()
        if current_key:
            headers["Authorization"] = f"Bearer {current_key}"

        # Handle identity headers from parent class
        if identity is not None:
            try:
                identity_headers = identity.get_resolved_headers(None)
            except (KeyError, TypeError, AttributeError) as e:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Failed to get identity headers, using empty headers: %s",
                        e,
                        exc_info=True,
                    )
                identity_headers = {}
            else:
                identity_headers = dict(identity_headers)
            if identity_headers:
                headers.update(identity_headers)

        # Ensure loop guard header from parent
        from src.core.security.loop_prevention import ensure_loop_guard_header

        return ensure_loop_guard_header(headers)

    def _get_current_api_key(self) -> str | None:
        """Get the current API key from rotation."""
        if self.api_keys:
            key = self.api_keys[self._current_key_index]
            # Advance index for next request (round-robin)
            self._current_key_index = (self._current_key_index + 1) % len(self.api_keys)
            return key
        return self.api_key

    def _rotate_to_next_key(self) -> None:
        """Rotate to the next API key (useful for failover)."""
        if self.api_keys and len(self.api_keys) > 1:
            self._current_key_index = (self._current_key_index + 1) % len(self.api_keys)
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Rotated to API key index %d (total keys: %d)",
                    self._current_key_index,
                    len(self.api_keys),
                )

    async def initialize(self, **kwargs: Any) -> None:
        """Initialize the connector with API key(s) and optional base URL."""
        # Collect API keys from kwargs
        api_key = kwargs.get("api_key")
        api_keys = kwargs.get("api_keys", [])

        # Build list of API keys: primary + numbered variants
        all_keys: list[str] = []
        if api_key:
            all_keys.append(api_key)
        if api_keys:
            if isinstance(api_keys, list):
                all_keys.extend([k for k in api_keys if k and k not in all_keys])
            elif isinstance(api_keys, str):
                # Handle comma-separated string
                all_keys.extend(
                    [
                        k.strip()
                        for k in api_keys.split(",")
                        if k.strip() and k.strip() not in all_keys
                    ]
                )

        # Set primary api_key for backward compatibility
        self.api_key = all_keys[0] if all_keys else None
        # Set list for rotation
        self.api_keys = all_keys
        self._current_key_index = 0

        if "api_base_url" in kwargs:
            self.api_base_url = kwargs["api_base_url"]

        logger.info(
            "InternLMConnector initialize called. api_key_provided=%s, total_keys=%d",
            "yes" if self.api_key else "no",
            len(self.api_keys),
        )

        # The InternLM API may not provide a model listing endpoint.
        # Avoid calling the base implementation which would log spurious warnings.
        if self.api_key and logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Skipping InternLM model discovery (endpoint may not be supported by provider)"
            )
        self.available_models = []

    async def _prepare_payload(
        self,
        request_data: Any,
        processed_messages: list[Any],
        effective_model: str,
        context: Any = None,
    ) -> dict[str, Any]:
        """Prepare payload, stripping vendor prefix from model name and enabling deep thinking mode.

        Always forces ``stream=False`` because the InternLM API does not
        reliably support SSE streaming.
        """
        # Call parent to get base payload
        payload = await super()._prepare_payload(
            request_data, processed_messages, effective_model, context
        )
        # Strip vendor prefix from model name before sending to API
        from .base import strip_vendor_prefix

        payload["model"] = strip_vendor_prefix(
            payload.get("model", effective_model), "internlm"
        )

        # Enable deep thinking mode by default (as per InternLM API documentation)
        # https://internlm.intern-ai.org.cn/api/document?lang=en
        payload["thinking_mode"] = True

        # InternLM API does not reliably support SSE streaming.
        # Always request a non-streaming response from the backend; the
        # connector converts the result to SSE when the client asked for
        # streaming (see _chat_completions_canonical).
        payload["stream"] = False

        return payload

    # ------------------------------------------------------------------
    # Streaming shim: force non-streaming backend call, convert to SSE
    # ------------------------------------------------------------------

    async def _chat_completions_canonical(
        self,
        request: ConnectorChatCompletionsRequest,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Force a non-streaming request to InternLM and convert to SSE if needed.

        The InternLM API does not reliably support SSE streaming.  This
        override ensures we always make a non-streaming HTTP request to
        the backend.  When the originating client requested streaming, the
        non-streaming ``ResponseEnvelope`` is converted into a
        ``StreamingResponseEnvelope`` with a synthetic SSE event stream.
        """
        domain_request = request.request
        client_wants_streaming = domain_request.stream

        # Create a non-streaming copy of the request so the parent takes
        # the non-streaming code-path.  The domain request is a frozen
        # Pydantic model and cannot be mutated in-place.
        if client_wants_streaming:
            non_streaming_domain = domain_request.model_copy(update={"stream": False})
            non_streaming_request = ConnectorChatCompletionsRequest(
                request=non_streaming_domain,
                processed_messages=request.processed_messages,
                effective_model=request.effective_model,
                identity=request.identity,
                cancellation_token=request.cancellation_token,
                cancellation_coordinator=request.cancellation_coordinator,
                context=request.context,
                options=request.options,
            )
        else:
            non_streaming_request = request

        response = await super()._chat_completions_canonical(non_streaming_request)

        if not client_wants_streaming:
            return response

        # Client requested streaming -- wrap the non-streaming envelope as SSE.
        if not isinstance(response, ResponseEnvelope):
            # Unexpected: parent returned StreamingResponseEnvelope despite
            # stream=False -- return as-is.
            return response

        return self._wrap_as_streaming_envelope(response)

    # ------------------------------------------------------------------
    # Helpers for the non-streaming -> SSE conversion
    # ------------------------------------------------------------------

    def _wrap_as_streaming_envelope(
        self,
        response: ResponseEnvelope,
    ) -> StreamingResponseEnvelope:
        """Convert a ``ResponseEnvelope`` to a ``StreamingResponseEnvelope``.

        Produces a two-event SSE stream:
        1. A ``chat.completion.chunk`` event carrying the full response
           content in the ``delta`` field.
        2. The ``[DONE]`` sentinel that signals end-of-stream.
        """
        content_dict = response.content if isinstance(response.content, dict) else {}

        async def _synthetic_sse_stream() -> AsyncIterator[ProcessedResponse]:
            # Emit the content as an OpenAI-compatible streaming chunk
            chunk = self._to_streaming_chunk(content_dict)
            yield ProcessedResponse(
                content=(b"data: " + json.dumps(chunk).encode("utf-8") + b"\n\n"),
            )
            # Emit the terminal [DONE] sentinel
            yield ProcessedResponse(content=b"data: [DONE]\n\n")

        return StreamingResponseEnvelope(
            content=_synthetic_sse_stream(),
            media_type="text/event-stream",
            headers=response.headers,
            status_code=response.status_code,
        )

    @staticmethod
    def _to_streaming_chunk(response_dict: dict[str, Any]) -> dict[str, Any]:
        """Convert a non-streaming OpenAI response dict to streaming chunk format.

        Changes:
        * ``object`` becomes ``"chat.completion.chunk"``
        * Each choice's ``message`` key is renamed to ``delta``
        * A fallback ``id`` / ``created`` is injected when absent.
        """
        chunk: dict[str, Any] = dict(response_dict)
        chunk["object"] = "chat.completion.chunk"
        chunk.setdefault("id", f"chatcmpl-internlm-{uuid.uuid4().hex[:12]}")
        chunk.setdefault("created", int(time.time()))

        if "choices" in chunk and isinstance(chunk["choices"], list):
            new_choices: list[dict[str, Any]] = []
            for choice in chunk["choices"]:
                if not isinstance(choice, dict):
                    new_choices.append(choice)
                    continue
                new_choice = dict(choice)
                if "message" in new_choice:
                    new_choice["delta"] = new_choice.pop("message")
                new_choices.append(new_choice)
            chunk["choices"] = new_choices

        return chunk

    def get_available_models(self) -> list[str]:
        """Get a list of available InternLM models with vendor prefix."""
        # Available InternLM models
        models = [
            "intern-latest",  # Auto-routes to newest available model
            "intern-s1-pro",
            "intern-s1",
            "intern-s1-mini",
        ]

        # Add vendor prefix to all models
        from .base import add_vendor_prefix

        return [add_vendor_prefix(model, "internlm") for model in models]


backend_registry.register_backend("internlm", InternLMConnector)
