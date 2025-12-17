"""
Gemini dict parser.

This parser handles Gemini JSON objects with 'candidates' and 'contentBlock' fields.

Note: This parser exists for completeness but is NOT used in the RawChunkParser
strategy chain. Provider-specific formats like Gemini JSON objects should be
normalized by GeminiStreamNormalizer before reaching the shared parsing entry
point (StreamingContent.from_raw). This enforces architectural boundaries and
keeps provider-specific logic in provider adapters, not shared domain code.
"""

from __future__ import annotations

import uuid
from typing import Any

from src.core.domain.streaming.parsing.parser_strategy import IParserStrategy
from src.core.domain.streaming.streaming_content import StreamingContent


class GeminiDictParser(IParserStrategy):
    """Parser for Gemini JSON objects.

    Handles dicts with 'candidates' array containing 'contentBlock' with 'parts'.
    """

    def can_parse(self, raw_data: Any) -> bool:
        """Check if input is a Gemini JSON object.

        Args:
            raw_data: The raw data to check

        Returns:
            True if raw_data is a dict with 'candidates' field (and not OpenAI format)
        """
        if not isinstance(raw_data, dict):
            return False

        # Skip if it's a StopChunkWithUsage (handled by StopChunkParser)
        from src.core.domain.streaming.stop_chunk_with_usage import (
            StopChunkWithUsage,
        )

        if isinstance(raw_data, StopChunkWithUsage):
            return False

        # Skip Anthropic format
        if raw_data.get("type") in ("content_block_delta", "message_delta"):
            return False

        # Skip OpenAI format (has 'choices' field)
        if "choices" in raw_data:
            return False

        # Gemini format has 'candidates' field
        return "candidates" in raw_data

    def parse(self, raw_data: Any) -> StreamingContent:
        """Parse Gemini JSON object into StreamingContent.

        Args:
            raw_data: Gemini JSON object

        Returns:
            StreamingContent with extracted content and metadata

        Raises:
            ValueError: If raw_data is not a valid Gemini JSON object
        """
        if not isinstance(raw_data, dict):
            raise ValueError(f"Expected dict, got {type(raw_data).__name__}")

        content: str | dict | bytes = ""
        is_done = bool(raw_data.get("done", False))
        metadata: dict[str, Any] = {}
        finish_reason = None

        candidates = raw_data.get("candidates")
        if isinstance(candidates, list) and candidates:
            candidate = candidates[0]
            if isinstance(candidate, dict):
                finish_reason = candidate.get("finishReason", finish_reason)
                content_block = candidate.get("content") or {}
                if isinstance(content_block, dict):
                    parts = content_block.get("parts")
                    if isinstance(parts, list) and parts:
                        first_part = parts[0]
                        if isinstance(first_part, dict):
                            text_val = first_part.get("text")
                            if isinstance(text_val, str):
                                content = text_val

                            function_call = first_part.get("functionCall")
                            if isinstance(function_call, dict):
                                metadata["tool_calls"] = [
                                    {
                                        "id": function_call.get("id")
                                        or f"call_{uuid.uuid4().hex[:8]}",
                                        "type": "function",
                                        "function": function_call,
                                    }
                                ]
                                finish_reason = finish_reason or "tool_calls"

                        elif isinstance(first_part, str):
                            content = first_part

                    role = content_block.get("role")
                    if role:
                        metadata["role"] = role

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

        # Extract usage metadata (Gemini uses 'usageMetadata')
        usage: dict[str, Any] | None = None
        usage_metadata = raw_data.get("usageMetadata")
        if isinstance(usage_metadata, dict):
            usage = {
                "prompt_tokens": usage_metadata.get("promptTokenCount", 0),
                "completion_tokens": usage_metadata.get("candidatesTokenCount", 0),
                "total_tokens": usage_metadata.get("totalTokenCount", 0),
            }
        else:
            usage = raw_data.get("usage")  # type: ignore[assignment]

        return StreamingContent(
            content=content,
            is_done=is_done,
            metadata=metadata,
            usage=usage,
            raw_data=raw_data,
        )


__all__ = ["GeminiDictParser"]
