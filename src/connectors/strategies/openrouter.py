"""OpenRouter backend initialization strategy."""

from __future__ import annotations

from typing import Any

from src.connectors.strategies.registry import initialization_strategy_registry
from src.core.config.models.backends import get_openrouter_headers


class OpenRouterInitializationStrategy:
    """Initialization strategy for OpenRouter backend connectors.

    This strategy sets the `key_name` to "openrouter", sets the
    `openrouter_headers_provider` function reference, and sets a default
    `api_base_url` if not present, preserving all other configuration values.
    """

    def augment_init_config(self, init_config: dict[str, Any]) -> dict[str, Any]:
        """Augment initialization configuration for OpenRouter backend.

        Sets `key_name = "openrouter"`, `openrouter_headers_provider` to
        `get_openrouter_headers`, and default `api_base_url` if not present,
        preserving all other existing configuration values.

        Args:
            init_config: The base initialization configuration dictionary.

        Returns:
            A new dictionary with `key_name` set to "openrouter",
            `openrouter_headers_provider` set to `get_openrouter_headers`,
            default `api_base_url` set if not present, and all other values preserved.
        """
        augmented = dict(init_config)
        augmented["key_name"] = "openrouter"
        augmented["openrouter_headers_provider"] = get_openrouter_headers
        if "api_base_url" not in augmented:
            augmented["api_base_url"] = "https://openrouter.ai/api/v1"
        return augmented


# Register the strategy at module import time
_openrouter_strategy = OpenRouterInitializationStrategy()
initialization_strategy_registry.register_strategy("openrouter", _openrouter_strategy)
