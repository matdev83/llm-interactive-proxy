"""Contract for deterministic compression rule evaluation."""

from __future__ import annotations

from typing import Protocol

from src.core.domain.configuration.dynamic_compression_config import (
    CompressionRule,
    DynamicCompressionConfig,
)
from src.core.domain.dynamic_compression import ToolOutputContext


class ICompressionRuleEvaluator(Protocol):
    """Select a matching compression rule from runtime config."""

    def select_rule(
        self,
        context: ToolOutputContext,
        config: DynamicCompressionConfig,
    ) -> CompressionRule | None:
        """Return one matching rule using deterministic ordering."""
        ...
