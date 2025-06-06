from __future__ import annotations

import httpx
import json
import logging
from typing import Union, Dict, Any, Optional

from fastapi import HTTPException
from starlette.responses import StreamingResponse
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
                parts = []
                for part in msg.content:
                    data = part.model_dump(exclude_unset=True)
                    if (
                        data.get("type") == "text"
                        and "text" in data
                        and prompt_redactor
                    ):
                        data["text"] = prompt_redactor.redact(data["text"])
                    parts.append(data)
            payload_contents.append({"role": msg.role, "parts": parts})

        payload = {"contents": payload_contents}
        if request_data.extra_params:
            payload.update(request_data.extra_params)
        # Do not add 'project' to payload for Gemini

        base_url = f"{gemini_api_base_url.rstrip('/')}/v1beta/models/{effective_model}"

        if request_data.stream:
            url = f"{base_url}:streamGenerateContent?key={api_key}"
            try:

                async def stream_generator():
                    try:
                        async with self.client.stream(
                            "POST", url, json=payload
                        ) as response:
                            response.raise_for_status()
                            async for chunk in response.aiter_bytes():
                                yield chunk
                    except httpx.HTTPStatusError as e_stream:
                        logger.info(
                            "Caught httpx.HTTPStatusError in Gemini stream_generator"
                        )
                        logger.error(
                            f"HTTP error during Gemini stream: {e_stream.response.status_code} - {e_stream.response.content.decode('utf-8')}"
                        )
                        raise HTTPException(
                            status_code=e_stream.response.status_code,
                            detail={
                                "message": f"Gemini stream error: {e_stream.response.status_code} - {e_stream.response.content.decode('utf-8')}",
                                "type": "gemini_error",
                                "code": e_stream.response.status_code,
                            },
                        )
                    except Exception as e_gen:
                        logger.error(
                            f"Error in Gemini stream generator: {e_gen}", exc_info=True
                        )
                        raise HTTPException(
                            status_code=500,
                            detail={
                                "message": f"Proxy stream generator error: {str(e_gen)}",
                                "type": "proxy_error",
                                "code": "proxy_stream_error",
                            },
                        )

                return StreamingResponse(
                    stream_generator(), media_type="text/event-stream"
                )
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
            return response.json()
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
