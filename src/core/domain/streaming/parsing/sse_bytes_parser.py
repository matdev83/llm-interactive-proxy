"""
SSE bytes parser.

This parser handles bytes/bytearray containing Server-Sent Events format.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from src.core.domain.streaming.parsing.parser_strategy import IParserStrategy
from src.core.domain.streaming.streaming_content import StreamingContent

logger = logging.getLogger(__name__)

# DoS protection limits
MAX_SSE_PAYLOAD_SIZE = 10 * 1024 * 1024  # 10MB maximum SSE payload
MAX_JSON_DEPTH = 100  # Maximum JSON nesting depth to prevent stack overflow


class SSEBytesParser(IParserStrategy):
    """Parser for SSE bytes/bytearray.

    Handles bytes starting with 'data: ' prefix, including '[DONE]' markers.
    """

    def can_parse(self, raw_data: Any) -> bool:
        """Check if input is bytes/bytearray.

        Args:
            raw_data: The raw data to check

        Returns:
            True if raw_data is bytes or bytearray
        """
        return isinstance(raw_data, bytes | bytearray)

    def parse(self, raw_data: Any) -> StreamingContent:
        """Parse SSE bytes into StreamingContent.

        Args:
            raw_data: Bytes or bytearray containing SSE format

        Returns:
            StreamingContent with parsed content

        Raises:
            ValueError: If raw_data is not bytes/bytearray or exceeds size limits
        """
        if not isinstance(raw_data, bytes | bytearray):
            raise ValueError(
                f"Expected bytes or bytearray, got {type(raw_data).__name__}"
            )

        # DoS protection: Check payload size before parsing
        payload_size = len(raw_data)
        if payload_size > MAX_SSE_PAYLOAD_SIZE:
            logger.warning(
                "SSE payload too large: %d bytes (limit: %d bytes)",
                payload_size,
                MAX_SSE_PAYLOAD_SIZE,
            )
            raise ValueError(
                f"SSE payload too large: {payload_size} bytes (limit: {MAX_SSE_PAYLOAD_SIZE} bytes)"
            )

        try:
            decoded_str = bytes(raw_data).decode("utf-8").strip()
            if decoded_str.startswith("data: "):
                json_part = decoded_str[6:]
                if json_part.strip() == "[DONE]":
                    return StreamingContent(is_done=True, raw_data=raw_data)
                else:
                    try:
                        # DoS protection: Parse JSON with depth limit
                        parsed_json = self._parse_json_safely(json_part)
                        # Recursively parse JSON using StreamingContent.from_raw
                        return StreamingContent.from_raw(parsed_json)
                    except json.JSONDecodeError:
                        return StreamingContent(content=json_part, raw_data=raw_data)
                    except ValueError as e:
                        if "depth" in str(e).lower():
                            logger.warning(
                                "JSON payload too deeply nested: %s", e, exc_info=True
                            )
                            # Reject deeply nested JSON completely for security
                            raise ValueError(f"JSON payload too deeply nested: {e}")
                        raise
            else:
                # Not SSE format, try parsing as JSON string with safety checks
                return self._parse_as_string_safely(decoded_str, raw_data)
        except UnicodeDecodeError:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning("Could not decode bytes: %r", raw_data, exc_info=True)
            return StreamingContent(content="", raw_data=raw_data)

    def _parse_json_safely(self, json_str: str) -> Any:
        """Parse JSON with depth limits to prevent stack overflow.

        Args:
            json_str: JSON string to parse

        Returns:
            Parsed JSON object

        Raises:
            ValueError: If JSON is too deeply nested
            json.JSONDecodeError: If JSON is invalid
        """
        # Use a custom JSON parser with depth limit
        try:
            # Python's json.loads doesn't have a built-in depth limit,
            # so we need to validate depth manually
            parsed = json.loads(json_str)
            self._validate_json_depth(parsed, 0)
            return parsed
        except RecursionError:
            raise ValueError("JSON too deeply nested (stack overflow)")

    def _validate_json_depth(self, obj: Any, current_depth: int) -> None:
        """Validate JSON object doesn't exceed maximum nesting depth.

        Args:
            obj: JSON object to validate
            current_depth: Current nesting depth

        Raises:
            ValueError: If maximum depth exceeded
        """
        if current_depth >= MAX_JSON_DEPTH:
            raise ValueError(
                f"JSON depth {current_depth} exceeds maximum {MAX_JSON_DEPTH}"
            )

        if isinstance(obj, dict):
            for value in obj.values():
                self._validate_json_depth(value, current_depth + 1)
        elif isinstance(obj, list):
            for item in obj:
                self._validate_json_depth(item, current_depth + 1)

    def _parse_as_string_safely(
        self, decoded_str: str, raw_data: bytes | bytearray
    ) -> StreamingContent:
        """Parse decoded string safely with size and depth checks.

        Args:
            decoded_str: Decoded string from bytes
            raw_data: Original raw bytes for raw_data field

        Returns:
            StreamingContent result
        """
        # Additional size check for string representation
        string_size = len(decoded_str.encode("utf-8"))
        if string_size > MAX_SSE_PAYLOAD_SIZE:
            logger.warning(
                "Decoded string too large: %d bytes (limit: %d bytes)",
                string_size,
                MAX_SSE_PAYLOAD_SIZE,
            )
            raise ValueError(
                f"Decoded string too large: {string_size} bytes (limit: {MAX_SSE_PAYLOAD_SIZE} bytes)"
            )

        # Try parsing as JSON first with safety checks
        stripped = decoded_str.strip()
        if stripped.startswith(("{", "[")):
            try:
                parsed_json = self._parse_json_safely(stripped)
                return StreamingContent.from_raw(parsed_json)
            except json.JSONDecodeError:
                # Fall back to string content if JSON is malformed
                pass
            except ValueError as e:
                if "depth" in str(e).lower():
                    # Reject deeply nested JSON completely for security
                    raise ValueError(f"JSON payload too deeply nested: {e}")
                # Fall back to string content for other validation errors

        # Treat as plain string
        return StreamingContent(content=decoded_str, raw_data=raw_data)


__all__ = ["SSEBytesParser"]
