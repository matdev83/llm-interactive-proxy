"""Contract for rendering compression transparency markers."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from src.core.domain.configuration.dynamic_compression_config import (
    CompressionLevel,
    CompressionMarkerConfig,
)
from src.core.domain.dynamic_compression import ToolOutputContext


class ICompressionMarkerRenderer(Protocol):
    """Render and apply human-readable compression markers."""

    def apply_marker(
        self,
        *,
        context: ToolOutputContext,
        content: str,
        marker_config: CompressionMarkerConfig,
        level: CompressionLevel,
        methods: Sequence[str],
        original_bytes: int,
        compressed_bytes: int,
    ) -> tuple[str, bool]:
        """Apply marker to content when policy allows it."""
        ...

    def render_marker(
        self,
        *,
        marker_config: CompressionMarkerConfig,
        level: CompressionLevel,
        methods: Sequence[str],
        original_bytes: int,
        compressed_bytes: int,
    ) -> str:
        """Render marker text without applying it to payload."""
        ...
