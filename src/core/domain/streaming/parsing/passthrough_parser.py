"""
Passthrough parser for StreamingContent instances.

This parser handles StreamingContent instances that are already parsed,
simply returning a copy of the input.
"""

from __future__ import annotations

from typing import Any

from src.core.domain.streaming.parsing.parser_strategy import IParserStrategy
from src.core.domain.streaming.streaming_content import StreamingContent


class PassthroughParser(IParserStrategy):
    """Parser for StreamingContent instances (passthrough).

    When the input is already a StreamingContent instance, this parser
    creates a copy with all fields preserved.
    """

    def can_parse(self, raw_data: Any) -> bool:
        """Check if input is a StreamingContent instance.

        Args:
            raw_data: The raw data to check

        Returns:
            True if raw_data is a StreamingContent instance
        """
        return isinstance(raw_data, StreamingContent)

    def parse(self, raw_data: Any) -> StreamingContent:
        """Create a copy of the StreamingContent instance.

        Args:
            raw_data: StreamingContent instance to copy

        Returns:
            A new StreamingContent instance with all fields copied

        Raises:
            ValueError: If raw_data is not a StreamingContent instance
        """
        if not isinstance(raw_data, StreamingContent):
            raise ValueError(
                f"Expected StreamingContent, got {type(raw_data).__name__}"
            )

        return StreamingContent(
            content=raw_data.content,
            is_done=raw_data.is_done,
            is_cancellation=raw_data.is_cancellation,
            metadata=dict(raw_data.metadata),
            usage=raw_data.usage,
            raw_data=raw_data.raw_data,
        )


__all__ = ["PassthroughParser"]

