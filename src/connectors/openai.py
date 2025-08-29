from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

from collections.abc import AsyncGenerator, AsyncIterator
from typing import Any, cast

import httpx
from fastapi import HTTPException

from src.connectors.base import LLMBackend
from src.core.adapters.api_adapters import dict_to_domain_chat_request
from src.core.common.exceptions import AuthenticationError, ServiceUnavailableError
from src.core.config.app_config import AppConfig
from src.core.domain.chat import ChatRequest
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.configuration_interface import IAppIdentityConfig
from src.core.interfaces.model_bases import DomainModel, InternalDTO
from src.core.interfaces.response_processor_interface import (
    IResponseProcessor,
    ProcessedResponse,
)
from src.core.services.backend_registry import backend_registry

# Add health check flag for subclasses to control behavior
HEALTH_CHECK_SUPPORTED = False

# Legacy ChatCompletionRequest removed from connector signatures; use domain ChatRequest


class OpenAIConnector(LLMBackend):
    """Minimal OpenAI-compatible connector used by OpenRouterBackend in tests.

    It supports an optional `headers_override` kwarg and treats streaming
    responses that expose `aiter_bytes()` as streamable even if returned by
    test doubles.
    """

    backend_type: str = "openai"

    def __init__(
        self,
        client: httpx.AsyncClient,
        config: AppConfig,  # Added
        response_processor: IResponseProcessor | None = None,
    ) -> None:
        super().__init__(config, response_processor)
        self.client = client
        self.config = config  # Stored config
        self.available_models: list[str] = []
        self.api_key: str | None = None
        self.api_base_url: str = "https://api.openai.com/v1"
        self.identity: Any | None = None

        # Health check attributes
        self._health_checked: bool = False
        # Check environment variable to allow disabling health checks globally
        import os

        disable_health_checks = os.getenv("DISABLE_HEALTH_CHECKS", "false").lower() in (
            "true",
            "1",
            "yes",
        )

        # Also disable health checks during testing (detect pytest)
        is_testing = (
            "pytest" in os.environ.get("_", "") or "PYTEST_CURRENT_TEST" in os.environ
        )

        self._health_check_enabled: bool = (
            not disable_health_checks and not is_testing
        )  # Enabled by default unless disabled or testing

    def get_headers(self) -> dict[str, str]:
        if not self.api_key:
            return {}
        headers = {"Authorization": f"Bearer {self.api_key}"}
        if self.identity:
            headers["HTTP-Referer"] = self.identity.url
            headers["X-Title"] = self.identity.title
        return headers

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
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(f"Failed to fetch models: {e}")
            # Log the error but don't fail initialization

    async def _perform_health_check(self) -> bool:
        """Perform a health check by testing API connectivity.

        This method tests actual API connectivity by making a simple request to verify
        the API key works and the service is accessible.

        Returns:
            bool: True if health check passes, False otherwise
        """
        try:
            # Test API connectivity with a simple models endpoint request
            if not self.api_key:
                logger.warning("Health check failed - no API key available")
                return False

            headers = self.get_headers()
            if not headers.get("Authorization"):
                logger.warning("Health check failed - no authorization header")
                return False

            url = f"{self.api_base_url}/models"
            response = await self.client.get(url, headers=headers)

            if response.status_code == 200:
                logger.info("Health check passed - API connectivity verified")
                self._health_checked = True
                return True
            else:
                logger.warning(
                    f"Health check failed - API returned status {response.status_code}"
                )
                return False

        except Exception as e:
            if logger.isEnabledFor(logging.ERROR):
                logger.error(f"Health check failed - unexpected error: {e}")
            return False

    async def _ensure_healthy(self) -> None:
        """Ensure the backend is healthy before use.

        This method performs health checks on first use, similar to how
        models are loaded lazily in the parent class.
        """
        if not self._health_check_enabled:
            # Health check is disabled, skip
            return

        if not hasattr(self, "_health_checked") or not self._health_checked:
            logger.info(
                f"Performing first-use health check for {self.backend_type} backend"
            )

            if not await self._perform_health_check():
                from src.core.common.exceptions import BackendError

                raise BackendError(
                    "Health check failed - API key or connectivity issue"
                )

            self._health_checked = True
            logger.info("Health check passed - backend is ready for use")

    def enable_health_check(self) -> None:
        """Enable health check functionality for this connector instance."""
        self._health_check_enabled = True
        self._health_checked = False  # Reset so it will check on next use
        logger.info(f"Health check enabled for {self.backend_type} backend")

    def disable_health_check(self) -> None:
        """Disable health check functionality for this connector instance."""
        self._health_check_enabled = False
        logger.info(f"Health check disabled for {self.backend_type} backend")

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

        # Add seed if available
        if request_data.seed is not None:
            payload["seed"] = request_data.seed

        return payload

    def _ensure_string_keys_and_values(self, data: Any) -> Any:
        """Recursively ensures all dictionary keys and values (if bytes) are strings."""
        if isinstance(data, dict):
            return {
                self._ensure_string_keys_and_values(
                    k
                ): self._ensure_string_keys_and_values(v)
                for k, v in data.items()
            }
        elif isinstance(data, list):
            return [self._ensure_string_keys_and_values(elem) for elem in data]
        elif isinstance(data, bytes | bytearray):  # Handle bytes and bytearray directly
            try:
                return data.decode("utf-8")
            except UnicodeDecodeError:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(f"Could not decode bytes to utf-8: {data!r}")
                return str(data)  # Fallback to string representation
        elif isinstance(
            data, memoryview
        ):  # Convert memoryview to bytes before decoding
            try:
                return bytes(data).decode("utf-8")
            except UnicodeDecodeError:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(f"Could not decode memoryview to utf-8: {data!r}")
                return str(data)  # Fallback to string representation
        else:
            return data

    async def chat_completions(
        self,
        request_data: DomainModel | InternalDTO | dict[str, Any],
        processed_messages: list[Any],
        effective_model: str,
        identity: IAppIdentityConfig | None = None,
        **kwargs: Any,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        # Perform health check if enabled (for subclasses that support it)
        await self._ensure_healthy()

        # Normalize incoming request to domain ChatRequest
        if isinstance(request_data, dict):
            request_data = dict_to_domain_chat_request(
                self._ensure_string_keys_and_values(request_data)
            )
        elif not isinstance(request_data, ChatRequest):
            # Convert to dict first
            if hasattr(request_data, "model_dump"):
                request_dict = request_data.model_dump()  # type: ignore
            elif hasattr(request_data, "dict"):
                request_dict = request_data.dict()  # type: ignore
            else:
                request_dict = dict(request_data)  # type: ignore
            request_data = dict_to_domain_chat_request(
                self._ensure_string_keys_and_values(request_dict)
            )
        request_data = cast(ChatRequest, request_data)

        payload = self._prepare_payload(
            request_data, processed_messages, effective_model
        )
        headers = kwargs.pop("headers_override", None)
        if headers is None:
            try:
                if identity:
                    self.identity = identity
                headers = self.get_headers()
            except Exception:
                headers = None

        api_base = kwargs.get("openai_url") or self.api_base_url
        url = f"{api_base.rstrip('/')}/chat/completions"

        if request_data.stream:
            # Return a domain-level streaming envelope (raw bytes iterator)
            try:
                content_iterator = await self._handle_streaming_response(
                    url, payload, headers, request_data.session_id or ""
                )
            except AuthenticationError as e:
                raise HTTPException(status_code=401, detail=str(e))
            return StreamingResponseEnvelope(
                content=content_iterator,
                media_type="text/event-stream",
                headers={},
            )
        else:
            # Return a domain ResponseEnvelope for non-streaming
            return await self._handle_non_streaming_response(
                url, payload, headers, request_data.session_id or ""
            )

    async def _handle_non_streaming_response(
        self,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str] | None,
        session_id: str,
    ) -> ResponseEnvelope:
        if not headers or not headers.get("Authorization"):
            raise AuthenticationError(message="No auth credentials found")

        try:
            response = await self.client.post(url, json=payload, headers=headers)
        except httpx.RequestError as e:
            raise ServiceUnavailableError(message=f"Could not connect to backend ({e})")

        if int(response.status_code) >= 400:
            # For backwards compatibility with existing error handlers, still use HTTPException here.
            # This will be replaced in a future update with domain exceptions.
            try:
                err = response.json()
            except Exception:
                err = response.text
            raise HTTPException(status_code=response.status_code, detail=err)

        if self._response_processor:
            processed_response = await self._response_processor.process_response(
                response.json(), session_id=session_id
            )
            return ResponseEnvelope(
                content=processed_response.content,
                status_code=response.status_code,
                headers=dict(response.headers),
                usage=processed_response.usage,
                metadata=processed_response.metadata,
            )
        else:
            return ResponseEnvelope(
                content=response.json(),
                status_code=response.status_code,
                headers=dict(response.headers),
            )

    async def _handle_streaming_response(
        self,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str] | None,
        session_id: str,
    ) -> AsyncIterator[ProcessedResponse]:
        """Return an AsyncIterator of ProcessedResponse objects (transport-agnostic)"""

        if not headers or not headers.get("Authorization"):
            raise AuthenticationError(message="No auth credentials found")

        request = self.client.build_request("POST", url, json=payload, headers=headers)
        response = await self.client.send(request, stream=True)

        status_code = (
            int(response.status_code) if hasattr(response, "status_code") else 200
        )
        if status_code >= 400:
            # For backwards compatibility with existing error handlers, still use HTTPException here.
            # This will be replaced in a future update with domain exceptions.
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

        async def gen() -> AsyncGenerator[ProcessedResponse, None]:
            # Forward raw text stream; central pipeline will handle normalization/repairs
            async def text_generator() -> AsyncGenerator[str, None]:
                async for chunk in response.aiter_text():
                    yield chunk

            try:
                async for chunk in text_generator():
                    yield ProcessedResponse(content=chunk)
            finally:
                import contextlib

                with contextlib.suppress(Exception):
                    await response.aclose()

        # For streaming responses, return raw bytes; response processing is
        # handled at the adapter layer if needed.
        return gen()

    async def list_models(self, api_base_url: str | None = None) -> dict[str, Any]:
        headers = self.get_headers()
        base = api_base_url or self.api_base_url
        logger.info(f"OpenAIConnector list_models - base URL: {base}")
        response = await self.client.get(f"{base.rstrip('/')}/models", headers=headers)
        response.raise_for_status()
        result = response.json()
        return result  # type: ignore[no-any-return]


backend_registry.register_backend("openai", OpenAIConnector)
