from __future__ import annotations

import httpx
from typing import AsyncIterator, Dict, Optional, Union, Any, List

from src.models import (
    ChatCompletionRequest,
    ChatMessage,
    MessageContentPartText,
    MessageContentPartImage,
)
from .base import LLMBackend


class GeminiBackend(LLMBackend):
    """LLM backend for Google Gemini AI."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        api_keys: List[str],
        api_base_url: str = "https://generativelanguage.googleapis.com/v1beta",
    ) -> None:
        if not api_keys:
            raise ValueError("At least one API key must be provided")
        self.client = client
        self.api_keys = api_keys
        self.api_base_url = api_base_url.rstrip("/")
        self._key_index = 0

    def _next_key(self) -> str:
        key = self.api_keys[self._key_index]
        self._key_index = (self._key_index + 1) % len(self.api_keys)
        return key

    def _build_headers(self, extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if extra:
            headers.update(extra)
        return headers

    def _convert_messages(self, messages: List[ChatMessage]) -> List[Dict[str, Any]]:
        contents: List[Dict[str, Any]] = []
        for msg in messages:
            parts: List[Dict[str, Any]] = []
            if isinstance(msg.content, str):
                parts.append({"text": msg.content})
            else:
                for part in msg.content:
                    if isinstance(part, MessageContentPartText):
                        parts.append({"text": part.text})
                    elif isinstance(part, MessageContentPartImage):
                        parts.append(
                            {
                                "inline_data": {
                                    "mime_type": "image/png",
                                    "data": part.image_url.url,
                                }
                            }
                        )
            contents.append({"role": msg.role, "parts": parts})
        return contents

    async def chat_completion(
        self,
        request: ChatCompletionRequest,
        *,
        extra_headers: Optional[Dict[str, str]] = None,
        stream: bool = False,
    ) -> Union[Dict[str, Any], AsyncIterator[bytes]]:
        key = self._next_key()
        endpoint = "streamGenerateContent" if stream else "generateContent"
        url = f"{self.api_base_url}/models/{request.model}:{endpoint}?key={key}"
        payload = {"contents": self._convert_messages(request.messages)}
        if request.extra_params:
            payload.update(request.extra_params)
        headers = self._build_headers(extra_headers)

        if stream:
            async def iterator() -> AsyncIterator[bytes]:
                async with self.client.stream("POST", url, json=payload, headers=headers) as resp:
                    resp.raise_for_status()
                    async for chunk in resp.aiter_bytes():
                        yield chunk
            return iterator()

        resp = await self.client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        return {"data": resp.json(), "headers": dict(resp.headers)}

    async def list_models(self, *, extra_headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        key = self._next_key()
        url = f"{self.api_base_url}/models?key={key}"
        headers = self._build_headers(extra_headers)
        resp = await self.client.get(url, headers=headers)
        resp.raise_for_status()
        return {"data": resp.json(), "headers": dict(resp.headers)}
