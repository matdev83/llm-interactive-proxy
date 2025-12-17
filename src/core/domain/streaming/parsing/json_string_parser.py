"""
JSON string parser.

This parser handles strings containing JSON format.
"""

from __future__ import annotations

import json
from typing import Any

from src.core.domain.streaming.parsing.parser_strategy import IParserStrategy
from src.core.domain.streaming.streaming_content import StreamingContent


class JSONStringParser(IParserStrategy):
    """Parser for JSON strings.

    Handles strings that start with '{' or '[' and can be parsed as JSON.
    """

    def can_parse(self, raw_data: Any) -> bool:
        """Check if input is a string that looks like JSON.

        Args:
            raw_data: The raw data to check

        Returns:
            True if raw_data is a string starting with '{' or '['
        """
        if not isinstance(raw_data, str):
            return False

        stripped = raw_data.strip()
        return stripped.startswith(("{", "["))

    def parse(self, raw_data: Any) -> StreamingContent:
        """Parse JSON string into StreamingContent.

        Args:
            raw_data: String containing JSON

        Returns:
            StreamingContent with parsed content

        Raises:
            ValueError: If raw_data is not a string or JSON parsing fails
        """
        if not isinstance(raw_data, str):
            raise ValueError(f"Expected str, got {type(raw_data).__name__}")

        try:
            parsed_json = json.loads(raw_data)
            # Recursively parse the JSON using StreamingContent.from_raw
            return StreamingContent.from_raw(parsed_json)
        except json.JSONDecodeError:
            # If JSON parsing fails, treat as plain string
            return StreamingContent(content=raw_data, raw_data=raw_data)


__all__ = ["JSONStringParser"]
