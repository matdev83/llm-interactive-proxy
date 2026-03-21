"""Nvidia NIM OpenAI-compatible backend connector."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import httpx

from src.connectors.openai import OpenAIConnector
from src.core.config.app_config import AppConfig
from src.core.domain.chat import CanonicalChatRequest
from src.core.domain.models_listing import ModelsListingResponse
from src.core.services.backend_registry import backend_registry

if TYPE_CHECKING:
    from src.connectors.contracts import ConnectorRequestContext
    from src.core.services.translation_service import TranslationService

NVIDIA_DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1"

# Match shared DI / infrastructure defaults so NVIDIA-only client behaves like the pool.
_NVIDIA_HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=60.0, write=60.0, pool=60.0)
_NVIDIA_HTTP_LIMITS = httpx.Limits(max_connections=100, max_keepalive_connections=20)


def _normalize_nvidia_api_key(value: str) -> str:
    """Strip whitespace and a leading ``Bearer `` prefix (common copy-paste mistake)."""

    s = value.strip()
    lower = s.lower()
    if lower.startswith("bearer "):
        s = s[7:].lstrip()
    return s


class NvidiaConnector(OpenAIConnector):
    """Connector for NVIDIA-hosted NIM OpenAI-compatible inference API."""

    backend_type: str = "nvidia"

    # Multi-vendor gateway: upstream model ids are already vendor-qualified
    VENDOR_PREFIX: str | None = None

    def __init__(
        self,
        client: httpx.AsyncClient,
        config: AppConfig,
        translation_service: TranslationService | None = None,
    ) -> None:
        super().__init__(client, config, translation_service=translation_service)
        self.api_base_url = NVIDIA_DEFAULT_BASE_URL
        # Dedicated client: NVIDIA integrator often drops HTTP/2 mid-stream
        # (``RemoteProtocolError: Server disconnected`` in httpcore's HTTP/2 stack)
        # on large chat bodies; HTTP/1.1 is stable for the same traffic.
        self._nvidia_http11_client: httpx.AsyncClient | None = None

    async def initialize(self, **kwargs: Any) -> None:
        """Initialize connector, falling back to NVIDIA_API_KEY when no key in kwargs."""

        raw = kwargs.get("api_key")
        if isinstance(raw, str):
            norm = _normalize_nvidia_api_key(raw)
            kwargs["api_key"] = norm if norm else None

        if not kwargs.get("api_key"):
            env_key = os.getenv("NVIDIA_API_KEY")
            if env_key:
                kwargs["api_key"] = _normalize_nvidia_api_key(env_key)

        kwargs.setdefault("api_base_url", self.api_base_url)
        self._ensure_nvidia_http11_client()
        await super().initialize(**kwargs)

    def _ensure_nvidia_http11_client(self) -> None:
        """Use HTTP/1.1 for NVIDIA only; keep timeouts/limits aligned with the shared client."""

        if not isinstance(self.client, httpx.AsyncClient):
            return
        dedicated = self._nvidia_http11_client
        if dedicated is not None and not dedicated.is_closed:
            self.client = dedicated
            return
        if dedicated is not None:
            self._nvidia_http11_client = None

        base = self.client
        timeout = getattr(base, "timeout", None) or _NVIDIA_HTTP_TIMEOUT
        limits = getattr(base, "limits", None) or _NVIDIA_HTTP_LIMITS
        self._nvidia_http11_client = httpx.AsyncClient(
            http2=False,
            timeout=timeout,
            limits=limits,
            trust_env=False,
        )
        self.client = self._nvidia_http11_client

    async def close(self) -> None:
        """Close the NVIDIA-only client in addition to OpenAI connector resources."""

        nvidia_client = self._nvidia_http11_client
        self._nvidia_http11_client = None
        if nvidia_client is not None and not nvidia_client.is_closed:
            await nvidia_client.aclose()
        await super().close()

    async def list_models(
        self, api_base_url: str | None = None
    ) -> ModelsListingResponse:
        """Ensure HTTP/1.1 client before ``GET /models`` (may run outside ``initialize`` in tests)."""

        self._ensure_nvidia_http11_client()
        return await super().list_models(api_base_url)

    async def _prepare_payload(
        self,
        request_data: CanonicalChatRequest,
        processed_messages: list[Any],
        effective_model: str,
        context: ConnectorRequestContext | None = None,
    ) -> dict[str, Any]:
        """Build JSON body for NVIDIA NIM; strict schema rejects some OpenAI Chat fields."""

        payload = await super()._prepare_payload(
            request_data, processed_messages, effective_model, context
        )
        # Hosted integrator returns 400 extra_forbidden for max_completion_tokens (Pydantic strict).
        mct = payload.pop("max_completion_tokens", None)
        if mct is not None and payload.get("max_tokens") is None:
            payload["max_tokens"] = mct
        # Strict OpenAI-compat schema on hosted NIM often rejects Chat Completions extensions
        # that the generic OpenAI connector adds (unknown keys -> 422/extra_forbidden).
        payload.pop("stream_options", None)
        return payload


backend_registry.register_backend("nvidia", NvidiaConnector)
