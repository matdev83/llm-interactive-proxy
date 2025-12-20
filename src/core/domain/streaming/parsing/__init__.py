"""
Raw chunk parsing strategies.

This module contains parser strategies for converting raw backend chunks
into StreamingContent. The parser handles transport-neutral formats (OpenAI-style
dicts, SSE, strings, bytes) and ProcessedResponse. Provider-specific formats
(Anthropic events, Gemini JSON) are handled by provider normalizers, not here.
"""

from __future__ import annotations

from src.core.domain.streaming.parsing.fallback_parser import FallbackParser
from src.core.domain.streaming.parsing.json_string_parser import (
    JSONStringParser,
)
from src.core.domain.streaming.parsing.openai_dict_parser import OpenAIDictParser
from src.core.domain.streaming.parsing.parser_strategy import IParserStrategy
from src.core.domain.streaming.parsing.passthrough_parser import (
    PassthroughParser,
)
from src.core.domain.streaming.parsing.plain_string_parser import (
    PlainStringParser,
)
from src.core.domain.streaming.parsing.processed_response_parser import (
    ProcessedResponseParser,
)
from src.core.domain.streaming.parsing.raw_chunk_parser import RawChunkParser
from src.core.domain.streaming.parsing.sse_bytes_parser import SSEBytesParser
from src.core.domain.streaming.parsing.sse_string_parser import SSEStringParser
from src.core.domain.streaming.parsing.stop_chunk_parser import StopChunkParser

__all__ = [
    "IParserStrategy",
    "RawChunkParser",
    "PassthroughParser",
    "ProcessedResponseParser",
    "StopChunkParser",
    "OpenAIDictParser",
    "SSEBytesParser",
    "SSEStringParser",
    "JSONStringParser",
    "PlainStringParser",
    "FallbackParser",
]
