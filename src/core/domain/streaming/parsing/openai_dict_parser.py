"""
OpenAI dict parser.

This parser handles OpenAI-style dict chunks with 'choices' and 'delta' fields.
"""

from __future__ import annotations

from typing import Any

from src.core.domain.streaming.parsing.parser_strategy import IParserStrategy
from src.core.domain.streaming.streaming_content import StreamingContent


class OpenAIDictParser(IParserStrategy):
    """Parser for OpenAI-style dict chunks.

    Handles dicts with 'choices' array containing 'delta' or 'message' fields.
    Also handles error responses and usage metadata.
    """

    def can_parse(self, raw_data: Any) -> bool:
        """Check if input is an OpenAI-style dict.

        Args:
            raw_data: The raw data to check

        Returns:
            True if raw_data is a dict with 'choices' field (and not Anthropic/Gemini format)
        """
        if not isinstance(raw_data, dict):
            return False

        # Skip if it's a StopChunkWithUsage (handled by StopChunkParser)
        from src.core.domain.streaming.stop_chunk_with_usage import (
            StopChunkWithUsage,
        )

        if isinstance(raw_data, StopChunkWithUsage):
            return False

        # Skip Anthropic format (has 'type' field with specific values)
        if raw_data.get("type") in ("content_block_delta", "message_delta"):
            return False

        # Skip Gemini format (has 'candidates' field without 'choices')
        if "candidates" in raw_data and "choices" not in raw_data:
            return False

        # OpenAI format has 'choices' field
        return "choices" in raw_data

    def parse(self, raw_data: Any) -> StreamingContent:
        """Parse OpenAI-style dict into StreamingContent.

        Args:
            raw_data: OpenAI-style dict chunk

        Returns:
            StreamingContent with extracted content and metadata

        Raises:
            ValueError: If raw_data is not a valid OpenAI-style dict
        """
        if not isinstance(raw_data, dict):
            raise ValueError(f"Expected dict, got {type(raw_data).__name__}")

        content: str | dict | bytes = ""
        is_done = False
        metadata: dict[str, Any] = {}
        usage: dict[str, Any] | None = None

        choices = raw_data.get("choices")
        if choices and isinstance(choices, list) and len(choices) > 0:
            choice = choices[0]
            if isinstance(choice, dict):
                finish_reason = choice.get("finish_reason")

                if "delta" in choice:
                    delta = choice["delta"]
                    if isinstance(delta, dict):
                        # Extract reasoning content
                        reasoning_value = delta.get("reasoning_content") or delta.get(
                            "reasoning"
                        )
                        if reasoning_value:
                            normalized_reasoning = (
                                reasoning_value
                                if isinstance(reasoning_value, str)
                                else str(reasoning_value)
                            )
                            metadata["reasoning_content"] = normalized_reasoning
                            metadata.setdefault("reasoning", normalized_reasoning)

                        # Extract content (preserves whitespace-only deltas)
                        content_value = delta.get("content")
                        if content_value is not None:
                            content = content_value

                        # Extract tool calls
                        tool_calls_val = delta.get("tool_calls")
                        if isinstance(tool_calls_val, list) and tool_calls_val:
                            metadata["tool_calls"] = tool_calls_val

                elif "message" in choice:
                    message = choice["message"]
                    if isinstance(message, dict) and "content" in message:
                        content_value = message.get("content")
                        content = (
                            content_value if content_value is not None else ""
                        )
                    if isinstance(message, dict):
                        tool_calls_val = message.get("tool_calls")
                        if isinstance(tool_calls_val, list) and tool_calls_val:
                            metadata["tool_calls"] = tool_calls_val

                elif "text" in choice:
                    content_value = choice.get("text")
                    content = content_value if content_value is not None else ""

                if finish_reason is not None:
                    metadata["finish_reason"] = finish_reason
                    normalized_reason = (
                        str(finish_reason).strip().lower() if finish_reason else ""
                    )
                    if normalized_reason in {
                        "error",
                        "cancelled",
                        "user_cancelled",
                        "system_cancelled",
                    }:
                        is_done = True

        # Capture top-level error from OpenAI-style error responses
        # This handles streaming error responses like rate limit errors
        # that have format: {"choices": [{"delta": {}, "finish_reason": "error"}], "error": {...}}
        if "error" in raw_data:
            metadata["error"] = raw_data["error"]
            # Also store the full error response as content for debugging
            if not content:
                content = raw_data

        # Extract metadata fields
        if "id" in raw_data:
            metadata["id"] = raw_data["id"]
        if "model" in raw_data:
            metadata["model"] = raw_data["model"]
        if "created" in raw_data:
            metadata["created"] = raw_data["created"]

        # Extract usage
        usage = raw_data.get("usage")

        # For chunks with usage data, preserve the original OpenAI-format
        # structure in content so downstream can recognize it and properly
        # serialize the usage field in the SSE output.
        if usage and not content and isinstance(raw_data, dict) and "choices" in raw_data:
            # OpenAI-format chunk with usage - preserve structure
            content = raw_data

        return StreamingContent(
            content=content,
            is_done=is_done,
            metadata=metadata,
            usage=usage,
            raw_data=raw_data,
        )


__all__ = ["OpenAIDictParser"]

