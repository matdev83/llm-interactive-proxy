from __future__ import annotations

import contextlib
import logging
import os
from collections.abc import AsyncGenerator
from typing import Any

import httpx
from fastapi import HTTPException

from src.connectors.base import strip_vendor_prefix
from src.connectors.contracts import ConnectorRequestContext
from src.core.common.exceptions import AuthenticationError, ServiceUnavailableError
from src.core.domain.chat import CanonicalChatRequest
from src.core.domain.responses import ResponseEnvelope
from src.core.interfaces.configuration_interface import IAppIdentityConfig
from src.core.security.loop_prevention import LOOP_GUARD_HEADER
from src.core.services.backend_registry import backend_registry

from .openai import OpenAIConnector

logger = logging.getLogger(__name__)


class KimiCodeConnector(OpenAIConnector):
    """Connector for Kimi Code API.

    Subclasses OpenAIConnector and uses Kimi-specific URL and credentials.
    """

    backend_type: str = "kimi-code"

    # Vendor prefix for model names in unified model routing.
    VENDOR_PREFIX: str | None = "kimi"

    # Kimi-for-coding appears gated behind coding-agent fingerprints.
    # In practice, Kilo Code / Roo Code / Cline clients send additional headers.
    _KILO_VERSION: str = "4.111.0"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._api_base_url = "https://api.kimi.com/coding/v1"

    async def initialize(self, **kwargs: Any) -> None:
        """Initialize the connector with KIMI_API_KEY from environment."""
        # Check environment variable first as requested
        api_key = os.getenv("KIMI_API_KEY") or kwargs.get("api_key")

        if "api_base_url" in kwargs:
            self.api_base_url = kwargs["api_base_url"]

        self.api_key = api_key

        # Hardcode the list of models as requested
        self.available_models = ["kimi-for-coding"]

        if not self.api_key and logger.isEnabledFor(logging.WARNING):
            logger.warning(
                "Kimi Code connector initialized without an API key (KIMI_API_KEY not found)"
            )

    def get_headers(self, identity: IAppIdentityConfig | None = None) -> dict[str, str]:
        """Return request headers identifying as a coding agent.

        Important: OpenAIConnector will add the loop-guard header at multiple call sites.
        For Kimi, we avoid adding it here and strip it again at the final send step.
        """

        headers: dict[str, str] = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        if identity is not None:
            try:
                identity_headers = dict(identity.get_resolved_headers(None))
            except (KeyError, TypeError, AttributeError):
                identity_headers = {}
            headers.update(identity_headers)

        # Mimic Kilo Code request fingerprint (known to work against Kimi's coding gateway).
        headers["User-Agent"] = f"Kilo-Code/{self._KILO_VERSION}"
        headers["Referer"] = "https://kilocode.ai"
        headers["Origin"] = "https://kilocode.ai"
        headers["HTTP-Referer"] = "https://kilocode.ai"
        headers["X-Title"] = "Kilo Code"
        headers["X-KiloCode-Version"] = self._KILO_VERSION

        headers.pop(LOOP_GUARD_HEADER, None)
        return headers

    async def _handle_non_streaming_response(
        self,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str] | None,
        session_id: str,
        context: ConnectorRequestContext | None = None,
    ) -> ResponseEnvelope:
        """Override to avoid injecting loop-guard header for Kimi."""
        if not headers or not headers.get("Authorization"):
            raise AuthenticationError(message="No auth credentials found")

        safe_headers = dict(headers)
        safe_headers.pop(LOOP_GUARD_HEADER, None)

        try:
            response = await self.client.post(url, json=payload, headers=safe_headers)
        except httpx.RequestError as exc:
            raise ServiceUnavailableError(
                message=f"Could not connect to backend ({exc})"
            ) from exc

        if int(response.status_code) >= 400:
            try:
                err = response.json()
            except Exception:
                err = response.text
            raise HTTPException(status_code=response.status_code, detail=err)

        response_json = response.json()
        domain_response = self.translation_service.to_domain_response(
            response_json, "openai"
        )
        try:
            response_headers = dict(response.headers)
        except Exception:
            response_headers = {}

        return ResponseEnvelope(
            content=domain_response.model_dump(),
            status_code=response.status_code,
            headers=response_headers,
            usage=domain_response.usage,
        )

    async def stream_completion(
        self, request: CanonicalChatRequest
    ) -> AsyncGenerator[object, None]:
        """Stream SSE chunks from Kimi without the proxy loop-guard header."""

        api_base = getattr(request, "api_base", None) or self.api_base_url
        url = f"{api_base.rstrip('/')}/chat/completions"

        headers = self.get_headers(identity=getattr(request, "identity", None))
        if not headers.get("Authorization"):
            raise AuthenticationError(message="No auth credentials found")

        headers = dict(headers)
        headers.pop(LOOP_GUARD_HEADER, None)
        headers.setdefault("Accept", "text/event-stream")

        payload = await self._prepare_payload(
            request, request.messages, request.model, context=None
        )
        payload["stream"] = True

        http_request = self.client.build_request(
            "POST", url, json=payload, headers=headers
        )

        try:
            response = await self.client.send(http_request, stream=True)
        except httpx.RequestError as exc:
            raise ServiceUnavailableError(
                message=f"Could not connect to backend ({exc})"
            ) from exc

        status_code = int(getattr(response, "status_code", 200))
        if status_code >= 400:
            body_text = ""
            try:
                body_text = (await response.aread()).decode("utf-8", errors="replace")
            except Exception:
                body_text = str(getattr(response, "text", ""))
            finally:
                with contextlib.suppress(BaseException):
                    await response.aclose()
            raise HTTPException(
                status_code=status_code,
                detail={
                    "message": body_text,
                    "type": "openai_error",
                    "code": status_code,
                },
            )

        try:
            async for chunk_bytes in response.aiter_bytes():
                yield chunk_bytes
        finally:
            with contextlib.suppress(BaseException):
                await response.aclose()

    async def _prepare_payload(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """Strip vendor prefix from model name before sending to Kimi."""
        payload = await super()._prepare_payload(*args, **kwargs)
        if self.VENDOR_PREFIX and "model" in payload:
            payload["model"] = strip_vendor_prefix(payload["model"], self.VENDOR_PREFIX)
        return payload

    def get_provider_name(self) -> str:
        """Return the provider name for logging/metrics."""
        return "openai"


backend_registry.register_backend("kimi-code", KimiCodeConnector)
