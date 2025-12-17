"""Replacement response factory for tool-call reactor subsystem.

This module implements the factory for building replacement responses when tool calls
are swallowed by policy, ensuring client safety and downstream compatibility.
"""

from __future__ import annotations

import time
from typing import Any

from src.core.domain.chat import ToolCall
from src.core.interfaces.replacement_response_factory_interface import (
    IReplacementResponseFactory,
    ToolCallReactionMetadata,
)
from src.core.interfaces.response_processor_interface import ProcessedResponse

# Bound the amount of swallowed assistant content that is kept for retry prompts.
_MAX_SWALLOWED_ORIGINAL_CONTENT_CHARS = 4000


def _truncate_text(value: str | None, limit: int) -> str | None:
    """Truncate text to a maximum length, appending truncation indicator.

    Args:
        value: The text to truncate, or None.
        limit: Maximum length before truncation.

    Returns:
        Truncated text with indicator, or None if input was None.
    """
    if value is None:
        return None
    if len(value) <= limit:
        return value
    return value[:limit] + "\n...[truncated]"


class ReplacementResponseFactory(IReplacementResponseFactory):
    """Factory for building replacement responses for swallowed tool calls.

    This factory creates client-safe replacement responses that:
    - Avoid exposing internal steering identifiers to clients
    - Set required metadata keys for downstream processing
    - Preserve bounded original content for retry logic
    - Set the _steering_replacement marker for streaming accumulation reset
    """

    def build_replacement(
        self,
        original_response: ProcessedResponse,
        replacement_content: str,
        original_tool_call: ToolCall,
        reaction_metadata: ToolCallReactionMetadata | None = None,
    ) -> ProcessedResponse:
        """Build a replacement response for a swallowed tool call.

        Args:
            original_response: The original response that contained the tool call.
            replacement_content: The steering message to include in the replacement.
            original_tool_call: The tool call that was swallowed.
            reaction_metadata: Optional metadata about the reactor's reaction.

        Returns:
            A ProcessedResponse compatible with the middleware pipeline that:
            - Contains client-safe content (no internal steering identifiers)
            - Sets required metadata keys for downstream processing
            - Preserves bounded original content for retry logic
            - Sets the _steering_replacement marker for streaming accumulation reset
        """
        # Extract original content
        original_content = getattr(original_response, "content", None)

        # Merge metadata
        original_metadata = getattr(original_response, "metadata", {}) or {}
        merged_metadata: dict[str, Any] = (
            dict(original_metadata) if isinstance(original_metadata, dict) else {}
        )

        # Merge reaction metadata into tool_call_reactor key
        if reaction_metadata:
            existing_reactor_metadata = {}
            if isinstance(merged_metadata.get("tool_call_reactor"), dict):
                existing_reactor_metadata = {
                    **merged_metadata["tool_call_reactor"],
                }
            merged_metadata["tool_call_reactor"] = {
                **existing_reactor_metadata,
                **reaction_metadata.model_dump(),
            }

        # Collect swallowed tool calls
        swallowed_tool_calls: list[dict[str, Any]] = []
        existing_tool_calls = merged_metadata.get("tool_calls")
        if isinstance(existing_tool_calls, list):
            for tc in existing_tool_calls:
                if isinstance(tc, dict):
                    swallowed_tool_calls.append(dict(tc))
        # Remove tool_calls from metadata (they're now in swallowed_tool_calls)
        if "tool_calls" in merged_metadata:
            merged_metadata.pop("tool_calls", None)

        # Extract tool call details
        tool_call_dict = original_tool_call.model_dump()
        tool_call_id = tool_call_dict.get("id")
        function_payload = tool_call_dict.get("function", {})
        tool_name = None
        if isinstance(function_payload, dict):
            tool_name = function_payload.get("name")
        swallowed_tool_calls.append(tool_call_dict)

        # Build metadata with required keys
        merged_metadata.update(
            {
                "tool_call_swallowed": True,
                "original_tool_call": tool_call_dict,
                "replacement_provided": True,
                "role": "tool",
                "tool_call_id": tool_call_id,
                "finish_reason": "stop",
                "tool_name": tool_name,
                "steering_message": replacement_content,
                "swallowed_tool_calls": swallowed_tool_calls,
                "swallowed_original_content": (
                    _truncate_text(
                        (
                            original_content
                            if isinstance(original_content, str)
                            else None
                        ),
                        _MAX_SWALLOWED_ORIGINAL_CONTENT_CHARS,
                    )
                ),
                # CRITICAL: Mark as steering replacement so downstream processors
                # clear accumulated content instead of appending
                "_steering_replacement": True,
            }
        )

        # Get model name from metadata or use default
        model_name = merged_metadata.get("model", "proxy-assistant")

        # Build an OpenAI-compatible response structure for client consumption.
        # CRITICAL FIX: Use 'chatcmpl-proxy-*' ID instead of 'chatcmpl-steering-*'
        # to avoid exposing internal steering markers to clients. The steering-*
        # pattern is flagged as an internal leak by SteeringLeakProtector.
        current_time = int(time.time())
        replacement_struct = {
            "id": f"chatcmpl-proxy-{current_time}",
            "object": "chat.completion",
            "created": current_time,
            "model": model_name,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": replacement_content,
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": getattr(original_response, "usage", None),
        }

        # CRITICAL ROOT CAUSE FIX: Do NOT convert the struct to a JSON string!
        # When content is a JSON string, it gets treated as raw text by the
        # ContentAccumulationProcessor and is APPENDED to previously-sent content,
        # causing the leak bug where internal JSON appears after legitimate text.
        # Always use the dict struct - the SSE assembler will properly format it
        # as `data: {...}\n\n` for the client.
        new_response = ProcessedResponse(
            content=replacement_struct,
            usage=getattr(original_response, "usage", None),
            metadata=merged_metadata,
        )
        return new_response
