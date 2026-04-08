"""Registry for dynamic compression strategies."""

from __future__ import annotations

import logging

from src.core.interfaces.compression_strategy_registry_interface import (
    CompressionStrategy,
)

logger = logging.getLogger(__name__)


class CompressionStrategyRegistry:
    """Deterministic strategy registry keyed by method name."""

    def __init__(self) -> None:
        self._strategies: dict[str, CompressionStrategy] = {}

    def register(self, method_name: str, strategy: CompressionStrategy) -> None:
        normalized = method_name.strip()
        if not normalized:
            raise ValueError("method_name cannot be empty")
        if normalized in self._strategies:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Compression strategy '%s' already registered; keeping existing strategy.",
                    normalized,
                )
            return
        self._strategies[normalized] = strategy

    def get(self, method_name: str) -> CompressionStrategy | None:
        return self._strategies.get(method_name.strip())

    def available_method_names(self) -> list[str]:
        return sorted(self._strategies.keys())
