from __future__ import annotations

import httpx
import json
import logging
from typing import Union, Dict, Any

from fastapi import HTTPException
from src.models import ChatCompletionRequest
from src.connectors.base import LLMBackend

logger = logging.getLogger(__name__)

class GeminiBackend(LLMBackend):
    """LLMBackend implementation for Google's Gemini API."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client

    async def chat_completions(
        self,
        request_data: ChatCompletionRequest,
        processed_messages: list,
        effective_model: str,
        gemini_api_base_url: str,
        gemini_api_key: str,
    ) -> Dict[str, Any]:
        if request_data.stream:
            raise HTTPException(status_code=501, detail="Streaming not implemented for Gemini backend")

        payload = {
            "contents": [
                {
                    "role": msg.role,
                    "parts": (
                        [{"text": msg.content}]
                        if isinstance(msg.content, str)
                        else [part.model_dump(exclude_unset=True) for part in msg.content]
                    ),
                }
                for msg in processed_messages
            ]
        }
        if request_data.extra_params:
            payload.update(request_data.extra_params)

        url = f"{gemini_api_base_url.rstrip('/')}/v1beta/models/{effective_model}:generateContent?key={gemini_api_key}"
        try:
            response = await self.client.post(url, json=payload)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(
                f"HTTP error from Gemini API: {e.response.status_code} - {e.response.text}",
                exc_info=True,
            )
            raise HTTPException(status_code=e.response.status_code, detail=e.response.text)
        except httpx.RequestError as e:
            logger.error(f"Request error connecting to Gemini: {e}", exc_info=True)
            raise HTTPException(status_code=503, detail=f"Service unavailable: Could not connect to Gemini ({e})")
        except Exception as e:
            logger.error(f"Unexpected error in GeminiBackend.chat_completions: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))

    async def list_models(self, *, gemini_api_base_url: str, gemini_api_key: str) -> Dict[str, Any]:
        url = f"{gemini_api_base_url.rstrip('/')}/v1beta/models?key={gemini_api_key}"
        try:
            response = await self.client.get(url)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(
                f"HTTP error from Gemini API: {e.response.status_code} - {e.response.text}",
                exc_info=True,
            )
            raise HTTPException(status_code=e.response.status_code, detail=e.response.text)
        except httpx.RequestError as e:
            logger.error(f"Request error connecting to Gemini: {e}", exc_info=True)
            raise HTTPException(status_code=503, detail=f"Service unavailable: Could not connect to Gemini ({e})")
        except Exception as e:
            logger.error(f"Unexpected error in GeminiBackend.list_models: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))
