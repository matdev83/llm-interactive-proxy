"""
Fallback parser for unsupported types.

This parser handles any remaining types by converting them to strings.
"""

from __future__ import annotations

import logging
from typing import Any

from src.core.domain.streaming.parsing.parser_strategy import IParserStrategy
from src.core.domain.streaming.streaming_content import StreamingContent

logger = logging.getLogger(__name__)


class FallbackParser(IParserStrategy):
    """Fallback parser for unsupported types.

    Converts any remaining types to strings. This should be the last parser
    in the chain.
    """

    def can_parse(self, raw_data: Any) -> bool:
        """Always returns True - this is the fallback parser.

        Args:
            raw_data: The raw data to check

        Returns:
            True (always, as this is the fallback)
        """
        return True

    def parse(self, raw_data: Any) -> StreamingContent:
        """Convert unsupported type to StreamingContent.

        Args:
            raw_data: Any unsupported type

        Returns:
            StreamingContent with string representation as content
        """
        logger.warning(
            f"Unsupported raw data type for StreamingContent: {type(raw_data)}"
        )
        return StreamingContent(content=str(raw_data), raw_data=raw_data)


__all__ = ["FallbackParser"]

