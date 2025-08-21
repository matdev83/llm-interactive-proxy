"""
ZAI connector for Zhipu AI's GLM models
"""

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

from src.core.common.exceptions import AuthenticationError, ConfigurationError
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.services.backend_registry import backend_registry

from .openai import OpenAIConnector

if TYPE_CHECKING:
    pass


class ZAIConnector(OpenAIConnector):
    """ZAI backend connector for Zhipu AI's GLM models."""

    backend_type: str = "zai"

    def __init__(self, client: httpx.AsyncClient) -> None:
        super().__init__(client)
        self.api_base_url = "https://open.bigmodel.cn/api/paas/v4/"
        self.name = "zai"
        # Load default models from JSON config file
        self._default_models = self._load_default_models()

    def _load_default_models(self) -> list[str]:
        """Load default models from JSON configuration file."""
        config_path = (
            Path(__file__).parent.parent.parent
            / "config"
            / "backends"
            / "zai"
            / "default_models.json"
        )
        try:
            with open(config_path, encoding="utf-8") as f:
                config = json.load(f)
                models = config.get("models", [])
                if isinstance(models, list) and models:
                    return models
                # If the config file exists but has no models, fall back to hardcoded defaults
                return ["glm-4.5", "glm-4.5-flash", "glm-4.5-air"]
        except Exception:
            # Fallback to hardcoded models if config file is not found or invalid
            return ["glm-4.5", "glm-4.5-flash", "glm-4.5-air"]

    async def initialize(self, **kwargs: Any) -> None:
        """Initialize the connector and fetch available models."""
        self.api_key = kwargs.get("api_key")
        if not self.api_key:
            raise ConfigurationError(
                message="api_key is required for ZAIConnector", code="missing_api_key"
            )

        api_base_url = kwargs.get("api_base_url")
        if api_base_url:
            self.api_base_url = api_base_url

        # Load models
        await self._ensure_models_loaded()

    async def _ensure_models_loaded(self) -> None:
        """Ensure models are loaded, either from API or defaults."""
        # Initialize available_models if not already set
        if not hasattr(self, "available_models"):
            self.available_models = []

        # If we already have models, no need to reload
        if self.available_models:
            return

        # Try to fetch models from /models endpoint
        try:
            data = await self.list_models()
            models = [m.get("id") for m in data.get("data", []) if m.get("id")]
            # If we successfully fetched models, use them
            if models:
                self.available_models = models
                return
        except Exception as e:
            # Log the exception for debugging
            import logging

            logging.debug(f"Error fetching models from API: {e}")

        # If we get here, either the API call failed or returned no models
        # Use default models from config
        if not self.available_models:
            self.available_models = self._default_models.copy()

    def get_headers(self) -> dict[str, str]:
        """Get headers with ZAI API key."""
        if not self.api_key:
            raise AuthenticationError(
                message="ZAI API key is not set.", code="missing_api_key"
            )
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def get_available_models(self) -> list[str]:
        """
        Get a list of available models for this backend.

        Returns:
            A list of model identifiers supported by this backend.
        """
        if hasattr(self, "available_models") and self.available_models:
            return self.available_models
        return self._default_models.copy()

    async def chat_completions(
        self,
        request_data: Any,
        processed_messages: list[Any],
        effective_model: str,
        **kwargs: Any,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        return await super().chat_completions(
            request_data=request_data,
            processed_messages=processed_messages,
            effective_model=effective_model,
            **kwargs,
        )


backend_registry.register_backend("zai", ZAIConnector)
