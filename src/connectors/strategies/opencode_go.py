"""OpenCode Go backend initialization strategy."""

from __future__ import annotations

from typing import Any

from src.connectors.strategies.registry import initialization_strategy_registry


class OpencodeGoInitializationStrategy:
    """Initialization strategy for opencode-go backend connectors."""

    def augment_init_config(self, init_config: dict[str, Any]) -> dict[str, Any]:
        augmented = dict(init_config)
        augmented.setdefault("key_name", "opencode-go")
        augmented.setdefault("api_base_url", "https://opencode.ai/zen/go/v1")
        augmented.setdefault("anthropic_api_base_url", "https://opencode.ai/zen/go/v1")
        return augmented


_opencode_go_strategy = OpencodeGoInitializationStrategy()
initialization_strategy_registry.register_strategy("opencode-go", _opencode_go_strategy)
