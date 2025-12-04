"""ZenMux backend connector."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

import httpx

from src.connectors.openai import OpenAIConnector
from src.core.config.app_config import AppConfig
from src.core.interfaces.configuration_interface import IAppIdentityConfig
from src.core.services.backend_registry import backend_registry

if TYPE_CHECKING:
    from src.core.services.translation_service import TranslationService

logger = logging.getLogger(__name__)

ZENMUX_DEFAULT_BASE_URL = "https://zenmux.ai/api/v1"


class ZenmuxConnector(OpenAIConnector):
    """Connector for ZenMux's OpenAI-compatible API."""

    backend_type: str = "zenmux"

    # ZenMux is a multi-vendor gateway - models are already prefixed from upstream
    VENDOR_PREFIX: str | None = None

    def __init__(
        self,
        client: httpx.AsyncClient,
        config: AppConfig,
        translation_service: TranslationService | None = None,
    ) -> None:
        super().__init__(client, config, translation_service=translation_service)
        # Docs confirm the OpenAI-compatible endpoints live under /api/v1
        # (see https://docs.zenmux.ai/api-reference/overview#requests)
        self.api_base_url = ZENMUX_DEFAULT_BASE_URL

    async def initialize(self, **kwargs: Any) -> None:
        """Initialize connector, falling back to the ZENMUX_API_KEY env var if needed."""

        # Allow explicit API key overrides first, but fall back to env var to honor
        # the documented setup flow (ZENMUX_API_KEY required at startup).
        if not kwargs.get("api_key"):
            env_key = os.getenv("ZENMUX_API_KEY")
            if env_key:
                kwargs["api_key"] = env_key

        # ZenMux exposes /api/v1/models just like OpenAI (docs reference the endpoint
        # directly), so we can rely on the parent initialization for discovery.
        kwargs.setdefault("api_base_url", self.api_base_url)
        await super().initialize(**kwargs)

    def _build_identity_header_defaults(self) -> dict[str, str]:
        referer = "http://localhost:8000"
        title = "LLM Interactive Proxy"

        identity_config = getattr(self.config, "identity", None)
        if identity_config is not None:
            referer = (
                getattr(getattr(identity_config, "url", None), "default_value", referer)
                or referer
            )
            title = (
                getattr(getattr(identity_config, "title", None), "default_value", title)
                or title
            )
        return {"HTTP-Referer": referer, "X-Title": title}

    def get_headers(self, identity: IAppIdentityConfig | None = None) -> dict[str, str]:
        """Add ZenMux-specific identification headers."""

        headers = super().get_headers(identity=identity)
        defaults = self._build_identity_header_defaults()
        for key, value in defaults.items():
            headers.setdefault(key, value)
        return headers


backend_registry.register_backend("zenmux", ZenmuxConnector)
