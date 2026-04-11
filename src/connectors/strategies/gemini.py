"""Gemini backend initialization strategy."""

from __future__ import annotations

from typing import Any

from src.connectors.strategies.registry import initialization_strategy_registry


class GeminiInitializationStrategy:
    """Initialization strategy for Gemini backend connectors.

    This strategy sets the `key_name` to "x-goog-api-key" and handles the mapping
    of `api_base_url` to `gemini_api_base_url` for Gemini backend initialization.
    """

    def augment_init_config(self, init_config: dict[str, Any]) -> dict[str, Any]:
        """Augment initialization configuration for Gemini backend.

        Sets `key_name = "x-goog-api-key"` and maps `api_base_url` to `gemini_api_base_url`
        if present. If `gemini_api_base_url` is not present after mapping, sets
        the default value.

        Args:
            init_config: The base initialization configuration dictionary.

        Returns:
            A new dictionary with `key_name` set to "x-goog-api-key", `gemini_api_base_url`
            mapped from `api_base_url` if present, or set to default if not present,
            and all other values preserved.
        """
        augmented = dict(init_config)
        augmented["key_name"] = "x-goog-api-key"

        # Map api_base_url to gemini_api_base_url for Gemini backend
        if "api_base_url" in augmented:
            augmented["gemini_api_base_url"] = augmented["api_base_url"]
        elif "gemini_api_base_url" not in augmented:
            augmented["gemini_api_base_url"] = (
                "https://generativelanguage.googleapis.com"
            )

        return augmented


# Register the strategy at module import time
_gemini_strategy = GeminiInitializationStrategy()
initialization_strategy_registry.register_strategy("gemini", _gemini_strategy)
