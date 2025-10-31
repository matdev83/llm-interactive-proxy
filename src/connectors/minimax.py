"""
Minimax connector for Minimax AI models.
"""

from typing import TYPE_CHECKING

import httpx

from src.core.config.app_config import AppConfig
from src.core.services.backend_registry import backend_registry

from .openai import OpenAIConnector

if TYPE_CHECKING:
    from src.core.services.translation_service import TranslationService


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


backend_registry.register_backend("minimax", MinimaxConnector)
