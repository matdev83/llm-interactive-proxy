from __future__ import annotations

import logging
import os
from typing import Any

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

    def get_provider_name(self) -> str:
        """Return the provider name for logging/metrics."""
        return "openai"


backend_registry.register_backend("kimi-code", KimiCodeConnector)
