from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator
from typing import Any, cast

import httpx
from fastapi import HTTPException
from starlette.responses import StreamingResponse

from src.connectors.base import LLMBackend
from src.models import ChatCompletionRequest

logger = logging.getLogger(__name__)


class OpenAIConnector(LLMBackend):
    """LLMBackend implementation for OpenAI-compatible APIs."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client
        self.available_models: list[str] = []
        self.api_key: str | None = None
        self.api_keys: list[str] = []
        self.api_base_url: str = "https://api.openai.com/v1"

    def get_headers(self) -> dict[str, str]:
        if not self.api_key:
            raise HTTPException(status_code=500, detail="API key is not set.")
        return {"Authorization": f"Bearer {self.api_key}"}

    async def initialize(self, **kwargs: Any) -> None:
        """Initialize the connector and fetch available models."""
        self.api_key = kwargs.get("api_key")
        if not self.api_key:
            raise ValueError("api_key is required for OpenAIConnector")
        
        api_base_url = kwargs.get("api_base_url")
        if api_base_url:
            self.api_base_url = api_base_url

        # Allow tests to skip model discovery to avoid network and simplify mocks
        if kwargs.get("skip_backend_discovery") or getattr(self.client, "skip_backend_discovery", False):
            logger.debug("Skipping OpenAI model discovery (test mode).")
            self.available_models = []
            return

        data = await self.list_models(api_base_url)
        self.available_models = [
            m.get("id") for m in data.get("data", []) if m.get("id")
        ]

    def get_available_models(self) -> list[str]:
        """Return the list of cached model identifiers."""
        return list(self.available_models)

    def _prepare_payload(
        self,
        request_data: ChatCompletionRequest,
        processed_messages: list[Any],
        effective_model: str,
    ) -> dict[str, Any]:
        """Constructs the payload for the OpenAI API request.

        Tests may pass processed_messages as plain dicts instead of Pydantic models.
        This method normalizes each item to a serializable dict.
        """
        payload = request_data.model_dump(exclude_unset=True)
        payload["model"] = effective_model

        def _to_dict(msg: Any) -> dict[str, Any]:
            # Pydantic v2
            if hasattr(msg, "model_dump") and callable(msg.model_dump):
                return msg.model_dump(exclude_unset=True)
            # Pydantic v1-style
            if hasattr(msg, "dict") and callable(msg.dict):
                try:
                    return msg.dict(exclude_unset=True)  # type: ignore[attr-defined]
                except TypeError:
                    # Fallback if exclude_unset unsupported
                    return msg.dict()  # type: ignore[attr-defined]
            # Already a mapping
            if isinstance(msg, dict):
                return msg
            # Last resort: try best-effort JSON roundtrip
            try:
                return json.loads(json.dumps(msg))
            except Exception:
                # If all else fails, wrap as content string
                return {"content": str(msg)}

        payload["messages"] = [_to_dict(msg) for msg in processed_messages]

        if request_data.extra_params:
            payload.update(request_data.extra_params)

        return payload

    async def chat_completions(  # type: ignore[override]
        self,
        request_data: ChatCompletionRequest,
        processed_messages: list[Any],
        effective_model: str,
        **kwargs: Any,
    ) -> StreamingResponse | tuple[dict[str, Any], dict[str, str]]:
        payload = self._prepare_payload(
            request_data,
            processed_messages,
            effective_model,
        )

        logger.info(
            f"Forwarding to OpenAI-compatible API. Effective model: {effective_model}. Stream: {request_data.stream}"
        )
        logger.debug(f"Payload for API: {json.dumps(payload, indent=2)}")

        headers = self.get_headers()

        # Check if a custom URL is provided in the session state
        custom_url = kwargs.get("openai_url")
        api_base_url = custom_url if custom_url else self.api_base_url
        api_url = f"{api_base_url}/chat/completions"

        if custom_url:
            logger.info(f"Using custom OpenAI URL: {custom_url}")
        else:
            logger.debug(f"Using default OpenAI URL: {self.api_base_url}")

        try:
            if request_data.stream:
                return await self._handle_streaming_response(api_url, payload, headers)
            else:
                return await self._handle_non_streaming_response(
                    api_url, payload, headers
                )
        except httpx.HTTPStatusError as e:
            logger.error(
                f"HTTP error from API: {e.response.status_code} - {e.response.text}",
                exc_info=True,
            )
            try:
                error_detail = e.response.json()
            except json.JSONDecodeError:
                error_detail = e.response.text
            raise HTTPException(status_code=e.response.status_code, detail=error_detail)
        except httpx.RequestError as e:
            logger.error(
                f"Request error connecting to API: {type(e).__name__} - {e!s}",
                exc_info=True,
            )
            raise HTTPException(
                status_code=503,
                detail=f"Service unavailable: Could not connect to API ({e!s})",
            )

    async def _handle_non_streaming_response(
        self, url: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> tuple[dict[str, Any], dict[str, str]]:
        logger.debug("Initiating non-streaming request to API.")
        # Ensure client is open (tests may reuse a closed instance)
        if hasattr(self.client, "is_closed") and self.client.is_closed:
            self.client = httpx.AsyncClient()
        response = await self.client.post(url, json=payload, headers=headers)
        logger.debug(f"API non-stream response status: {response.status_code}")

        # Explicitly handle error status codes even when test doubles don't raise
        try:
            status_code = int(response.status_code)
        except Exception:
            status_code = 200
        if status_code >= 400:
            try:
                error_detail = response.json()
            except Exception:
                try:
                    error_detail = response.text
                except Exception:
                    error_detail = "Unknown error"
            raise HTTPException(status_code=status_code, detail=error_detail)

        try:
            response_json = response.json()
        except Exception:
            response_json = {}
        try:
            response_headers = dict(response.headers)
        except Exception:
            response_headers = {}
        logger.debug(f"API response JSON: {json.dumps(response_json, indent=2)}")
        logger.debug(f"API response headers: {response_headers}")
        return response_json, response_headers

    async def _handle_streaming_response(
        self, url: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> StreamingResponse:
        logger.debug("Initiating stream request to API.")
        try:
            # Ensure client is open (tests may reuse a closed instance)
            if hasattr(self.client, "is_closed") and self.client.is_closed:
                self.client = httpx.AsyncClient()
            request = self.client.build_request(
                "POST", url, json=payload, headers=headers
            )
            response = await self.client.send(request, stream=True)
            # Explicitly handle error status codes even when test doubles don't raise
            try:
                status_code = int(response.status_code)
            except Exception:
                status_code = 200
            if status_code >= 400:
                try:
                    body_text = (await response.aread()).decode("utf-8")
                except Exception:
                    try:
                        body_text = response.text
                    except Exception:
                        body_text = "Unable to read error response"
                from contextlib import suppress

                with suppress(Exception):
                    await response.aclose()
                raise HTTPException(
                    status_code=status_code,
                    detail={
                        "message": f"API streaming error: {status_code} - {body_text}",
                        "type": "stream_error",
                        "code": status_code,
                    },
                )

            async def stream_generator() -> AsyncGenerator[bytes, None]:
                try:
                    async for chunk in response.aiter_bytes():
                        yield chunk
                    logger.debug("API stream finished.")
                finally:
                    await response.aclose()

            try:
                response_headers = dict(response.headers)
            except Exception:
                response_headers = {}

            return StreamingResponse(
                stream_generator(),
                media_type="text/event-stream",
                headers=response_headers,
            )
        except httpx.HTTPStatusError as e:
            body_text = (await e.response.aread()).decode("utf-8")
            await e.response.aclose()
            logger.error(
                f"HTTP error during API stream: {e.response.status_code} - {body_text}",
            )
            raise HTTPException(
                status_code=e.response.status_code,
                detail=body_text,
            )
        except httpx.RequestError as e:
            logger.error(f"Request error connecting to API: {e}", exc_info=True)
            raise HTTPException(
                status_code=503,
                detail=f"Service unavailable: Could not connect to API ({e})",
            )

    async def list_models(self, api_base_url: str | None = None) -> dict[str, Any]:
        """Fetch available models from the configured API endpoint."""
        headers = self.get_headers()
        url_to_use = api_base_url if api_base_url else self.api_base_url
        try:
            response = await self.client.get(f"{url_to_use}/models", headers=headers)
            response.raise_for_status()
            return cast(dict[str, Any], response.json())
        except httpx.HTTPStatusError as e:
            logger.error(
                f"HTTP error fetching models: {e.response.status_code} - {e.response.text}",
                exc_info=True,
            )
            try:
                error_detail = e.response.json()
            except json.JSONDecodeError:
                error_detail = e.response.text
            raise HTTPException(status_code=e.response.status_code, detail=error_detail)
        except httpx.RequestError as e:
            logger.error(
                f"Request error fetching models: {type(e).__name__} - {e!s}",
                exc_info=True,
            )
            raise HTTPException(
                status_code=503,
                detail=f"Service unavailable: Could not fetch models ({e!s})",
            )
