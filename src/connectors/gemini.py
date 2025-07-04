from __future__ import annotations

import httpx
import json
import logging
import time
from typing import Union, Dict, Any, Optional, AsyncGenerator

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
                    "finish_reason": (
                        finish.lower() if isinstance(finish, str) else None
                    ),
                }
            ],
        }

    def _convert_full_response(
        self, data: Dict[str, Any], model: str
    ) -> Dict[str, Any]:
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
                    "finish_reason": (
                        finish.lower() if isinstance(finish, str) else None
                    ),
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
        part: Union[MessageContentPartText, MessageContentPartImage],
        prompt_redactor: APIKeyRedactor | None,
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
            return {
                "fileData": {"mimeType": "application/octet-stream", "fileUri": url}
            }
        data = part.model_dump(exclude_unset=True)
        if data.get("type") == "text" and "text" in data:
            if prompt_redactor:
                data["text"] = prompt_redactor.redact(data["text"])
            data.pop("type", None)
        return data

    def _convert_messages_to_gemini_format( # Renamed this method
        self,
        processed_messages: list, # List of ChatMessage
        # request_data: ChatCompletionRequest, # Removed unused parameter
        prompt_redactor: APIKeyRedactor | None,
    ) -> List[Dict[str, Any]]:
        """Converts a list of ChatMessage objects to Gemini's 'contents' format."""
        gemini_messages = []
        for msg in processed_messages:
            if msg.role == "system":  # Gemini API does not support system role
                continue

            current_parts = []
            if isinstance(msg.content, str):
                text = msg.content
                if prompt_redactor:  # pragma: no cover
                    text = prompt_redactor.redact(text)
                current_parts = [{"text": text}]
            else:  # msg.content is a list of MessageContentPart
                current_parts = [
                    self._convert_part_for_gemini(part, prompt_redactor)
                    for part in msg.content
                ]

            # Map roles to 'user' or 'model'
            gemini_role = "user" if msg.role == "user" else "model"

            # Special handling for tool/function roles if needed (simplified here)
            if msg.role in ["tool", "function"]: # pragma: no cover
                gemini_role = "user" # Or map to a specific Gemini tool role if available
                try:
                    tool_content_str = json.dumps(msg.content)
                except TypeError: # pragma: no cover
                    tool_content_str = str(msg.content)
                # This part might need adjustment based on actual Gemini tool usage patterns
                current_parts = [{"text": f"tool_code: {tool_content_str}", "tool_response": msg.content}]


            gemini_messages.append({"role": gemini_role, "parts": current_parts})
        return gemini_messages

    def _prepare_gemini_payload(
        self,
        processed_messages: list, # List of ChatMessage
        request_data: ChatCompletionRequest,
        prompt_redactor: APIKeyRedactor | None,
    ) -> Dict[str, Any]:
        """Constructs the payload for the Gemini API."""
        payload_contents = self._convert_messages_to_gemini_format(processed_messages, prompt_redactor) # Removed request_data

        payload = {"contents": payload_contents}
        if request_data.extra_params:  # pragma: no cover
            payload.update(request_data.extra_params)
        return payload

    async def _handle_gemini_streaming_request(
        self,
        url: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
        effective_model: str,
    ) -> StreamingResponse:
        """Handles the streaming request to Gemini."""
        try:
            request = self.client.build_request("POST", url, json=payload, headers=headers)
            response = await self.client.send(request, stream=True)

            if response.status_code >= 400:
                body_text = ""
                try:
                    body_text = (await response.aread()).decode("utf-8")
                except Exception: # pragma: no cover
                    pass # Keep body_text empty
                finally:
                    await response.aclose()
                logger.error("HTTP error during Gemini stream: %s - %s", response.status_code, body_text)
                raise HTTPException(
                    status_code=response.status_code,
                    detail={"message": f"Gemini stream error: {response.status_code} - {body_text}", "type": "gemini_error", "code": response.status_code},
                )

            async def stream_generator() -> AsyncGenerator[bytes, None]:
                decoder = json.JSONDecoder()
                buffer = ""
                try:
                    async for chunk in response.aiter_text():
                        buffer += chunk
                        while True:
                            buffer = buffer.lstrip()
                            if not buffer: break
                            try:
                                obj, idx = decoder.raw_decode(buffer)
                            except json.JSONDecodeError: break # More data needed

                            items_to_process = obj if isinstance(obj, list) else [obj]
                            for item in items_to_process:
                                if isinstance(item, dict):
                                    converted = self._convert_stream_chunk(item, effective_model)
                                    yield f"data: {json.dumps(converted)}\n\n".encode()
                                else: # pragma: no cover
                                    logger.warning(f"Unexpected item type in Gemini stream: {type(item)}")

                            buffer = buffer[idx:]
                            if buffer.startswith(","): # pragma: no cover
                                buffer = buffer[1:]
                    yield b"data: [DONE]\n\n"
                finally:
                    await response.aclose()

            return StreamingResponse(stream_generator(), media_type="text/event-stream")

        except httpx.RequestError as e: # pragma: no cover
            logger.error(f"Request error connecting to Gemini stream: {e}", exc_info=True)
            raise HTTPException(status_code=503, detail=f"Service unavailable: Could not connect to Gemini ({e})")

    async def _handle_gemini_non_streaming_request(
        self,
        url: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
        effective_model: str,
    ) -> Dict[str, Any]:
        """Handles the non-streaming request to Gemini."""
        try:
            response = await self.client.post(url, json=payload, headers=headers)
            if response.status_code >= 400:
                try:
                    error_detail = response.json()
                except Exception: # pragma: no cover
                    error_detail = response.text
                raise HTTPException(status_code=response.status_code, detail=error_detail)

            data = response.json()
            return self._convert_full_response(data, effective_model)

        except httpx.RequestError as e: # pragma: no cover
            logger.error(f"Request error connecting to Gemini: {e}", exc_info=True)
            raise HTTPException(status_code=503, detail=f"Service unavailable: Could not connect to Gemini ({e})")

    async def chat_completions(
        self,
        request_data: ChatCompletionRequest,
        processed_messages: list,
        effective_model: str,
        openrouter_api_base_url: Optional[str] = None,
        openrouter_headers_provider: object = None, # Unused by Gemini directly
        key_name: Optional[str] = None, # Unused by Gemini directly
        api_key: Optional[str] = None,
        project: str | None = None, # Unused by Gemini payload
        prompt_redactor: APIKeyRedactor | None = None,
        **kwargs,
    ) -> Union[dict, StreamingResponse]:
        gemini_api_base_url = openrouter_api_base_url or kwargs.get("gemini_api_base_url")
        if not gemini_api_base_url or not api_key:
            raise HTTPException(status_code=500, detail="Gemini API base URL and API key must be provided.")

        payload = self._prepare_gemini_payload(processed_messages, request_data, prompt_redactor)

        model_name = effective_model
        if model_name.startswith("gemini:"): # pragma: no cover
            model_name = model_name.split(":", 1)[1]
        if model_name.startswith("models/"): # pragma: no cover
            # This is the expected format e.g. models/gemini-pro
            pass # model_name = model_name.split("/", 1)[1] - No, keep "models/"
        else:
            # Assume it's a short name like "gemini-pro" and prepend "models/"
            model_name = f"models/{model_name}"


        # Correctly construct base_url without :generateContent or :streamGenerateContent yet
        # It should be like: https://generativelanguage.googleapis.com/v1beta/models/gemini-pro
        base_api_url = f"{gemini_api_base_url.rstrip('/')}/v1beta/{model_name}"
        headers = {"x-goog-api-key": api_key, "Content-Type": "application/json"}

        if request_data.stream:
            stream_url = f"{base_api_url}:streamGenerateContent"
            return await self._handle_gemini_streaming_request(stream_url, payload, headers, effective_model)

        non_stream_url = f"{base_api_url}:generateContent"
        return await self._handle_gemini_non_streaming_request(non_stream_url, payload, headers, effective_model)

    async def list_models(
        self,
        *,
        gemini_api_base_url: str,
        key_name: str,
        api_key: str,
    ) -> Dict[str, Any]:
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
            return response.json()
        except httpx.RequestError as e:
            logger.error(f"Request error connecting to Gemini: {e}", exc_info=True)
            raise HTTPException(
                status_code=503,
                detail=f"Service unavailable: Could not connect to Gemini ({e})",
            )
