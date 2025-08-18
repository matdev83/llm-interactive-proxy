"""
Anthropic backend connector - provides chat_completions and model discovery for the Anthropic Messages API.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncGenerator, Callable
from typing import Any, cast

import httpx
from fastapi import HTTPException
from starlette.responses import StreamingResponse

from src.connectors.base import LLMBackend
from src.core.domain.chat import ChatRequest

# Legacy ChatCompletionRequest removed from connector signatures; use domain ChatRequest

# API key redaction and command filtering are now handled by middleware
# from src.security import APIKeyRedactor, ProxyCommandFilter

logger = logging.getLogger(__name__)


ANTHROPIC_VERSION_HEADER = "2023-06-01"
ANTHROPIC_DEFAULT_BASE_URL = "https://api.anthropic.com/v1"


class AnthropicBackend(LLMBackend):
    """LLMBackend implementation for Anthropic's Messages API."""

    backend_type: str = "anthropic"

    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client
        self.available_models: list[str] = []

    # -----------------------------------------------------------
    # Public helpers
    # -----------------------------------------------------------
    async def initialize(self, **kwargs: Any) -> None:
        """Store configuration for lazy initialization."""
        self.anthropic_api_base_url = kwargs.get("anthropic_api_base_url")
        self.key_name = kwargs.get("key_name")
        self.api_key = kwargs.get("api_key")

        if not self.key_name or not self.api_key:
            raise ValueError("key_name and api_key are required for AnthropicBackend")

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
                logger.warning(f"Failed to fetch Anthropic models: {e}")
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
        request_data: ChatRequest,
        processed_messages: list[Any],
        effective_model: str,
        openrouter_api_base_url: str | None = None,
        openrouter_headers_provider: Callable[[str, str], dict[str, str]] | None = None,
        key_name: str | None = None,
        api_key: str | None = None,
        project: str | None = None,
        agent: str | None = None,
        **kwargs: Any,
    ) -> tuple[dict[str, Any], dict[str, str]] | StreamingResponse:
        """Send request to Anthropic Messages endpoint and return data in OpenAI format."""
        if api_key is None:
            raise HTTPException(
                status_code=500, detail="Anthropic API key not configured"
            )

        base_url = (openrouter_api_base_url or ANTHROPIC_DEFAULT_BASE_URL).rstrip("/")
        url = f"{base_url}/messages"

        # request_data is a domain ChatRequest; connectors can rely on adapter helpers
        anthropic_payload = self._prepare_anthropic_payload(
            request_data, processed_messages, effective_model, project
        )

        headers = {
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION_HEADER,
            "content-type": "application/json",
        }

        if logger.isEnabledFor(logging.INFO):
            logger.info(
                "Forwarding to Anthropic. Model: %s Stream: %s",
                effective_model,
                request_data.stream,
            )
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Anthropic payload: %s", json.dumps(anthropic_payload, indent=2)
            )

        if request_data.stream:
            return await self._handle_streaming_response(
                url, anthropic_payload, headers, effective_model
            )
        else:
            response_json, response_headers = await self._handle_non_streaming_response(
                url, anthropic_payload, headers, effective_model
            )
            return response_json, response_headers

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
            "model": effective_model,
            "max_tokens": request_data.max_tokens or 1024,
            "stream": bool(request_data.stream),
        }

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
        if getattr(request_data, "temperature", None) is not None:
            payload["temperature"] = request_data.temperature
        if request_data.top_p is not None:
            payload["top_p"] = request_data.top_p
        if request_data.stop is not None:
            payload["stop_sequences"] = request_data.stop
        if project:
            payload["metadata"] = {"project": project}

        # Include extra params from domain extra_body directly (allows reasoning, etc.)
        payload.update(request_data.extra_body or {})
        return payload

    # -----------------------------------------------------------
    # Non-streaming handling
    # -----------------------------------------------------------
    async def _handle_non_streaming_response(
        self,
        url: str,
        payload: dict,
        headers: dict,
        model: str,
    ) -> tuple[dict[str, Any], dict[str, str]]:
        response = await self.client.post(url, json=payload, headers=headers)
        if response.status_code >= 400:
            try:
                detail = response.json()
            except json.JSONDecodeError:
                detail = response.text
            raise HTTPException(status_code=response.status_code, detail=detail)
        data = response.json()
        converted = self._convert_full_response(data, model)
        return converted, dict(response.headers)

    # -----------------------------------------------------------
    # Streaming handling
    # -----------------------------------------------------------
    async def _handle_streaming_response(
        self,
        url: str,
        payload: dict,
        headers: dict,
        model: str,
    ) -> StreamingResponse:
        request = self.client.build_request("POST", url, json=payload, headers=headers)
        response = await self.client.send(request, stream=True)
        if response.status_code >= 400:
            try:
                body_text = (await response.aread()).decode("utf-8")
            except Exception:
                body_text = ""
            finally:
                await response.aclose()
            raise HTTPException(status_code=response.status_code, detail=body_text)

        async def event_stream() -> AsyncGenerator[bytes, None]:
            buffer = ""
            async for chunk in response.aiter_text():
                buffer += chunk
                while "\n\n" in buffer:
                    event, buffer = buffer.split("\n\n", 1)
                    # Ignore leading comments/keep-alives
                    if not event.strip() or event.startswith(":"):
                        continue
                    # Drop the leading "data: " prefix if present
                    if event.startswith("data: "):
                        event = event[6:]
                    # Anthropic ends with a DONE signal
                    if event.strip() == "[DONE]":
                        yield b"data: [DONE]\n\n"
                        continue
                    try:
                        json_data = json.loads(event)
                    except json.JSONDecodeError:
                        continue
                    chunk_dict = self._convert_stream_chunk(json_data, model)
                    yield ("data: " + json.dumps(chunk_dict) + "\n\n").encode("utf-8")
            await response.aclose()

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    # -----------------------------------------------------------
    # Converters
    # -----------------------------------------------------------
    def _convert_stream_chunk(self, data: dict[str, Any], model: str) -> dict[str, Any]:
        """Convert Anthropic delta event to OpenAI chat.completion.chunk format."""
        # Anthropic delta events have the shape:
        # {"type": "content_block_delta", "index":0, "delta": {"text":"..."}}
        text = ""
        finish_reason = None
        if data.get("type") == "content_block_delta":
            text = data.get("delta", {}).get("text", "")
        elif data.get("type") == "message_delta":
            finish_reason = data.get("delta", {}).get("stop_reason")
        return {
            "id": data.get("id", ""),
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": text},
                    "finish_reason": finish_reason,
                }
            ],
        }

    def _convert_full_response(
        self,
        data: dict[str, Any],
        model: str,
    ) -> dict[str, Any]:
        """Convert full Anthropic message response to OpenAI format."""
        # Anthropic response example:
        # {"id":"...","content":[{"type":"text","text":"..."}],"role":"assistant","stop_reason":"stop","usage":{"input_tokens":X,"output_tokens":Y}}
        content_blocks = data.get("content", [])
        text = "".join(
            block.get("text", "")
            for block in content_blocks
            if block.get("type") == "text"
        )
        usage = data.get("usage", {})
        return {
            "id": data.get("id", ""),
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": text},
                    "finish_reason": data.get("stop_reason"),
                }
            ],
            "usage": {
                "prompt_tokens": usage.get("input_tokens", 0),
                "completion_tokens": usage.get("output_tokens", 0),
                "total_tokens": usage.get("input_tokens", 0)
                + usage.get("output_tokens", 0),
            },
        }

    # -----------------------------------------------------------
    # Model listing
    # -----------------------------------------------------------
    async def list_models(
        self, *, base_url: str, key_name: str, api_key: str
    ) -> list[dict[str, Any]]:
        url = f"{base_url}/models"
        headers = {
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION_HEADER,
        }
        response = await self.client.get(url, headers=headers)
        if response.status_code >= 400:
            try:
                detail = response.json()
            except json.JSONDecodeError:
                detail = response.text
            raise HTTPException(status_code=response.status_code, detail=detail)
        return cast(
            list[dict[str, Any]], response.json().get("models", response.json())
        )