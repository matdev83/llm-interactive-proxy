"""
StreamingContent dict parser.

This parser handles the internal "StreamingContent-like" dict shape used in
some middleware/tests:

{
  "content": "...",
  "metadata": {...},
  "is_done": bool,
  ...
}

This is transport-neutral and should be treated as an already-normalized chunk
representation rather than an opaque dict payload.
"""

from __future__ import annotations

from typing import Any

from src.core.domain.streaming.parsing.parser_strategy import IParserStrategy
from src.core.domain.streaming.streaming_content import StreamingContent


class StreamingContentDictParser(IParserStrategy):
    """Parse internal StreamingContent-like dicts into StreamingContent."""

    _REQUIRED_KEYS = {"content", "metadata", "is_done"}

    def can_parse(self, raw_data: Any) -> bool:
        if not isinstance(raw_data, dict):
            return False

        # Avoid stealing OpenAI-format chunks which are also dicts.
        if "choices" in raw_data:
            return False

        return self._REQUIRED_KEYS.issubset(raw_data.keys())

    def parse(self, raw_data: Any) -> StreamingContent:
        if not isinstance(raw_data, dict):
            raise ValueError(f"Expected dict, got {type(raw_data).__name__}")

        content_val = raw_data.get("content", "")
        metadata_val = raw_data.get("metadata") or {}

        if not isinstance(metadata_val, dict):
            metadata_val = {}

        if content_val is None:
            normalized_content: str = ""
        elif isinstance(content_val, str):
            normalized_content = content_val
        else:
            normalized_content = str(content_val)

        stream_id = raw_data.get("stream_id")
        if not isinstance(stream_id, str):
            stream_id = None

        usage = raw_data.get("usage")
        if usage is not None and not isinstance(usage, dict):
            usage = None

        # Convert usage dict to UsageSummary if needed
        usage_summary = None
        if usage is not None and isinstance(usage, dict):
            from src.core.domain.streaming.streaming_content import UsageSummary

            usage_summary = UsageSummary(**usage)  # type: ignore[arg-type]

        return StreamingContent(
            content=normalized_content,
            metadata=dict(metadata_val),
            is_done=bool(raw_data.get("is_done", False)),
            is_empty=raw_data.get("is_empty"),
            stream_id=stream_id,
            is_cancellation=bool(raw_data.get("is_cancellation", False)),
            usage=usage_summary,
            raw_data=raw_data,
        )


__all__ = ["StreamingContentDictParser"]
