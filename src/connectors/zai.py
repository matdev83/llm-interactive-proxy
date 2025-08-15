"""
ZAI connector for Zhipu AI's GLM models
"""

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
from fastapi import HTTPException

from .openai import OpenAIConnector

if TYPE_CHECKING:
    pass


class ZAIConnector(OpenAIConnector):
    """ZAI backend connector for Zhipu AI's GLM models."""

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
                return models if isinstance(models, list) else []
        except Exception:
            # Fallback to hardcoded models if config file is not found or invalid
            return ["glm-4.5-flash", "glm-4.5-air", "glm-4.5"]

    async def initialize(self, **kwargs: Any) -> None:
        """Initialize the connector and fetch available models."""
        self.api_key = kwargs.get("api_key")
        if not self.api_key:
            raise ValueError("api_key is required for ZAIConnector")
        
        api_base_url = kwargs.get("api_base_url")
        if api_base_url:
            self.api_base_url = api_base_url

        # Try to fetch models from /models endpoint
        try:
            data = await self.list_models()
            self.available_models = [
                m.get("id") for m in data.get("data", []) if m.get("id")
            ]
            # If we successfully fetched models, use them
            if self.available_models:
                return
        except Exception:
            # If /models endpoint is not supported, use default models from config
            self.available_models = self._default_models.copy()

    def get_headers(self) -> dict[str, str]:
        """Get headers with ZAI API key."""
        if not self.api_key:
            raise HTTPException(status_code=500, detail="API key is not set.")
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
