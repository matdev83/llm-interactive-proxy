from __future__ import annotations

import httpx
import json
import logging
from typing import Union, Dict, Any, Optional

from fastapi import HTTPException
from src.models import ChatCompletionRequest
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
        **kwargs
    ) -> dict:
        # Use gemini_api_base_url if provided, else fallback to openrouter_api_base_url for compatibility
        gemini_api_base_url = openrouter_api_base_url or kwargs.get('gemini_api_base_url')
        if not gemini_api_base_url or not api_key:
            raise HTTPException(status_code=500, detail="Gemini API base URL and API key must be provided.")
        if request_data.stream:
            raise HTTPException(status_code=501, detail="Streaming not implemented for Gemini backend")

        payload_contents = []
        for msg in processed_messages:
            if isinstance(msg.content, str):
                text = msg.content
                if prompt_redactor:
                    text = prompt_redactor.redact(text)
                parts = [{"text": text}]
            else:
                parts = []
                for part in msg.content:
                    data = part.model_dump(exclude_unset=True)
                    if data.get("type") == "text" and "text" in data and prompt_redactor:
                        data["text"] = prompt_redactor.redact(data["text"])
                    parts.append(data)
            payload_contents.append({"role": msg.role, "parts": parts})

        payload = {"contents": payload_contents}
        if request_data.extra_params:
            payload.update(request_data.extra_params)
        # Do not add 'project' to payload for Gemini

        url = f"{gemini_api_base_url.rstrip('/')}/v1beta/models/{effective_model}:generateContent?key={api_key}"
        try:
            response = await self.client.post(url, json=payload)
            if response.status_code >= 400:
                try:
                    error_detail = response.json()
                except Exception:
                    error_detail = response.text
                raise HTTPException(status_code=response.status_code, detail=error_detail)
            return response.json()
        except httpx.RequestError as e:
            logger.error(f"Request error connecting to Gemini: {e}", exc_info=True)
            raise HTTPException(status_code=503, detail=f"Service unavailable: Could not connect to Gemini ({e})")
        # Removed the broad 'except Exception as e' block here.

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
                raise HTTPException(status_code=response.status_code, detail=error_detail)
            return response.json()
        except httpx.RequestError as e:
            logger.error(f"Request error connecting to Gemini: {e}", exc_info=True)
            raise HTTPException(status_code=503, detail=f"Service unavailable: Could not connect to Gemini ({e})")
        # Removed the broad 'except Exception as e' block here.
