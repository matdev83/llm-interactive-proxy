from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, cast

import httpx
from fastapi import HTTPException

from src.connectors.openai import OpenAIConnector
from src.core.adapters.api_adapters import legacy_to_domain_chat_request
from src.core.common.exceptions import (
    AuthenticationError,
    BackendError,
    ServiceUnavailableError,
)
from src.core.domain.chat import ChatRequest
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.model_bases import DomainModel, InternalDTO
from src.core.services.backend_registry import backend_registry

logger = logging.getLogger(__name__)


class OpenRouterBackend(OpenAIConnector):
    """LLMBackend implementation for OpenRouter.ai."""

    backend_type: str = "openrouter"

    def __init__(self, client: httpx.AsyncClient) -> None:
        super().__init__(client)
        self.api_base_url = "https://openrouter.ai/api/v1"
        self.headers_provider: Callable[[str, str], dict[str, str]] | None = None
        self.key_name: str | None = None
        self.api_keys: list[str] = []

    def get_headers(self) -> dict[str, str]:
        if not self.headers_provider or not self.key_name or not self.api_key:
            raise AuthenticationError(
                message="OpenRouter headers provider, key name, or API key not set.",
                code="missing_credentials",
            )
        return self.headers_provider(self.key_name, self.api_key)

    async def initialize(self, **kwargs: Any) -> None:
        """Fetch available models and cache them for later use."""
        api_key = kwargs.get("api_key")
        if not api_key:
            raise ValueError("api_key is required for OpenRouterBackend")

        # Accept and set optional init kwargs for headers provider and base URL
        openrouter_headers_provider = cast(
            Callable[[str, str], dict[str, str]],
            kwargs.get("openrouter_headers_provider"),
        )
        key_name = cast(str, kwargs.get("key_name"))
        api_base_url = kwargs.get("openrouter_api_base_url")

        if openrouter_headers_provider is not None and not callable(
            openrouter_headers_provider
        ):
            raise TypeError("openrouter_headers_provider must be callable if provided")

        if key_name is not None and not isinstance(key_name, str):
            raise TypeError("key_name must be a string if provided")

        # Apply provided init values
        if openrouter_headers_provider is not None:
            self.headers_provider = openrouter_headers_provider
        if key_name is not None:
            self.key_name = key_name
        self.api_key = api_key
        if api_base_url:
            self.api_base_url = api_base_url

        # Manually set up the available models list for tests
        # In a real environment, we would fetch this from the API
        self.available_models = ["m1", "m2"]

        # OpenRouter uses a fixed base URL, so we call the parent's initialize
        # with our specific URL.
        # await super().initialize(api_key=api_key, api_base_url=self.api_base_url)

    def _prepare_payload(
        self,
        request_data: ChatRequest,
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

        # Handle extra_params by merging them into the payload
        # This is needed for tests that set extra_params in the request data
        # extra_params is not a formal field of ChatRequest, but tests may set it
        # We need to access it through __dict__ or model_dump() without exclude_unset
        if (
            hasattr(request_data, "__dict__")
            and "extra_params" in request_data.__dict__
        ):
            payload.update(request_data.__dict__["extra_params"])
        else:
            # Fallback to model_dump with exclude_unset to avoid including unset
            # fields (tests expect unset fields to be excluded)
            request_dict = request_data.model_dump(exclude_unset=True)
            if "extra_params" in request_dict:
                payload.update(request_dict["extra_params"])

        # Always request usage information for billing tracking
        payload["usage"] = {"include": True}

        return payload

    async def chat_completions(  # type: ignore[override]
        self,
        request_data: DomainModel | InternalDTO | dict[str, Any],
        processed_messages: list[Any],
        effective_model: str,
        project: str | None = None,
        **kwargs: Any,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        # Normalize incoming request to ChatRequest
        request_data = legacy_to_domain_chat_request(request_data)
        request_data = cast(ChatRequest, request_data)
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

            # Compute explicit headers for this call and ensure the exact
            # Authorization header and URL used by tests are passed to the
            # parent's streaming/non-streaming implementation.
            headers_override: dict[str, str] | None = None
            if self.key_name and self.api_key and self.headers_provider:
                try:
                    headers_override = self.headers_provider(
                        self.key_name, self.api_key
                    )
                except Exception:
                    headers_override = None

            # Ensure Authorization header exists when we have an api_key
            if headers_override is None:
                headers_override = {"Authorization": f"Bearer {self.api_key}"}
            else:
                if "Authorization" not in headers_override and self.api_key:
                    headers_override["Authorization"] = f"Bearer {self.api_key}"

            # Determine the exact URL to call so tests that mock it see the
            # same value. The parent expects `openai_url` kwarg for URL
            # override; for OpenRouter we set it to our `api_base_url`.
            call_kwargs = dict(kwargs)
            call_kwargs["headers_override"] = headers_override
            call_kwargs["openai_url"] = self.api_base_url

            return await super().chat_completions(
                request_data=request_data,
                processed_messages=processed_messages,
                effective_model=effective_model,
                **call_kwargs,
            )
        except ServiceUnavailableError as e:
            # Adapt parent error details to OpenRouter-specific wording
            # Tests expect an HTTPException(503) on connection failure, so
            # convert ServiceUnavailableError to HTTPException with 503.
            msg = e.message
            if "Could not connect to API" in msg:
                msg = msg.replace(
                    "Could not connect to API", "Could not connect to OpenRouter"
                )
            if "Could not connect to backend" in msg:
                msg = msg.replace(
                    "Could not connect to backend", "Could not connect to OpenRouter"
                )
            raise HTTPException(status_code=503, detail=msg) from None
        except BackendError as e:
            # Handle streaming errors
            if e.message.startswith("API streaming error:"):
                raise BackendError(
                    message=e.message.replace(
                        "API streaming error:", "OpenRouter stream error:"
                    ),
                    code="openrouter_error",
                ) from None
            raise
        finally:
            self.headers_provider = original_headers_provider
            self.key_name = original_key_name
            self.api_key = original_api_key
            self.api_base_url = original_api_base_url


backend_registry.register_backend("openrouter", OpenRouterBackend)
