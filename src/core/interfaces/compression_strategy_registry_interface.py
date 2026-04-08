"""Contracts for dynamic compression strategy registry."""

from __future__ import annotations

from typing import Protocol

from src.core.domain.configuration.dynamic_compression_config import CompressionLevel
from src.core.domain.dynamic_compression import ToolOutputContext


class CompressionStrategy(Protocol):
    """Protocol implemented by individual compression strategies."""

    def compress(
        self,
        content: str,
        *,
        context: ToolOutputContext,
        level: CompressionLevel,
    ) -> str:
        """Return compressed content for one method invocation."""
        ...


class ICompressionStrategyRegistry(Protocol):
    """Registry contract for compression methods."""

    def register(self, method_name: str, strategy: CompressionStrategy) -> None:
        """Register a strategy by deterministic method name."""
        ...

    def get(self, method_name: str) -> CompressionStrategy | None:
        """Return strategy for method name when available."""
        ...

    def available_method_names(self) -> list[str]:
        """Return sorted list of registered method names."""
        ...
