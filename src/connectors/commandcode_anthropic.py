"""CommandCode Anthropic Messages-compatible backend connector."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

import httpx

from src.connectors.anthropic import AnthropicBackend
from src.core.common.exceptions import ConfigurationError
from src.core.config.app_config import AppConfig
from src.core.services.backend_registry import backend_registry

if TYPE_CHECKING:
    from src.core.services.translation_service import TranslationService

logger = logging.getLogger(__name__)

COMMANDCODE_ANTHROPIC_BACKEND_TYPE = "commandcode-anthropic"
COMMANDCODE_API_KEY_ENV = "COMMANDCODE_API_KEY"
COMMANDCODE_ANTHROPIC_DEFAULT_BASE_URL = "https://api.commandcode.ai/provider/v1"


class CommandCodeAnthropicConnector(AnthropicBackend):
    """Connector for CommandCode's Anthropic Messages-compatible API."""

    backend_type: str = COMMANDCODE_ANTHROPIC_BACKEND_TYPE

    # Multi-vendor gateway: upstream model IDs are already vendor-qualified
    VENDOR_PREFIX: str | None = None

    def __init__(
        self,
        client: httpx.AsyncClient,
        config: AppConfig,
        translation_service: TranslationService,
    ) -> None:
        super().__init__(client, config, translation_service)
        self.available_models: list[str] = []

    async def initialize(self, **kwargs: Any) -> None:
        """Initialize connector, falling back to COMMANDCODE_API_KEY env var if needed."""
        api_key = kwargs.get("api_key")
        if not api_key:
            env_key = os.getenv(COMMANDCODE_API_KEY_ENV)
            if env_key:
                api_key = env_key.strip()

        if not api_key:
            raise ConfigurationError(
                message=f"{COMMANDCODE_API_KEY_ENV} is required for {COMMANDCODE_ANTHROPIC_BACKEND_TYPE}",
                code="missing_config",
            )

        base_url = str(
            kwargs.get("anthropic_api_base_url")
            or kwargs.get("api_base_url")
            or COMMANDCODE_ANTHROPIC_DEFAULT_BASE_URL
        ).rstrip("/")

        await super().initialize(
            anthropic_api_base_url=base_url,
            key_name=COMMANDCODE_ANTHROPIC_BACKEND_TYPE,
            api_key=api_key,
            auth_header_name="x-api-key",
        )

        try:
            await self.list_models(
                base_url=base_url, key_name=self.key_name, api_key=self.api_key
            )
        except Exception as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Failed to fetch CommandCode Anthropic models at startup: %s", e
                )

    def get_available_models(self) -> list[str]:
        """Return cached CommandCode model IDs without adding synthetic anthropic/ prefix."""
        return list(self.available_models)

    async def get_available_models_async(self) -> list[str]:
        """Return CommandCode model IDs without adding synthetic anthropic/ prefix."""
        await self._ensure_models_loaded()
        return list(self.available_models)


backend_registry.register_backend(
    "commandcode-anthropic", CommandCodeAnthropicConnector
)
backend_registry.register_backend(
    "commandcode_anthropic", CommandCodeAnthropicConnector
)
