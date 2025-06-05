from __future__ import annotations

import httpx
from typing import AsyncIterator, Dict, Optional, Union, Any

from models import ChatCompletionRequest
from .base import LLMBackend


class OpenRouterBackend(LLMBackend):
    """LLM backend implementation for the OpenRouter API."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        api_key: str,
        api_base_url: str,
        app_site_url: str,
        app_title: str,
    ) -> None:
        self.client = client
        self.api_key = api_key
        self.api_base_url = api_base_url.rstrip("/")
        self.app_site_url = app_site_url
        self.app_title = app_title

    def _build_headers(self, extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": self.app_site_url,
            "X-Title": self.app_title,
            "User-Agent": f"{self.app_title}/1.0 (Python httpx)",
        }
        if extra:
            headers.update(extra)
        return headers

    async def chat_completion(
        self,
        request: ChatCompletionRequest,
        *,
        extra_headers: Optional[Dict[str, str]] = None,
        stream: bool = False,
    ) -> Union[Dict[str, Any], AsyncIterator[bytes]]:
        payload = request.model_dump(exclude_unset=True)
        if request.extra_params:
            payload.update(request.extra_params)
        headers = self._build_headers(extra_headers)

        if stream:
            async def iterator() -> AsyncIterator[bytes]:
                async with self.client.stream(
                    "POST",
                    f"{self.api_base_url}/chat/completions",
                    json=payload,
                    headers=headers,
                ) as resp:
                    resp.raise_for_status()
                    async for chunk in resp.aiter_bytes():
                        yield chunk

            return iterator()

        resp = await self.client.post(
            f"{self.api_base_url}/chat/completions",
            json=payload,
            headers=headers,
        )
        resp.raise_for_status()
        return resp.json()

    async def list_models(
        self, *, extra_headers: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        headers = self._build_headers(extra_headers)
        resp = await self.client.get(f"{self.api_base_url}/models", headers=headers)
        resp.raise_for_status()
        return resp.json()
