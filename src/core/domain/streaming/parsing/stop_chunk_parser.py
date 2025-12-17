"""
Stop chunk parser for StopChunkWithUsage instances.

This parser handles StopChunkWithUsage instances, preserving them as-is
to prevent usage data from leaking into delta.content.
"""

from __future__ import annotations

import logging
from typing import Any

from src.core.domain.streaming.parsing.parser_strategy import IParserStrategy
from src.core.domain.streaming.stop_chunk_with_usage import (
    StopChunkWithUsage,
)
from src.core.domain.streaming.streaming_content import StreamingContent

logger = logging.getLogger(__name__)


class StopChunkParser(IParserStrategy):
    """Parser for StopChunkWithUsage instances.

    CRITICAL: This parser must check for StopChunkWithUsage BEFORE generic
    dict parsers to prevent usage data from being extracted and lost.
    StopChunkWithUsage is a dict subclass that must be preserved as-is.
    """

    def can_parse(self, raw_data: Any) -> bool:
        """Check if input is a StopChunkWithUsage instance.

        Args:
            raw_data: The raw data to check

        Returns:
            True if raw_data is a StopChunkWithUsage instance
        """
        return isinstance(raw_data, StopChunkWithUsage)

    def parse(self, raw_data: Any) -> StreamingContent:
        """Parse StopChunkWithUsage into StreamingContent.

        Preserves the StopChunkWithUsage directly as content to prevent
        usage data from leaking into delta.content.

        Args:
            raw_data: StopChunkWithUsage instance

        Returns:
            StreamingContent with StopChunkWithUsage as content

        Raises:
            ValueError: If raw_data is not a StopChunkWithUsage instance
        """
        if not isinstance(raw_data, StopChunkWithUsage):
            raise ValueError(
                f"Expected StopChunkWithUsage, got {type(raw_data).__name__}"
            )

        logger.debug(
            "[STREAMING] StreamingContent.from_raw: Preserving StopChunkWithUsage (direct), "
            "chunk_id=%s, has_usage=%s",
            raw_data.get("id", "unknown"),
            "usage" in raw_data,
        )

        return StreamingContent(
            content=raw_data,  # Keep as StopChunkWithUsage
            is_done=True,  # Stop chunks are always final
            metadata={
                "id": raw_data.get("id"),
                "model": raw_data.get("model"),
                "created": raw_data.get("created"),
                "finish_reason": "stop",
            },
            usage=raw_data.get("usage"),
        )


__all__ = ["StopChunkParser"]

