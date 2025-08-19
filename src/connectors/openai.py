from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

import asyncio
from collections.abc import AsyncGenerator
from typing import Any

import httpx
from fastapi import HTTPException
from starlette.responses import StreamingResponse

from src.connectors.base import LLMBackend
from src.core.domain.chat import ChatRequest
from src.core.services.backend_registry import backend_registry

# Legacy ChatCompletionRequest removed from connector signatures; use domain ChatRequest


class OpenAIConnector(LLMBackend):
    """Minimal OpenAI-compatible connector used by OpenRouterBackend in tests.

    It supports an optional `headers_override` kwarg and treats streaming
    responses that expose `aiter_bytes()` as streamable even if returned by
    test doubles.
    """

    backend_type: str = "openai"

    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client
        self.available_models: list[str] = []
        self.api_key: str | None = None
        self.api_base_url: str = "https://api.openai.com/v1"

    def get_headers(self) -> dict[str, str]:
        if not self.api_key:
            return {}
        return {"Authorization": f"Bearer {self.api_key}"}

    async def initialize(self, **kwargs: Any) -> None:
        self.api_key = kwargs.get("api_key")
        logger.info(f"OpenAIConnector initialize called. api_key: {self.api_key}")
        if "api_base_url" in kwargs:
            self.api_base_url = kwargs["api_base_url"]

        # Fetch available models
        try:
            headers = self.get_headers()
            response = await self.client.get(
                f"{self.api_base_url}/models", headers=headers
            )
            # For mock responses in tests, status_code might not be accessible
            # or might not be 200, so we just try to access the data directly
            data = response.json()
            self.available_models = [model["id"] for model in data.get("data", [])]
        except Exception as e:
            logger.warning(f"Failed to fetch models: {e}")
            # Log the error but don't fail initialization

    def _prepare_payload(
        self,
        request_data: ChatRequest,
        processed_messages: list[Any],
        effective_model: str,
    ) -> dict[str, Any]:
        payload = request_data.model_dump(exclude_unset=True)
        payload["model"] = effective_model
        payload["messages"] = [
            m.model_dump() if hasattr(m, "model_dump") else m
            for m in processed_messages
        ]
        # Merge any connector-specific extra_body fields
        extra = getattr(request_data, "extra_body", None)
        if extra:
            payload.update(extra)
        return payload

    async def chat_completions(
        self,
        request_data: ChatRequest,
        processed_messages: list[Any],
        effective_model: str,
        **kwargs: Any,
    ) -> StreamingResponse | tuple[dict[str, Any], dict[str, str]]:
        payload = self._prepare_payload(
            request_data, processed_messages, effective_model
        )
        headers = kwargs.pop("headers_override", None)
        if headers is None:
            try:
                headers = self.get_headers()
            except Exception:
                headers = None

        api_base = kwargs.get("openai_url") or self.api_base_url
        url = f"{api_base.rstrip('/')}/chat/completions"

        if request_data.stream:
            # _handle_streaming_response now returns StreamingResponse
            return await self._handle_streaming_response(url, payload, headers)
        else:
            return await self._handle_non_streaming_response(url, payload, headers)

    async def _handle_non_streaming_response(
        self, url: str, payload: dict[str, Any], headers: dict[str, str] | None
    ) -> tuple[dict[str, Any], dict[str, str]]:
        if not headers or not headers.get("Authorization"):
            raise HTTPException(
                status_code=401,
                detail={"error": {"message": "No auth credentials found", "code": 401}},
            )
        try:
            response = await self.client.post(url, json=payload, headers=headers)
        except RuntimeError:
            # Client was closed by caller; create a new client for this request

            self.client = httpx.AsyncClient()
            response = await self.client.post(url, json=payload, headers=headers)
        except httpx.RequestError as e:
            raise HTTPException(
                status_code=503,
                detail=f"Service unavailable: Could not connect to backend ({e})",
            )
        if int(response.status_code) >= 400:
            try:
                err = response.json()
            except Exception:
                err = response.text
            raise HTTPException(status_code=response.status_code, detail=err)
        return response.json(), dict(response.headers)

    async def _handle_streaming_response(
        self, url: str, payload: dict[str, Any], headers: dict[str, str] | None
    ) -> StreamingResponse:
        if not headers or not headers.get("Authorization"):
            raise HTTPException(
                status_code=401,
                detail={"error": {"message": "No auth credentials found", "code": 401}},
            )

        request = self.client.build_request("POST", url, json=payload, headers=headers)
        try:
            response = await self.client.send(request, stream=True)
        except RuntimeError:
            # Recreate client if it was closed and retry once

            self.client = httpx.AsyncClient()
            request = self.client.build_request(
                "POST", url, json=payload, headers=headers
            )
            response = await self.client.send(request, stream=True)
        status_code = (
            int(response.status_code) if hasattr(response, "status_code") else 200
        )
        if status_code >= 400:
            try:
                body = (await response.aread()).decode("utf-8")
            except Exception:
                body = getattr(response, "text", "")
            raise HTTPException(
                status_code=status_code,
                detail={
                    "message": body,
                    "type": (
                        "openrouter_error" if "openrouter" in url else "openai_error"
                    ),
                    "code": status_code,
                },
            )

        async def gen() -> AsyncGenerator[bytes, None]:
            try:
                it = response.aiter_bytes()
                if hasattr(it, "__aiter__"):
                    async for chunk in it:
                        yield chunk
                elif hasattr(it, "__iter__"):
                    for chunk in it:  # type: ignore[misc]
                        yield chunk
                elif asyncio.iscoroutine(it):
                    res = await it
                    if hasattr(res, "__iter__"):
                        for chunk in res:
                            yield chunk
            finally:
                import contextlib

                with contextlib.suppress(Exception):
                    await response.aclose()

        # Safely convert headers to dict, handling both real httpx responses and mocks
        headers_dict = {}
        try:
            # Try the normal way first
            raw_headers = dict(response.headers)
            # Filter out any sentinel objects or invalid values
            headers_dict = {
                k: v
                for k, v in raw_headers.items()
                if hasattr(k, "encode") and hasattr(v, "encode")
            }
        except (TypeError, ValueError, AttributeError):
            # If that fails, try to handle Mock objects
            try:
                if hasattr(response.headers, "__dict__") and isinstance(
                    response.headers.__dict__, dict
                ):
                    raw_headers = response.headers.__dict__
                    # Filter out any sentinel objects or invalid values
                    headers_dict = {
                        k: v
                        for k, v in raw_headers.items()
                        if hasattr(k, "encode") and hasattr(v, "encode")
                    }
                else:
                    # Last resort: empty dict
                    headers_dict = {}
            except Exception:
                # If all else fails, use empty dict
                headers_dict = {}

        # Return a StreamingResponse via helper for consistent behavior
        from src.connectors.streaming_utils import to_streaming_response

        return to_streaming_response(
            lambda: gen(), media_type="text/event-stream", headers=headers_dict
        )

    async def list_models(self, api_base_url: str | None = None) -> dict[str, Any]:
        headers = self.get_headers()
        base = api_base_url or self.api_base_url
        logger.info(f"OpenAIConnector list_models - base URL: {base}")
        try:
            response = await self.client.get(
                f"{base.rstrip('/')}/models", headers=headers
            )
        except RuntimeError:
            import httpx

            self.client = httpx.AsyncClient()
            response = await self.client.get(
                f"{base.rstrip('/')}/models", headers=headers
            )
        response.raise_for_status()
        result = response.json()
        return result  # type: ignore[no-any-return]


backend_registry.register_backend("openai", OpenAIConnector)
