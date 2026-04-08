"""Marker rendering for dynamic compression transparency."""

from __future__ import annotations

import re
from collections.abc import Sequence

from src.core.domain.configuration.dynamic_compression_config import (
    CompressionLevel,
    CompressionMarkerConfig,
    MarkerStyle,
)
from src.core.domain.dynamic_compression import ToolOutputContentType, ToolOutputContext

_MARKER_PATTERN = re.compile(r"^\[COMPRESSED[^\]]*\]\s*", re.MULTILINE)


class MarkerRenderer:
    """Render and inject deterministic compression markers."""

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
        if not marker_config.enabled:
            return content, False
        if context.content_type != ToolOutputContentType.TEXT:
            return content, False
        if marker_config.style == MarkerStyle.NONE:
            return content, False

        marker = self.render_marker(
            marker_config=marker_config,
            level=level,
            methods=methods,
            original_bytes=original_bytes,
            compressed_bytes=compressed_bytes,
        )

        cleaned = _MARKER_PATTERN.sub("", content, count=1).lstrip()
        if marker_config.style == MarkerStyle.SUFFIX:
            rendered = f"{cleaned}\n{marker}" if cleaned else marker
            return rendered, True

        rendered = f"{marker}\n{cleaned}" if cleaned else marker
        return rendered, True

    def render_marker(
        self,
        *,
        marker_config: CompressionMarkerConfig,
        level: CompressionLevel,
        methods: Sequence[str],
        original_bytes: int,
        compressed_bytes: int,
    ) -> str:
        marker_tokens: list[str] = []
        if marker_config.include_sizes:
            marker_tokens.append(f"level={level.value}")
        if marker_config.include_methods and methods:
            marker_tokens.append(f"methods={','.join(methods)}")
        if marker_config.include_sizes:
            saved = max(0, original_bytes - compressed_bytes)
            marker_tokens.append(f"saved={saved}B")
        if not marker_tokens:
            return "[COMPRESSED]"
        return f"[COMPRESSED {' '.join(marker_tokens)}]"
