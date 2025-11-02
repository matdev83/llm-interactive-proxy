"""
Minimax connector for Minimax AI models.
"""

import logging
from typing import TYPE_CHECKING, Any

import httpx

from src.core.config.app_config import AppConfig
from src.core.services.backend_registry import backend_registry

from .openai import OpenAIConnector

if TYPE_CHECKING:
    from src.core.services.translation_service import TranslationService


logger = logging.getLogger(__name__)


class MinimaxConnector(OpenAIConnector):
    """Minimax backend connector for Minimax AI models."""

    backend_type: str = "minimax"

    def __init__(
        self,
        client: httpx.AsyncClient,
        config: AppConfig,
        translation_service: "TranslationService | None" = None,
    ) -> None:
        super().__init__(client, config, translation_service=translation_service)
        self.api_base_url = "https://api.minimax.io/v1"
        self.name = "minimax"

        # Minimax API does not expose a /models listing endpoint; skip health checks
        self.disable_health_check()

    async def initialize(self, **kwargs: Any) -> None:
        """Initialize the connector without performing model discovery."""

        self.api_key = kwargs.get("api_key")
        if "api_base_url" in kwargs:
            self.api_base_url = kwargs["api_base_url"]

        logger.info(
            "MinimaxConnector initialize called. api_key_provided=%s",
            "yes" if self.api_key else "no",
        )

        # The Minimax API does not provide a model listing endpoint and returns 404.
        # Avoid calling the base implementation which would log spurious warnings.
        if self.api_key:
            logger.debug(
                "Skipping Minimax model discovery (endpoint not supported by provider)"
            )
        self.available_models = []

    async def _perform_health_check(self) -> bool:
        """Perform a lightweight health check by hitting the chat endpoint with minimal payload."""

        if not self.api_key:
            logger.debug(
                "Skipping Minimax health check because no API key is configured"
            )
            return True

        try:
            headers = self.get_headers()
            payload = {
                "model": "MiniMax-M2",
                "messages": [
                    {"role": "system", "content": "health check"},
                    {"role": "user", "content": "ping"},
                ],
                "stream": False,
                "max_tokens": 1,
            }
            response = await self.client.post(
                f"{self.api_base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=10.0,
            )
            response.raise_for_status()
        except Exception as exc:
            logger.warning("Minimax health check failed: %s", exc, exc_info=True)
            return False

        logger.debug("Minimax health check succeeded")
        return True


backend_registry.register_backend("minimax", MinimaxConnector)
