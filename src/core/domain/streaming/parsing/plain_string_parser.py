"""
Plain string parser.

This parser handles plain strings that are not JSON or SSE format.
"""

from __future__ import annotations

from typing import Any

from src.core.domain.streaming.parsing.parser_strategy import IParserStrategy
from src.core.domain.streaming.streaming_content import StreamingContent


class PlainStringParser(IParserStrategy):
    """Parser for plain strings.

    Handles strings that are not JSON or SSE format - fallback parser.
    """

    def can_parse(self, raw_data: Any) -> bool:
        """Check if input is a plain string.

        Args:
            raw_data: The raw data to check

        Returns:
            True if raw_data is a string (and not JSON/SSE format)
        """
        return isinstance(raw_data, str)

    def parse(self, raw_data: Any) -> StreamingContent:
        """Parse plain string into StreamingContent.

        Args:
            raw_data: Plain string

        Returns:
            StreamingContent with string as content

        Raises:
            ValueError: If raw_data is not a string
        """
        if not isinstance(raw_data, str):
            raise ValueError(f"Expected str, got {type(raw_data).__name__}")

        return StreamingContent(content=raw_data, raw_data=raw_data)


__all__ = ["PlainStringParser"]
