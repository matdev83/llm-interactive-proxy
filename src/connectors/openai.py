from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from typing import Any

import httpx
from fastapi import HTTPException
from starlette.responses import StreamingResponse

from src.connectors.base import LLMBackend
from src.models import ChatCompletionRequest


class OpenAIConnector(LLMBackend):
    """Minimal OpenAI-compatible connector used by OpenRouterBackend in tests.

    It supports an optional `headers_override` kwarg and treats streaming
    responses that expose `aiter_bytes()` as streamable even if returned by
    test doubles.
    """

    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client
        self.available_models: list[str] = []
        self.api_key: str | None = None
        self.api_base_url: str = "https://api.openai.com/v1"

    def get_headers(self) -> dict[str, str]:
        if not self.api_key:
            raise HTTPException(status_code=500, detail="API key is not set.")
        return {"Authorization": f"Bearer {self.api_key}"}

    async def initialize(self, **kwargs: Any) -> None:
        self.api_key = kwargs.get("api_key")
        api_base_url = kwargs.get("api_base_url")
        if api_base_url:
            self.api_base_url = api_base_url

    def _prepare_payload(
        self,
        request_data: ChatCompletionRequest,
        processed_messages: list[Any],
        effective_model: str,
    ) -> dict[str, Any]:
        payload = request_data.model_dump(exclude_unset=True)
        payload["model"] = effective_model
        payload["messages"] = [
            m.model_dump() if hasattr(m, "model_dump") else m
            for m in processed_messages
        ]
        if request_data.extra_params:
            payload.update(request_data.extra_params)
        return payload

    async def chat_completions(
        self,
        request_data: ChatCompletionRequest,
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
        url = f"{api_base}/chat/completions"

        if request_data.stream:
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
        response = await self.client.post(url, json=payload, headers=headers)
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
        response = await self.client.send(request, stream=True)
        status_code = (
            int(response.status_code) if hasattr(response, "status_code") else 200
        )
        if status_code >= 400:
            try:
                body = (await response.aread()).decode("utf-8")
            except Exception:
                body = getattr(response, "text", "")
            raise HTTPException(status_code=status_code, detail={"message": body})

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

        return StreamingResponse(
            gen(), media_type="text/event-stream", headers=dict(response.headers)
        )

    async def list_models(self, api_base_url: str | None = None) -> dict[str, Any]:
        headers = self.get_headers()
        base = api_base_url or self.api_base_url
        response = await self.client.get(f"{base}/models", headers=headers)
        response.raise_for_status()
        return response.json()
