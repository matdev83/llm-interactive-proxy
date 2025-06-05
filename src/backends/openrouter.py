from __future__ import annotations

import httpx
from typing import AsyncIterator, Dict, Optional, Union, Any

from fastapi import HTTPException # Added this import
from models import ChatCompletionRequest
from .base import LLMBackend


class OpenRouterBackend(LLMBackend):
    """LLM backend implementation for the OpenRouter API."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client
        self.api_key: str | None = None
        self.api_base_url: str | None = None
        self.app_site_url: str | None = None
        self.app_title: str | None = None
        self.available_models: list[str] = []

    async def initialize(
        self,
        *,
        openrouter_api_base_url: str,
        openrouter_headers_provider,
        key_name: str,
        api_key: str,
    ) -> None:
        self.api_key = api_key
        self.api_base_url = openrouter_api_base_url.rstrip("/")
        # The headers provider gives us app_site_url and app_title
        headers = openrouter_headers_provider(key_name, api_key)
        self.app_site_url = headers.get("HTTP-Referer")
        self.app_title = headers.get("X-Title")

        # Fetch available models and cache them
        try:
            data = await self.list_models()
            self.available_models = [
                m.get("id") for m in data.get("data", []) if m.get("id")
            ]
        except HTTPException as e:
            # If fetching models fails, we still want the backend to be
            # considered "functional" for chat completions if keys are present,
            # but model listing will be empty.
            # Log the error but don't re-raise to allow app to start.
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Failed to fetch OpenRouter models during initialization: {e.detail}")
            self.available_models = [] # Ensure it's empty on failure

    def _build_headers(self, extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        if not self.api_key or not self.app_site_url or not self.app_title:
            raise RuntimeError("OpenRouterBackend not initialized")
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

    def get_available_models(self) -> list[str]:
        return self.available_models
