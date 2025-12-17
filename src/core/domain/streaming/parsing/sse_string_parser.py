"""
SSE string parser.

This parser handles strings containing Server-Sent Events format.
"""

from __future__ import annotations

import json
from typing import Any

from src.core.domain.streaming.parsing.parser_strategy import IParserStrategy
from src.core.domain.streaming.streaming_content import StreamingContent


class SSEStringParser(IParserStrategy):
    """Parser for SSE strings.

    Handles strings starting with 'data: ' prefix, including '[DONE]' markers.
    """

    def can_parse(self, raw_data: Any) -> bool:
        """Check if input is a string with SSE format.

        Args:
            raw_data: The raw data to check

        Returns:
            True if raw_data is a string starting with 'data: '
        """
        if not isinstance(raw_data, str):
            return False

        # Check if it starts with JSON-like structure (handled by JSONStringParser)
        stripped = raw_data.strip()
        if stripped.startswith(("{", "[")):
            return False

        # SSE format starts with 'data: '
        return stripped.startswith("data: ")

    def parse(self, raw_data: Any) -> StreamingContent:
        """Parse SSE string into StreamingContent.

        Args:
            raw_data: String containing SSE format

        Returns:
            StreamingContent with parsed content

        Raises:
            ValueError: If raw_data is not a string
        """
        if not isinstance(raw_data, str):
            raise ValueError(f"Expected str, got {type(raw_data).__name__}")

        # Handle Server-Sent Events format
        sse_part = raw_data.strip()[6:]  # Remove "data: " prefix
        if sse_part.strip() == "[DONE]":
            return StreamingContent(is_done=True, raw_data=raw_data)
        else:
            try:
                parsed_json = json.loads(sse_part)
                # Recursively parse the JSON using StreamingContent.from_raw
                return StreamingContent.from_raw(parsed_json)
            except json.JSONDecodeError:
                return StreamingContent(content=sse_part, raw_data=raw_data)


__all__ = ["SSEStringParser"]
