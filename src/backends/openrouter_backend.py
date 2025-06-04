from __future__ import annotations

import json
import logging
from typing import Any, AsyncGenerator, Dict

import httpx

from models import ChatCompletionRequest
from .base import Backend

logger = logging.getLogger(__name__)


class OpenRouterBackend(Backend):
    """Backend implementation for the OpenRouter API."""

    prefix = "openrouter"

    def __init__(self, api_key: str, base_url: str):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    def _headers(self) -> Dict[str, str]:
        if not self.api_key:
            raise RuntimeError("OPENROUTER_API_KEY is not configured")
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def chat_completions(
        self, request: ChatCompletionRequest, client: httpx.AsyncClient
    ) -> Any:
        payload = request.model_dump(exclude_unset=True)
        payload["messages"] = [m.model_dump(exclude_unset=True) for m in request.messages]
        if request.stream:
            req = client.build_request(
                "POST",
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=self._headers(),
            )

            async def gen() -> AsyncGenerator[bytes, None]:
                async with client.stream(req) as response:
                    response.raise_for_status()
                    async for chunk in response.aiter_bytes():
                        yield chunk
            return gen()
        else:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=self._headers(),
            )
            response.raise_for_status()
            return response.json()

    async def list_models(self, client: httpx.AsyncClient) -> Dict[str, Any]:
        response = await client.get(f"{self.base_url}/models", headers=self._headers())
        response.raise_for_status()
        return response.json()
