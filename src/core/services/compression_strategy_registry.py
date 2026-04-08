"""Registry for dynamic compression strategies."""

from __future__ import annotations

import logging

from src.core.interfaces.compression_strategy_registry_interface import (
    CompressionStrategy,
)

logger = logging.getLogger(__name__)


class CompressionStrategyRegistry:
    """Deterministic strategy registry keyed by method name.

    Custom strategies can be registered at runtime (for example via
    :meth:`register_extension_strategy`) and referenced from
    ``dynamic_compression.rules`` pipelines without changing
    :class:`~src.core.services.tool_output_compression_service.ToolOutputCompressionService`.
    """

    def __init__(self) -> None:
        self._strategies: dict[str, CompressionStrategy] = {}

    def register_extension_strategy(
        self, method_name: str, strategy: CompressionStrategy
    ) -> None:
        """Register a custom compression method for config-driven rule pipelines.

        This is the supported extension entry point: add the method here, then
        reference it by name in ``CompressionRule.pipeline`` in configuration.
        """
        self.register(method_name, strategy)

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
