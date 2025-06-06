from __future__ import annotations

import httpx
import json
import logging
import time
from typing import Union, Dict, Any, Optional

from fastapi import HTTPException
from starlette.responses import StreamingResponse
from src.models import (
    ChatCompletionRequest,
    MessageContentPartText,
    MessageContentPartImage,
)
from src.connectors.base import LLMBackend
from src.security import APIKeyRedactor

logger = logging.getLogger(__name__)


class GeminiBackend(LLMBackend):
    """LLMBackend implementation for Google's Gemini API."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client
        self.available_models: list[str] = []

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

    def _convert_stream_chunk(self, data: Dict[str, Any], model: str) -> Dict[str, Any]:
        """Convert a Gemini streaming JSON chunk to OpenAI format."""
        candidate = {}
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
                    "finish_reason": finish.lower() if isinstance(finish, str) else None,
                }
            ],
        }

    def _convert_full_response(self, data: Dict[str, Any], model: str) -> Dict[str, Any]:
        """Convert a Gemini JSON response to OpenAI format."""
        candidate = {}
        text = ""
        if data.get("candidates"):
            candidate = data["candidates"][0] or {}
            parts = candidate.get("content", {}).get("parts", [])
            for part in parts:
                if isinstance(part, dict) and "text" in part:
                    text += part["text"]
        finish = candidate.get("finishReason")
        usage = data.get("usageMetadata", {})
        return {
            "id": data.get("id", ""),
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [
                {
                    "index": candidate.get("index", 0),
                    "message": {"role": "assistant", "content": text},
                    "finish_reason": finish.lower() if isinstance(finish, str) else None,
                }
            ],
            "usage": {
                "prompt_tokens": usage.get("promptTokenCount", 0),
                "completion_tokens": usage.get("candidatesTokenCount", 0),
                "total_tokens": usage.get("totalTokenCount", 0),
            },
        }

    def _convert_part_for_gemini(
        self, part: Union[MessageContentPartText, MessageContentPartImage], prompt_redactor: APIKeyRedactor | None
    ) -> Dict[str, Any]:
        """Convert a MessageContentPart into Gemini API format."""
        if isinstance(part, MessageContentPartText):
            text = part.text
            if prompt_redactor:
                text = prompt_redactor.redact(text)
            return {"text": text}
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
            return {"fileData": {"mimeType": "application/octet-stream", "fileUri": url}}
        data = part.model_dump(exclude_unset=True)
        if data.get("type") == "text" and "text" in data:
            if prompt_redactor:
                data["text"] = prompt_redactor.redact(data["text"])
            data.pop("type", None)
        return data

    async def chat_completions(
        self,
        request_data: ChatCompletionRequest,
        processed_messages: list,
        effective_model: str,
        openrouter_api_base_url: Optional[str] = None,  # absorb unused param
        openrouter_headers_provider: object = None,  # absorb unused param
        key_name: Optional[str] = None,
        api_key: Optional[str] = None,
        project: str | None = None,
        prompt_redactor: APIKeyRedactor | None = None,
        **kwargs,
    ) -> dict:
        # Use gemini_api_base_url if provided, else fallback to openrouter_api_base_url for compatibility
        gemini_api_base_url = openrouter_api_base_url or kwargs.get(
            "gemini_api_base_url"
        )
        if not gemini_api_base_url or not api_key:
            raise HTTPException(
                status_code=500,
                detail="Gemini API base URL and API key must be provided.",
            )
        payload_contents = []
        for msg in processed_messages:
            if isinstance(msg.content, str):
                text = msg.content
                if prompt_redactor:
                    text = prompt_redactor.redact(text)
                parts = [{"text": text}]
            else:
                parts = [
                    self._convert_part_for_gemini(part, prompt_redactor)
                    for part in msg.content
                ]
            payload_contents.append({"role": msg.role, "parts": parts})

        payload = {"contents": payload_contents}
        if request_data.extra_params:
            payload.update(request_data.extra_params)
        # Do not add 'project' to payload for Gemini

        model_name = effective_model
        if model_name.startswith("gemini:"):
            model_name = model_name.split(":", 1)[1]
        if model_name.startswith("models/"):
            model_name = model_name.split("/", 1)[1]
        base_url = f"{gemini_api_base_url.rstrip('/')}/v1beta/models/{model_name}"

        if request_data.stream:
            url = f"{base_url}:streamGenerateContent?key={api_key}"
            try:
                request = self.client.build_request("POST", url, json=payload)
                response = await self.client.send(request, stream=True)
                if response.status_code >= 400:
                    try:
                        body_text = (await response.aread()).decode("utf-8")
                    except Exception:
                        body_text = ""
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

                async def stream_generator() -> bytes:
                    buffer = ""
                    try:
                        async for chunk in response.aiter_text():
                            buffer += chunk
                            while "\n" in buffer:
                                line, buffer = buffer.split("\n", 1)
                                line = line.strip()
                                if not line:
                                    continue
                                data = json.loads(line)
                                converted = self._convert_stream_chunk(data, effective_model)
                                yield f"data: {json.dumps(converted)}\n\n".encode()
                        if buffer.strip():
                            data = json.loads(buffer.strip())
                            converted = self._convert_stream_chunk(data, effective_model)
                            yield f"data: {json.dumps(converted)}\n\n".encode()
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

        url = f"{base_url}:generateContent?key={api_key}"
        try:
            response = await self.client.post(url, json=payload)
            if response.status_code >= 400:
                try:
                    error_detail = response.json()
                except Exception:
                    error_detail = response.text
                raise HTTPException(
                    status_code=response.status_code, detail=error_detail
                )
            data = response.json()
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
    ) -> Dict[str, Any]:
        url = f"{gemini_api_base_url.rstrip('/')}/v1beta/models?key={api_key}"
        try:
            response = await self.client.get(url)
            if response.status_code >= 400:
                try:
                    error_detail = response.json()
                except Exception:
                    error_detail = response.text
                raise HTTPException(
                    status_code=response.status_code, detail=error_detail
                )
            return response.json()
        except httpx.RequestError as e:
            logger.error(f"Request error connecting to Gemini: {e}", exc_info=True)
            raise HTTPException(
                status_code=503,
                detail=f"Service unavailable: Could not connect to Gemini ({e})",
            )
