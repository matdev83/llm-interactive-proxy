"""
Anthropic dict parser.

This parser handles Anthropic event dicts with 'type' fields like
'content_block_delta' and 'message_delta'.

Note: This parser exists for completeness but is NOT used in the RawChunkParser
strategy chain. Provider-specific formats like Anthropic event dicts should be
normalized by AnthropicStreamNormalizer before reaching the shared parsing
entry point (StreamingContent.from_raw). This enforces architectural boundaries
and keeps provider-specific logic in provider adapters, not shared domain code.
"""

from __future__ import annotations

from typing import Any

from src.core.domain.streaming.parsing.parser_strategy import IParserStrategy
from src.core.domain.streaming.streaming_content import StreamingContent


class AnthropicDictParser(IParserStrategy):
    """Parser for Anthropic event dicts.

    Handles dicts with 'type' field set to 'content_block_delta' or 'message_delta'.
    """

    def can_parse(self, raw_data: Any) -> bool:
        """Check if input is an Anthropic event dict.

        Args:
            raw_data: The raw data to check

        Returns:
            True if raw_data is a dict with Anthropic 'type' field
        """
        if not isinstance(raw_data, dict):
            return False

        event_type = raw_data.get("type")
        return event_type in ("content_block_delta", "message_delta")

    def parse(self, raw_data: Any) -> StreamingContent:
        """Parse Anthropic event dict into StreamingContent.

        Args:
            raw_data: Anthropic event dict

        Returns:
            StreamingContent with extracted content and metadata

        Raises:
            ValueError: If raw_data is not a valid Anthropic event dict
        """
        if not isinstance(raw_data, dict):
            raise ValueError(f"Expected dict, got {type(raw_data).__name__}")

        content: str | dict | bytes = ""
        is_done = False
        from src.core.domain.usage_summary import UsageSummary

        usage: UsageSummary | None = None

        event_type = raw_data.get("type")

        if event_type == "content_block_delta":
            delta = raw_data.get("delta", {})
            if delta.get("type") == "text_delta":
                content = delta.get("text", "")

        elif event_type == "message_delta":
            raw_usage = raw_data.get("usage")
            if isinstance(raw_usage, UsageSummary):
                usage = raw_usage
            elif isinstance(raw_usage, dict):
                usage = UsageSummary.from_dict(raw_usage)
            is_done = True

        return StreamingContent(
            content=content,
            is_done=is_done,
            metadata={},
            usage=usage,
            raw_data=raw_data,
        )


__all__ = ["AnthropicDictParser"]
