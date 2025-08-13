from __future__ import annotations

import json
import logging
import time
from typing import Any, AsyncGenerator, Callable, cast

import httpx
from fastapi import HTTPException
from starlette.responses import StreamingResponse

from src.connectors.base import LLMBackend
from src.models import (
    ChatCompletionRequest,
    MessageContentPartImage,
    MessageContentPartText,
)

# API key redaction and command filtering are now handled by middleware
# from src.security import APIKeyRedactor, ProxyCommandFilter

logger = logging.getLogger(__name__)


class GeminiBackend(LLMBackend):
    """LLMBackend implementation for Google's Gemini API."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client
        self.available_models: list[str] = []
        self.api_keys: list[str] = []

    async def initialize(
        self,
        *,
        gemini_api_base_url: str,
        key_name: str,
        api_key: str,
    ) -> None:
        """Fetch available models and cache them."""
        data = await self.list_models(
            gemini_api_base_url=gemini_api_base_url,
            key_name=key_name,
            api_key=api_key,
        )
        self.available_models = [
            m.get("name") for m in data.get("models", []) if m.get("name")
        ]

    def get_available_models(self) -> list[str]:
        """Return cached Gemini model names."""
        return list(self.available_models)

    def _convert_stream_chunk(self, data: dict[str, Any], model: str) -> dict[str, Any]:
        """Convert a Gemini streaming JSON chunk to OpenAI format."""
        candidate: dict[str, Any] = {}
        text = ""
        if data.get("candidates"):
            candidate = data["candidates"][0] or {}
            parts = candidate.get("content", {}).get("parts", [])
            for part in parts:
                if isinstance(part, dict) and "text" in part:
                    text += part["text"]
        finish = candidate.get("finishReason")
        return {
            "id": data.get("id", ""),
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": model,
            "choices": [
                {
                    "index": candidate.get("index", 0),
                    "delta": {"content": text},
                    "finish_reason": (
                        finish.lower() if isinstance(finish, str) else None
                    ),
                }
            ],
        }

    def _convert_full_response(
        self, data: dict[str, Any], model: str
    ) -> dict[str, Any]:
        """Convert a Gemini JSON response to OpenAI format, including function calls."""
        candidate: dict[str, Any] = {}
        text = ""
        tool_call_obj: dict[str, Any] | None = None
        if data.get("candidates"):
            candidate = data["candidates"][0] or {}
            parts = candidate.get("content", {}).get("parts", [])
            for part in parts:
                if isinstance(part, dict):
                    if part.get("functionCall"):
                        fc = part["functionCall"]
                        try:
                            args_str = json.dumps(fc.get("args", {}))
                        except Exception:
                            args_str = "{}"
                        tool_call_obj = {
                            "id": "call_0",
                            "type": "function",
                            "function": {
                                "name": fc.get("name", "function"),
                                "arguments": args_str,
                            },
                        }
                    elif "text" in part:
                        text += part["text"]
        finish = candidate.get("finishReason")
        usage = data.get("usageMetadata", {})

        message: dict[str, Any] = {"role": "assistant", "content": text}
        finish_reason = finish.lower() if isinstance(finish, str) else None
        if tool_call_obj is not None:
            message["content"] = None
            message["tool_calls"] = [tool_call_obj]
            finish_reason = "tool_calls"

        return {
            "id": data.get("id", ""),
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [
                {
                    "index": candidate.get("index", 0),
                    "message": message,
                    "finish_reason": finish_reason,
                }
            ],
            "usage": {
                "prompt_tokens": usage.get("promptTokenCount", 0),
                "completion_tokens": usage.get("candidatesTokenCount", 0),
                "total_tokens": usage.get("totalTokenCount", 0),
            },
        }

    def _convert_part_for_gemini(
        self,
        part: MessageContentPartText | MessageContentPartImage,
    ) -> dict[str, Any]:
        """Convert a MessageContentPart into Gemini API format."""
        if isinstance(part, MessageContentPartText):
            # Text content is already processed by middleware
            return {"text": part.text}
        if isinstance(part, MessageContentPartImage):
            url = part.image_url.url
            # Data URL -> inlineData
            if url.startswith("data:"):
                try:
                    header, b64_data = url.split(",", 1)
                    mime = header.split(";")[0][5:]
                except Exception:
                    mime = "application/octet-stream"
                    b64_data = ""
                return {"inlineData": {"mimeType": mime, "data": b64_data}}
            # Otherwise treat as remote file URI
            return {
                "fileData": {"mimeType": "application/octet-stream", "fileUri": url}
            }
        data = part.model_dump(exclude_unset=True)
        if data.get("type") == "text" and "text" in data:
            # Text content is already processed by middleware
            data.pop("type", None)
        return data

    def _prepare_gemini_contents(
        self,
        processed_messages: list[Any],
    ) -> list[dict[str, Any]]:
        payload_contents = []
        for msg in processed_messages:
            if msg.role == "system":
                # Gemini API does not support system role
                continue

            if isinstance(msg.content, str):
                # If this is a tool or function role, represent it as functionResponse for Gemini
                if msg.role in ["tool", "function"]:
                    # Try to parse JSON payload; otherwise wrap string
                    try:
                        input_obj = json.loads(msg.content)
                    except Exception:
                        input_obj = {"output": msg.content}
                    parts: list[dict[str, Any]] = [
                        {
                            "functionResponse": {
                                "name": getattr(msg, "name", "tool") or "tool",
                                "response": input_obj,
                            }
                        }
                    ]
                else:
                    # Content is already processed by middleware
                    parts = [{"text": msg.content}]
            else:
                parts = [self._convert_part_for_gemini(part) for part in msg.content]

            # Map roles to 'user' or 'model' as required by Gemini API
            if msg.role == "user":
                gemini_role = "user"
            elif msg.role in ["tool", "function"]:
                # Tool/function results are treated as coming from the user side in Gemini
                gemini_role = "user"
            else:  # e.g., assistant
                gemini_role = "model"

            payload_contents.append({"role": gemini_role, "parts": parts})
        return payload_contents

    async def _handle_gemini_streaming_response(
        self,
        base_url: str,
        payload: dict,
        headers: dict,
        effective_model: str,
    ) -> StreamingResponse:
        url = f"{base_url}:streamGenerateContent"
        try:
            request = self.client.build_request(
                "POST", url, json=payload, headers=headers
            )
            response = await self.client.send(request, stream=True)
            if response.status_code >= 400:
                try:
                    body_text = (await response.aread()).decode("utf-8")
                except Exception:
                    body_text = ""
                finally:
                    await response.aclose()
                logger.error(
                    "HTTP error during Gemini stream: %s - %s",
                    response.status_code,
                    body_text,
                )
                raise HTTPException(
                    status_code=response.status_code,
                    detail={
                        "message": f"Gemini stream error: {response.status_code} - {body_text}",
                        "type": "gemini_error",
                        "code": response.status_code,
                    },
                )

            async def stream_generator() -> AsyncGenerator[bytes, None]:
                decoder = json.JSONDecoder()
                buffer = ""
                try:
                    async for chunk in response.aiter_text():
                        buffer += chunk
                        while True:
                            buffer = buffer.lstrip()
                            if not buffer:
                                break
                            try:
                                obj, idx = decoder.raw_decode(buffer)
                            except json.JSONDecodeError:
                                break

                            if isinstance(obj, list):
                                for item in obj:
                                    if isinstance(item, dict):
                                        converted = self._convert_stream_chunk(
                                            item, effective_model
                                        )
                                        yield f"data: {json.dumps(converted)}\n\n".encode()
                                    else:
                                        logger.warning(
                                            f"Unexpected item type in Gemini stream: {type(item)}"
                                        )
                            elif isinstance(
                                obj, dict
                            ):  # Ensure obj is a dict before processing
                                converted = self._convert_stream_chunk(
                                    obj, effective_model
                                )
                                yield f"data: {json.dumps(converted)}\n\n".encode()
                            else:
                                logger.warning(
                                    f"Unexpected object type in Gemini stream: {type(obj)}"
                                )

                            buffer = buffer[idx:]
                            if buffer.startswith(","):
                                buffer = buffer[1:]
                    yield b"data: [DONE]\n\n"
                finally:
                    await response.aclose()

            return StreamingResponse(stream_generator(), media_type="text/event-stream")
        except httpx.RequestError as e:
            logger.error(f"Request error connecting to Gemini: {e}", exc_info=True)
            raise HTTPException(
                status_code=503,
                detail=f"Service unavailable: Could not connect to Gemini ({e})",
            )

    async def chat_completions(  # type: ignore[override]
        self,
        request_data: ChatCompletionRequest,
        processed_messages: list[Any],
        effective_model: str,
        openrouter_api_base_url: str | None = None,
        openrouter_headers_provider: Callable[[str, str], dict[str, str]] | None = None,
        key_name: str | None = None,
        api_key: str | None = None,
        project: str | None = None,
        agent: str | None = None,
        gemini_api_base_url: str | None = None,
        prompt_redactor: Any = None,
        command_filter: Any = None,
        **kwargs: Any,
    ) -> dict[str, Any] | StreamingResponse:
        # Use gemini_api_base_url parameter if provided, otherwise use openrouter_api_base_url or kwargs
        _gemini_api_base_url = (
            gemini_api_base_url
            or openrouter_api_base_url
            or kwargs.get("gemini_api_base_url")
        )
        _api_key = api_key or kwargs.get("api_key")

        if not _gemini_api_base_url or not _api_key:
            raise HTTPException(
                status_code=500,
                detail="Gemini API base URL and API key must be provided.",
            )

        payload_contents = self._prepare_gemini_contents(processed_messages)
        payload: dict[str, Any] = {"contents": payload_contents}

        # Handle Gemini-specific reasoning parameters
        if hasattr(request_data, "thinking_budget") and request_data.thinking_budget:
            if "generationConfig" not in payload:
                payload["generationConfig"] = {}
            if "thinkingConfig" not in payload["generationConfig"]:
                payload["generationConfig"]["thinkingConfig"] = {}
            payload["generationConfig"]["thinkingConfig"][
                "thinkingBudget"
            ] = request_data.thinking_budget

        if (
            hasattr(request_data, "generation_config")
            and request_data.generation_config
        ):
            if "generationConfig" not in payload:
                payload["generationConfig"] = {}
            payload["generationConfig"].update(request_data.generation_config)

        # Handle temperature parameter
        if (
            hasattr(request_data, "temperature")
            and request_data.temperature is not None
        ):
            if "generationConfig" not in payload:
                payload["generationConfig"] = {}
            # Validate temperature range for Gemini (0.0 to 1.0)
            temperature = request_data.temperature
            if temperature > 1.0:
                logger.warning(
                    f"Temperature {temperature} > 1.0 for Gemini, clamping to 1.0"
                )
                temperature = 1.0
            payload["generationConfig"]["temperature"] = temperature

        # Add extra parameters (may override or supplement the above)
        if request_data.extra_params:
            payload.update(request_data.extra_params)

        model_name = effective_model
        if model_name.startswith("gemini:"):
            model_name = model_name.split(":", 1)[1]
        if model_name.startswith("models/"):
            model_name = model_name.split("/", 1)[1]
        if model_name.startswith("gemini/"):
            model_name = model_name.split("/", 1)[1]
        # NEW: Strip provider prefixes like 'google/' that are used by OpenRouter
        # Only keep the final path segment which is the actual Gemini model id.
        if "/" in model_name:
            logger.debug(
                "Detected provider prefix in model name '%s'. Using last path segment as Gemini model id.",
                model_name,
            )
            model_name = model_name.rsplit("/", 1)[-1]

        logger.debug(f"Constructing Gemini API URL with model_name: {model_name}")
        base_api_url = f"{_gemini_api_base_url.rstrip('/')}/v1beta/models/{model_name}"
        headers = {"x-goog-api-key": _api_key}

        if request_data.stream:
            return await self._handle_gemini_streaming_response(
                base_api_url, payload, headers, effective_model
            )

        response_json = await self._handle_gemini_non_streaming_response(
            base_api_url, payload, headers, effective_model
        )
        return response_json

    async def _handle_gemini_non_streaming_response(
        self,
        base_url: str,
        payload: dict,
        headers: dict,
        effective_model: str,
    ) -> dict[str, Any]:
        url = f"{base_url}:generateContent"
        try:
            response = await self.client.post(url, json=payload, headers=headers)
            if response.status_code >= 400:
                try:
                    error_detail = response.json()
                except Exception:
                    error_detail = response.text
                raise HTTPException(
                    status_code=response.status_code, detail=error_detail
                )
            data = response.json()
            logger.debug(f"Gemini response headers: {dict(response.headers)}")
            return self._convert_full_response(data, effective_model)
        except httpx.RequestError as e:
            logger.error(f"Request error connecting to Gemini: {e}", exc_info=True)
            raise HTTPException(
                status_code=503,
                detail=f"Service unavailable: Could not connect to Gemini ({e})",
            )

    async def list_models(
        self,
        *,
        gemini_api_base_url: str,
        key_name: str,
        api_key: str,
    ) -> dict[str, Any]:
        headers = {"x-goog-api-key": api_key}
        url = f"{gemini_api_base_url.rstrip('/')}/v1beta/models"
        try:
            response = await self.client.get(url, headers=headers)
            if response.status_code >= 400:
                try:
                    error_detail = response.json()
                except Exception:
                    error_detail = response.text
                raise HTTPException(
                    status_code=response.status_code, detail=error_detail
                )
            return cast(dict[str, Any], response.json())
        except httpx.RequestError as e:
            logger.error(f"Request error connecting to Gemini: {e}", exc_info=True)
            raise HTTPException(
                status_code=503,
                detail=f"Service unavailable: Could not connect to Gemini ({e})",
            )
