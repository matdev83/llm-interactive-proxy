"""Contract for dynamic compression config resolution."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Protocol

from src.core.domain.configuration.dynamic_compression_config import (
    DynamicCompressionConfig,
)

if TYPE_CHECKING:
    from src.core.services.dynamic_compression_config_resolver import (
        ResolvedDynamicCompressionConfig,
    )


class ICompressionConfigProvider(Protocol):
    """Provide resolved runtime compression configuration snapshots."""

    def create_runtime_snapshot(
        self,
        config: DynamicCompressionConfig,
    ) -> DynamicCompressionConfig:
        """Return immutable per-request config snapshot."""
        ...

    def resolve(
        self,
        config: DynamicCompressionConfig,
        *,
        available_methods: Iterable[str],
    ) -> ResolvedDynamicCompressionConfig:
        """Normalize config and collect non-fatal diagnostics."""
        ...
