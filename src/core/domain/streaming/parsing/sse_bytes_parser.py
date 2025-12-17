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
            ValueError: If raw_data is not bytes/bytearray
        """
        if not isinstance(raw_data, bytes | bytearray):
            raise ValueError(
                f"Expected bytes or bytearray, got {type(raw_data).__name__}"
            )

        try:
            decoded_str = bytes(raw_data).decode("utf-8").strip()
            if decoded_str.startswith("data: "):
                json_part = decoded_str[6:]
                if json_part.strip() == "[DONE]":
                    return StreamingContent(is_done=True, raw_data=raw_data)
                else:
                    try:
                        parsed_json = json.loads(json_part)
                        # Recursively parse the JSON using StreamingContent.from_raw
                        return StreamingContent.from_raw(parsed_json)
                    except json.JSONDecodeError:
                        return StreamingContent(content=json_part, raw_data=raw_data)
            else:
                # Not SSE format, try parsing as JSON string
                return StreamingContent.from_raw(decoded_str)
        except UnicodeDecodeError:
            logger.warning(f"Could not decode bytes: {raw_data!r}")
            return StreamingContent(content="", raw_data=raw_data)


__all__ = ["SSEBytesParser"]
