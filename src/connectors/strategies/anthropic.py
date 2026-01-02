"""Anthropic backend initialization strategy."""

from __future__ import annotations

from typing import Any

from src.connectors.strategies.registry import initialization_strategy_registry


class AnthropicInitializationStrategy:
    """Initialization strategy for Anthropic backend connectors.

    This strategy sets the `key_name` to "anthropic" in the initialization
    configuration, preserving all other configuration values.
    """

    def augment_init_config(self, init_config: dict[str, Any]) -> dict[str, Any]:
        """Augment initialization configuration for Anthropic backend.

        Sets `key_name = "anthropic"` in the configuration, preserving all
        other existing configuration values.

        Args:
            init_config: The base initialization configuration dictionary.

        Returns:
            A new dictionary with `key_name` set to "anthropic" and all
            other values preserved.
        """
        augmented = dict(init_config)
        augmented["key_name"] = "anthropic"
        return augmented


# Register the strategy at module import time
_anthropic_strategy = AnthropicInitializationStrategy()
initialization_strategy_registry.register_strategy("anthropic", _anthropic_strategy)
