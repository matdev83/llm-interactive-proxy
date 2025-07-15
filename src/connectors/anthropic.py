"""
Anthropic backend connector – provides chat_completions and model discovery for the Anthropic Messages API.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, Tuple, Union, Callable, AsyncGenerator

import httpx
from fastapi import HTTPException
from starlette.responses import StreamingResponse

from src.connectors.base import LLMBackend
from src.models import ChatCompletionRequest
from src.security import APIKeyRedactor, ProxyCommandFilter

logger = logging.getLogger(__name__)


ANTHROPIC_VERSION_HEADER = "2023-06-01"
ANTHROPIC_DEFAULT_BASE_URL = "https://api.anthropic.com/v1"


class AnthropicBackend(LLMBackend):
    """LLMBackend implementation for Anthropic's Messages API."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client
        self.available_models: list[str] = []

    # -----------------------------------------------------------
    # Public helpers
    # -----------------------------------------------------------
    async def initialize(
        self,
        *,
        anthropic_api_base_url: str | None = None,
        key_name: str,
        api_key: str,
    ) -> None:
        """Fetch model list from Anthropic and cache."""
        base_url = anthropic_api_base_url or ANTHROPIC_DEFAULT_BASE_URL
        try:
            data = await self.list_models(base_url=base_url, key_name=key_name, api_key=api_key)
        except HTTPException as e:
            logger.warning("Could not list Anthropic models: %s", e.detail)
            return
        self.available_models = [m.get("name", m.get("id")) for m in data if isinstance(m, dict)]

    def get_available_models(self) -> list[str]:
        return list(self.available_models)

    # -----------------------------------------------------------
    # Core entry – called by proxy
    # -----------------------------------------------------------
    async def chat_completions(
        self,
        request_data: "ChatCompletionRequest",
        processed_messages: list,
        effective_model: str,
        openrouter_api_base_url: str | None = None,  # absorbs positional arg in base class
        openrouter_headers_provider: Callable[[str, str], Dict[str, str]] | None = None,  # unused
        key_name: str | None = None,
        api_key: str | None = None,
        project: str | None = None,
        prompt_redactor: "APIKeyRedactor" | None = None,
        command_filter: "ProxyCommandFilter" | None = None,
        **kwargs,
    ) -> Union[Tuple[Dict[str, Any], Dict[str, str]], StreamingResponse]:
        """Send request to Anthropic Messages endpoint and return data in OpenAI format."""
        if api_key is None:
            raise HTTPException(status_code=500, detail="Anthropic API key not configured")

        base_url = (openrouter_api_base_url or ANTHROPIC_DEFAULT_BASE_URL).rstrip("/")
        url = f"{base_url}/messages"

        anthropic_payload = self._prepare_anthropic_payload(
            request_data,
            processed_messages,
            effective_model,
            project,
            prompt_redactor,
            command_filter,
        )

        headers = {
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION_HEADER,
            "content-type": "application/json",
        }

        logger.info(
            "Forwarding to Anthropic. Model: %s Stream: %s", effective_model, request_data.stream
        )
        logger.debug("Anthropic payload: %s", json.dumps(anthropic_payload, indent=2))

        if request_data.stream:
            return await self._handle_streaming_response(url, anthropic_payload, headers, effective_model)
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
        request_data: ChatCompletionRequest,
        processed_messages: list,
        effective_model: str,
        project: str | None,
        prompt_redactor: APIKeyRedactor | None,
        command_filter: ProxyCommandFilter | None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "model": effective_model,
            "max_tokens": request_data.max_tokens or 1024,
            "stream": bool(request_data.stream),
        }

        # System message extraction (Anthropic expects it separately)
        system_prompt = None
        anth_messages: list[Dict[str, Any]] = []
        for msg in processed_messages:
            if msg.role == "system":
                if isinstance(msg.content, str):
                    system_prompt = msg.content
                else:
                    # If list/parts, flatten to string for system
                    system_prompt = json.dumps(msg.content)
                continue

            # Map content
            content = msg.content
            if isinstance(content, str):
                text = content
                if command_filter:
                    text = command_filter.filter_commands(text)
                if prompt_redactor:
                    text = prompt_redactor.redact(text)
                anth_messages.append({"role": msg.role, "content": text})
            else:
                # For list-of-parts, Anthropic only supports string or array of dict {"type":"text","text":...}
                parts: list[Any] = []
                for part in content:
                    if isinstance(part, dict):
                        # assume already valid
                        part_obj = part.copy()
                        if part_obj.get("type") == "text" and "text" in part_obj:
                            if command_filter:
                                part_obj["text"] = command_filter.filter_commands(part_obj["text"])
                            if prompt_redactor:
                                part_obj["text"] = prompt_redactor.redact(part_obj["text"])
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
        if project:
            payload["metadata"] = {"project": project}

        # Include extra params directly (allows reasoning, etc.)
        if request_data.extra_params:
            payload.update(request_data.extra_params)
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
    ) -> Tuple[Dict[str, Any], Dict[str, str]]:
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
    def _convert_stream_chunk(self, data: Dict[str, Any], model: str) -> Dict[str, Any]:
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

    def _convert_full_response(self, data: Dict[str, Any], model: str) -> Dict[str, Any]:
        """Convert full Anthropic message response to OpenAI format."""
        # Anthropic response example:
        # {"id":"...","content":[{"type":"text","text":"..."}],"role":"assistant","stop_reason":"stop","usage":{"input_tokens":X,"output_tokens":Y}}
        content_blocks = data.get("content", [])
        text = "".join(block.get("text", "") for block in content_blocks if block.get("type") == "text")
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
                "total_tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
            },
        }

    # -----------------------------------------------------------
    # Model listing
    # -----------------------------------------------------------
    async def list_models(self, *, base_url: str, key_name: str, api_key: str) -> list[Dict[str, Any]]:
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
        return response.json().get("models", response.json())
