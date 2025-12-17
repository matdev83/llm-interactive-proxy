"""
Raw chunk parsing strategies.

This module contains parser strategies for converting raw backend chunks
into StreamingContent. The parser handles provider-specific formats including
OpenAI, Anthropic, Gemini, SSE, and ProcessedResponse.
"""

from __future__ import annotations

import logging
from typing import Any

from src.core.app.constants.logging_constants import TRACE_LEVEL
from src.core.domain.streaming.parsing.anthropic_dict_parser import (
    AnthropicDictParser,
)
from src.core.domain.streaming.parsing.fallback_parser import FallbackParser
from src.core.domain.streaming.parsing.json_string_parser import (
    JSONStringParser,
)
from src.core.domain.streaming.parsing.gemini_dict_parser import GeminiDictParser
from src.core.domain.streaming.parsing.openai_dict_parser import OpenAIDictParser
from src.core.domain.streaming.parsing.passthrough_parser import (
    PassthroughParser,
)
from src.core.domain.streaming.parsing.parser_strategy import IParserStrategy
from src.core.domain.streaming.parsing.plain_string_parser import (
    PlainStringParser,
)
from src.core.domain.streaming.parsing.processed_response_parser import (
    ProcessedResponseParser,
)
from src.core.domain.streaming.parsing.sse_bytes_parser import SSEBytesParser
from src.core.domain.streaming.parsing.sse_string_parser import SSEStringParser
from src.core.domain.streaming.parsing.stop_chunk_parser import StopChunkParser
from src.core.domain.streaming.stop_chunk_with_usage import (
    StopChunkWithUsage,
)
from src.core.domain.streaming.streaming_content import StreamingContent

logger = logging.getLogger(__name__)


class RawChunkParser:
    """Parser for converting raw backend chunks into StreamingContent.

    This parser uses a chain of strategy parsers to handle multiple input formats:
    - StreamingContent (passthrough)
    - ProcessedResponse
    - StopChunkWithUsage
    - Dict (OpenAI, Anthropic, Gemini formats)
    - String (JSON, SSE, plain)
    - Bytes (SSE, JSON)
    """

    def __init__(self) -> None:
        """Initialize the parser with strategy chain.

        Strategies are ordered by specificity - most specific parsers come first.
        """
        # Order matters: most specific parsers first
        self._strategies: list[IParserStrategy] = [
            PassthroughParser(),  # StreamingContent instances
            ProcessedResponseParser(),  # ProcessedResponse objects
            StopChunkParser(),  # StopChunkWithUsage (must be before dict parsers)
            AnthropicDictParser(),  # Anthropic event dicts
            OpenAIDictParser(),  # OpenAI-style dicts
            GeminiDictParser(),  # Gemini JSON objects
            SSEBytesParser(),  # Bytes/SSE
            SSEStringParser(),  # String SSE
            JSONStringParser(),  # JSON strings
            PlainStringParser(),  # Plain strings
            FallbackParser(),  # Everything else (fallback)
        ]

    def parse(self, raw_data: Any) -> StreamingContent:
        """Parse raw data into StreamingContent using strategy chain.

        Args:
            raw_data: Raw data from backend (dict, str, bytes, ProcessedResponse, etc.)

        Returns:
            A new StreamingContent instance
        """
        # Log chunk entering the pipeline at TRACE level for diagnostic tracking
        if logger.isEnabledFor(TRACE_LEVEL):
            raw_type = type(raw_data).__name__
            raw_keys = (
                list(raw_data.keys())
                if isinstance(raw_data, dict)
                else (
                    list(raw_data.content.keys())
                    if hasattr(raw_data, "content")
                    and isinstance(raw_data.content, dict)
                    else "N/A"
                )
            )
            is_stop_chunk = isinstance(raw_data, StopChunkWithUsage) or (
                hasattr(raw_data, "content")
                and isinstance(raw_data.content, StopChunkWithUsage)
            )
            logger.log(
                TRACE_LEVEL,
                "[STREAMING] StreamingContent.from_raw: Chunk entering pipeline, "
                "type=%s, keys=%s, is_stop_chunk_with_usage=%s",
                raw_type,
                raw_keys,
                is_stop_chunk,
            )

        # Try each strategy in order until one can parse the data
        for strategy in self._strategies:
            if strategy.can_parse(raw_data):
                return strategy.parse(raw_data)

        # This should never happen since FallbackParser always returns True
        # But include as safety net
        logger.error(f"No parser strategy could handle raw data type: {type(raw_data)}")
        return StreamingContent(content=str(raw_data), raw_data=raw_data)


__all__ = ["RawChunkParser"]
