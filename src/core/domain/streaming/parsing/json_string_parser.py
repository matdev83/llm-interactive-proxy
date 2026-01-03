"""
JSON string parser.

This parser handles strings containing JSON format.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from src.core.common.json_validation import JSONValidationError, validate_json_structure
from src.core.domain.streaming.parsing.parser_strategy import IParserStrategy
from src.core.domain.streaming.streaming_content import StreamingContent

logger = logging.getLogger(__name__)

# DoS protection limits
MAX_JSON_PAYLOAD_SIZE = 10 * 1024 * 1024  # 10MB maximum JSON payload
MAX_JSON_ARRAY_ELEMENTS = 100_000  # Max elements in any array (DoS protection)


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
            ValueError: If raw_data is not a string, exceeds size limits,
                       or JSON parsing fails
        """
        if not isinstance(raw_data, str):
            raise ValueError(f"Expected str, got {type(raw_data).__name__}")

        # DoS protection: Check payload size before parsing
        if len(raw_data) > MAX_JSON_PAYLOAD_SIZE:
            logger.warning(
                "JSON payload too large: %d characters (limit: %d bytes)",
                len(raw_data),
                MAX_JSON_PAYLOAD_SIZE,
            )
            raise ValueError(
                f"JSON payload too large: {len(raw_data)} characters (limit: {MAX_JSON_PAYLOAD_SIZE} bytes)"
            )

        payload_size = len(raw_data.encode("utf-8"))
        if payload_size > MAX_JSON_PAYLOAD_SIZE:
            logger.warning(
                "JSON payload too large: %d bytes (limit: %d bytes)",
                payload_size,
                MAX_JSON_PAYLOAD_SIZE,
            )
            raise ValueError(
                f"JSON payload too large: {payload_size} bytes (limit: {MAX_JSON_PAYLOAD_SIZE} bytes)"
            )

        try:
            parsed_json = json.loads(raw_data)
            # DoS protection: Validate JSON structure (depth and array size)
            try:
                validate_json_structure(
                    parsed_json, max_array_elements=MAX_JSON_ARRAY_ELEMENTS
                )
            except JSONValidationError as e:
                logger.warning(
                    "JSON structure validation failed: %s",
                    e,
                    exc_info=True,
                )
                raise ValueError(f"JSON structure validation failed: {e}") from e

            # Recursively parse the JSON using StreamingContent.from_raw
            return StreamingContent.from_raw(parsed_json)
        except json.JSONDecodeError:
            # If JSON parsing fails, treat as plain string
            return StreamingContent(content=raw_data, raw_data=raw_data)


__all__ = ["JSONStringParser"]
