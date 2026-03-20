"""Nvidia NIM OpenAI-compatible backend connector."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import httpx

from src.connectors.openai import OpenAIConnector
from src.core.config.app_config import AppConfig
from src.core.domain.chat import CanonicalChatRequest
from src.core.services.backend_registry import backend_registry

if TYPE_CHECKING:
    from src.connectors.contracts import ConnectorRequestContext
    from src.core.services.translation_service import TranslationService

NVIDIA_DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1"


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
        await super().initialize(**kwargs)

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
        return payload


backend_registry.register_backend("nvidia", NvidiaConnector)
