from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, cast

import httpx
from fastapi import HTTPException
from starlette.responses import StreamingResponse

from src.connectors.openai import OpenAIConnector
from src.models import ChatCompletionRequest

logger = logging.getLogger(__name__)


class OpenRouterBackend(OpenAIConnector):
    """LLMBackend implementation for OpenRouter.ai."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        super().__init__(client)
        self.api_base_url = "https://openrouter.ai/api/v1"
        self.headers_provider: Callable[[str, str], dict[str, str]] | None = None
        self.key_name: str | None = None
        self.api_keys: list[str] = []

    def get_headers(self) -> dict[str, str]:
        if not self.headers_provider or not self.key_name or not self.api_key:
            raise HTTPException(
                status_code=500,
                detail="OpenRouter headers provider, key name, or API key not set.",
            )
        return self.headers_provider(self.key_name, self.api_key)

    async def initialize(self, **kwargs: Any) -> None:
        """Fetch available models and cache them for later use."""
        api_key = kwargs.get("api_key")
        if not api_key:
            raise ValueError("api_key is required for OpenRouterBackend")

        openrouter_headers_provider = cast(
            Callable[[str, str], dict[str, str]],
            kwargs.get("openrouter_headers_provider"),
        )
        key_name = cast(str, kwargs.get("key_name"))

        if not callable(openrouter_headers_provider) or not isinstance(key_name, str):
            raise TypeError(
                "OpenRouterBackend requires 'openrouter_headers_provider' (Callable) "
                "and 'key_name' (str) in kwargs."
            )

        self.headers_provider = openrouter_headers_provider
        self.key_name = key_name
        # OpenRouter uses a fixed base URL, so we call the parent's initialize
        # with our specific URL.
        await super().initialize(api_key=api_key, api_base_url=self.api_base_url)

    def _prepare_payload(
        self,
        request_data: ChatCompletionRequest,
        processed_messages: list[Any],
        effective_model: str,
    ) -> dict[str, Any]:
        """Constructs the payload for the OpenRouter API request."""
        payload = super()._prepare_payload(
            request_data, processed_messages, effective_model
        )

        # Ensure the model name includes the provider prefix for OpenRouter
        if "/" not in effective_model:
            payload["model"] = f"openrouter/{effective_model}"
        else:
            payload["model"] = effective_model

        # Add project to payload if available
        if "project" in request_data.model_dump(exclude_unset=True):
            payload["project"] = request_data.model_dump(exclude_unset=True).get(
                "project"
            )

        # Always request usage information for billing tracking
        payload["usage"] = {"include": True}

        return payload

    async def chat_completions(  # type: ignore[override]
        self,
        request_data: ChatCompletionRequest,
        processed_messages: list[Any],
        effective_model: str,
        project: str | None = None,
        **kwargs: Any,
    ) -> StreamingResponse | tuple[dict[str, Any], dict[str, str]]:
        # Allow tests and callers to provide per-call OpenRouter settings via kwargs
        headers_provider = kwargs.pop("openrouter_headers_provider", None)
        key_name = kwargs.pop("key_name", None)
        api_key = kwargs.pop("api_key", None)
        api_base_url = kwargs.pop("openrouter_api_base_url", None)

        original_headers_provider = self.headers_provider
        original_key_name = self.key_name
        original_api_key = self.api_key
        original_api_base_url = self.api_base_url

        try:
            if headers_provider is not None:
                self.headers_provider = cast(
                    Callable[[str, str], dict[str, str]], headers_provider
                )
            if key_name is not None:
                self.key_name = cast(str, key_name)
            if api_key is not None:
                self.api_key = cast(str, api_key)
            if api_base_url:
                self.api_base_url = cast(str, api_base_url)

            # Compute explicit headers for this call if possible and pass
            # them to the parent as a headers_override so the streaming
            # implementation will see the Authorization header.
            headers_override = None
            try:
                if self.key_name and self.api_key and self.headers_provider:
                    headers_override = self.headers_provider(
                        self.key_name, self.api_key
                    )
            except Exception:
                headers_override = None

            # No-op: computed headers_override is passed to parent; keep
            # quiet in normal runs (debug-level logs already available).
            # Defensive: ensure Authorization header present when we have an api_key
            try:
                if (
                    headers_override is not None
                    and "Authorization" not in headers_override
                    and self.api_key
                ):
                    headers_override["Authorization"] = f"Bearer {self.api_key}"
            except Exception:
                pass
            call_kwargs = dict(kwargs)
            if headers_override is not None:
                call_kwargs["headers_override"] = headers_override

            return await super().chat_completions(
                request_data=request_data,
                processed_messages=processed_messages,
                effective_model=effective_model,
                **call_kwargs,
            )
        except HTTPException as e:
            # Adapt parent error details to OpenRouter-specific wording expected by tests
            if (
                e.status_code == 503
                and isinstance(e.detail, str)
                and "Could not connect to API" in e.detail
            ):
                raise HTTPException(
                    status_code=503,
                    detail=e.detail.replace(
                        "Could not connect to API", "Could not connect to OpenRouter"
                    ),
                ) from None
            if e.status_code >= 400 and isinstance(e.detail, dict):
                msg = str(e.detail.get("message", ""))
                if msg.startswith("API streaming error:"):
                    new_detail = dict(e.detail)
                    new_detail["message"] = msg.replace(
                        "API streaming error:", "OpenRouter stream error:"
                    )
                    new_detail["type"] = "openrouter_error"
                    raise HTTPException(
                        status_code=e.status_code, detail=new_detail
                    ) from None
            raise
        finally:
            self.headers_provider = original_headers_provider
            self.key_name = original_key_name
            self.api_key = original_api_key
            self.api_base_url = original_api_base_url
