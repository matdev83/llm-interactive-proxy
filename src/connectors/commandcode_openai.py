"""CommandCode OpenAI-compatible backend connector."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

import httpx

from src.connectors.openai import OpenAIConnector
from src.core.config.app_config import AppConfig
from src.core.services.backend_registry import backend_registry

if TYPE_CHECKING:
    from src.core.services.translation_service import TranslationService

logger = logging.getLogger(__name__)

COMMANDCODE_OPENAI_BACKEND_TYPE = "commandcode-openai"
COMMANDCODE_API_KEY_ENV = "COMMANDCODE_API_KEY"
COMMANDCODE_OPENAI_DEFAULT_BASE_URL = "https://api.commandcode.ai/provider/v1"


class CommandCodeOpenAIConnector(OpenAIConnector):
    """Connector for CommandCode's OpenAI Chat Completions-compatible API."""

    backend_type: str = COMMANDCODE_OPENAI_BACKEND_TYPE

    # Multi-vendor gateway: upstream model IDs are already vendor-qualified
    VENDOR_PREFIX: str | None = None

    def __init__(
        self,
        client: httpx.AsyncClient,
        config: AppConfig,
        translation_service: TranslationService | None = None,
    ) -> None:
        super().__init__(client, config, translation_service=translation_service)
        self.api_base_url = COMMANDCODE_OPENAI_DEFAULT_BASE_URL

    async def initialize(self, **kwargs: Any) -> None:
        """Initialize connector, falling back to COMMANDCODE_API_KEY env var if needed."""
        if not kwargs.get("api_key"):
            env_key = os.getenv(COMMANDCODE_API_KEY_ENV)
            if env_key:
                kwargs["api_key"] = env_key.strip()

        kwargs.setdefault("api_base_url", self.api_base_url)
        await super().initialize(**kwargs)


backend_registry.register_backend("commandcode-openai", CommandCodeOpenAIConnector)
backend_registry.register_backend("commandcode_openai", CommandCodeOpenAIConnector)
backend_registry.register_backend("commandcode", CommandCodeOpenAIConnector)
