from __future__ import annotations

import json
import logging
import uuid
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


class StreamingContent:
    """Represents a piece of content from a streaming response.

    This class normalizes streaming content from various sources into a consistent
    structure that can be processed by streaming response processors.
    """

    def __init__(
        self,
        content: str = "",
        is_done: bool = False,
        is_cancellation: bool = False,
        metadata: dict[str, Any] | None = None,
        usage: dict[str, Any] | None = None,
        raw_data: Any | None = None,
    ) -> None:
        """Initialize a streaming content chunk.

        Args:
            content: The text content of the chunk
            is_done: Whether this is the final chunk in the stream
            is_cancellation: Whether this chunk represents a cancellation event
            metadata: Additional metadata about the chunk
            usage: Token usage information, if available
            raw_data: The original raw data from the stream
        """
        self.content = content
        self.is_done = is_done
        self.is_cancellation = is_cancellation
        self.metadata = metadata or {}
        self.usage = usage
        self.raw_data = raw_data

    @property
    def is_empty(self) -> bool:
        """Whether this chunk contains no actual content."""
        if self.content:
            return False
        if self.metadata.get("role") == "tool":
            return False
        tool_calls = self.metadata.get("tool_calls")
        if isinstance(tool_calls, list) and tool_calls:
            return False
        reasoning_content = self.metadata.get("reasoning_content")
        if isinstance(reasoning_content, str) and reasoning_content.strip():
            return False
        reasoning = self.metadata.get("reasoning")
        return not (isinstance(reasoning, str) and reasoning.strip())

    def to_bytes(self) -> bytes:
        """Convert this chunk to a bytes representation for streaming."""
        if self.is_done:
            if self.is_cancellation and self.content:
                data = {
                    "choices": [{"delta": {"content": self.content}}],
                    "finish_reason": "cancelled",
                }
                for key in ["id", "model", "created"]:
                    if key in self.metadata:
                        data[key] = self.metadata[key]
                return f"data: {json.dumps(data)}\n\ndata: [DONE]\n\n".encode()
            return b"data: [DONE]\n\n"

        # Simplified serialization for streaming
        delta: dict[str, Any] = {}

        role = self.metadata.get("role")
        if isinstance(role, str) and role:
            delta["role"] = role

        tool_call_id = self.metadata.get("tool_call_id")
        if isinstance(tool_call_id, str) and tool_call_id:
            delta["tool_call_id"] = tool_call_id

        tool_calls = self.metadata.get("tool_calls")
        if isinstance(tool_calls, list) and tool_calls:
            delta["tool_calls"] = tool_calls

        reasoning_value = self.metadata.get("reasoning_content") or self.metadata.get(
            "reasoning"
        )
        if isinstance(reasoning_value, str) and reasoning_value.strip():
            delta["reasoning_content"] = reasoning_value
            delta.setdefault("reasoning", reasoning_value)

        if self.content is not None:
            delta["content"] = self.content

        data = {"choices": [{"delta": delta}]}

        finish_reason = self.metadata.get("finish_reason")
        if finish_reason is not None:
            data["choices"][0]["finish_reason"] = finish_reason  # type: ignore[index]
        else:
            data["choices"][0]["finish_reason"] = None  # type: ignore[index]

        # Add metadata if available
        for key in ["id", "model", "created"]:
            if key in self.metadata:
                data[key] = self.metadata[key]

        return f"data: {json.dumps(data)}\n\n".encode()

    @classmethod
    def from_raw(cls, raw_data: Any) -> StreamingContent:
        """Create a StreamingContent instance from raw data.

        This method acts as a factory, attempting to parse various raw data formats
        into a standardized StreamingContent object.
        """
        content = ""
        is_done = False
        metadata: dict[str, Any] = {}
        usage: dict[str, Any] | None = None

        from src.core.interfaces.response_processor_interface import (
            ProcessedResponse,
        )

        if isinstance(raw_data, ProcessedResponse):
            metadata = dict(raw_data.metadata) if raw_data.metadata else {}
            usage = raw_data.usage
            content_val = raw_data.content

            def _finalize(result: StreamingContent) -> StreamingContent:
                merged_metadata = dict(result.metadata)
                merged_metadata.update(metadata)
                result.metadata = merged_metadata
                if usage is not None:
                    result.usage = usage
                result.raw_data = raw_data
                if bool(metadata.get("is_done")):
                    result.is_done = True
                if bool(metadata.get("is_cancellation")):
                    result.is_cancellation = True
                return result

            if isinstance(content_val, StreamingContent):
                # Create a shallow copy so downstream mutations don't affect upstream state
                copied = StreamingContent(
                    content=content_val.content,
                    is_done=content_val.is_done,
                    is_cancellation=content_val.is_cancellation,
                    metadata=dict(content_val.metadata),
                    usage=content_val.usage,
                    raw_data=content_val.raw_data,
                )
                return _finalize(copied)

            if isinstance(content_val, ProcessedResponse):
                return _finalize(cls.from_raw(content_val))

            if isinstance(content_val, dict | str | bytes | bytearray | list):
                # Delegate back to from_raw so dicts/bytes/strings are normalized consistently.
                return _finalize(cls.from_raw(content_val))

            content_str = ""
            if content_val is not None:
                if isinstance(content_val, bytes):
                    try:
                        content_str = content_val.decode("utf-8")
                    except UnicodeDecodeError:
                        logger.warning(
                            "Could not decode bytes in ProcessedResponse: %r",
                            content_val,
                        )
                        content_str = ""
                else:
                    content_str = str(content_val)

            return _finalize(
                cls(
                    content=content_str,
                    metadata={},
                )
            )

        if isinstance(raw_data, dict):
            # Handle dictionary (e.g., OpenAI or Anthropic chat completion chunk)
            if raw_data.get("type") == "content_block_delta":
                delta = raw_data.get("delta", {})
                if delta.get("type") == "text_delta":
                    content = delta.get("text", "")
            elif raw_data.get("type") == "message_delta":
                usage = raw_data.get("usage")
                is_done = True
            else:
                # Handle OpenAI chat completion chunks and Gemini streaming payloads
                is_done = bool(raw_data.get("done", False))
                finish_reason = None

                # Gemini-style candidates
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
                else:
                    # OpenAI-style chat completion chunk
                    choices = raw_data.get("choices")
                    if choices and isinstance(choices, list) and len(choices) > 0:
                        choice = choices[0]
                        if isinstance(choice, dict):
                            finish_reason = choice.get("finish_reason", finish_reason)
                            if "delta" in choice:
                                delta = choice["delta"]
                                if isinstance(delta, dict):
                                    reasoning_value = delta.get(
                                        "reasoning_content"
                                    ) or delta.get("reasoning")
                                    if reasoning_value:
                                        normalized_reasoning = (
                                            reasoning_value
                                            if isinstance(reasoning_value, str)
                                            else str(reasoning_value)
                                        )
                                        metadata["reasoning_content"] = (
                                            normalized_reasoning
                                        )
                                        metadata.setdefault(
                                            "reasoning", normalized_reasoning
                                        )
                                    content_value = delta.get("content")
                                    if content_value is not None:
                                        content = content_value
                                    tool_calls_val = delta.get("tool_calls")
                                    if (
                                        isinstance(tool_calls_val, list)
                                        and tool_calls_val
                                    ):
                                        metadata["tool_calls"] = tool_calls_val
                            elif "message" in choice:
                                message = choice["message"]
                                if isinstance(message, dict) and "content" in message:
                                    content_value = message.get("content")
                                    content = (
                                        content_value
                                        if content_value is not None
                                        else ""
                                    )
                                if isinstance(message, dict):
                                    tool_calls_val = message.get("tool_calls")
                                    if (
                                        isinstance(tool_calls_val, list)
                                        and tool_calls_val
                                    ):
                                        metadata["tool_calls"] = tool_calls_val
                            elif "text" in choice:  # For older models or specific APIs
                                content_value = choice.get("text")
                                content = (
                                    content_value if content_value is not None else ""
                                )

                if finish_reason is not None:
                    metadata["finish_reason"] = finish_reason
                    if str(finish_reason):
                        is_done = True

                if "id" in raw_data:
                    metadata["id"] = raw_data["id"]
                if "model" in raw_data:
                    metadata["model"] = raw_data["model"]
                if "created" in raw_data:
                    metadata["created"] = raw_data["created"]

                usage_metadata = raw_data.get("usageMetadata")
                if isinstance(usage_metadata, dict):
                    usage = {
                        "prompt_tokens": usage_metadata.get("promptTokenCount", 0),
                        "completion_tokens": usage_metadata.get(
                            "candidatesTokenCount", 0
                        ),
                        "total_tokens": usage_metadata.get("totalTokenCount", 0),
                    }
                else:
                    usage = raw_data.get("usage")

        elif isinstance(raw_data, str):
            # Handle string (e.g., raw text or JSON string)
            if raw_data.strip().startswith(("{", "[")):
                try:
                    parsed_json = json.loads(raw_data)
                    # Recursively call from_raw for parsed JSON
                    return cls.from_raw(parsed_json)
                except json.JSONDecodeError:
                    content = raw_data
            else:
                content = raw_data

        elif isinstance(raw_data, bytes):
            # Handle bytes (decode to string first)
            try:
                decoded_str = raw_data.decode("utf-8").strip()
                # Handle SSE format: data: {json}
                if decoded_str.startswith("data: "):
                    # Extract the JSON part after "data: "
                    json_part = decoded_str[6:]  # Remove "data: " prefix
                    if json_part.strip() == "[DONE]":
                        return cls(is_done=True, raw_data=raw_data)
                    else:
                        # Parse the JSON part
                        try:
                            parsed_json = json.loads(json_part)
                            return cls.from_raw(parsed_json)
                        except json.JSONDecodeError:
                            content = json_part
                else:
                    return cls.from_raw(decoded_str)
            except UnicodeDecodeError:
                logger.warning(f"Could not decode bytes: {raw_data!r}")
                content = ""  # Or handle as an error case
        else:
            logger.warning(
                f"Unsupported raw data type for StreamingContent: {type(raw_data)}"
            )
            content = str(raw_data)  # Convert to string as a fallback

        return cls(
            content=content,
            is_done=is_done,
            metadata=metadata,
            usage=usage,
            raw_data=raw_data,
        )


class IStreamProcessor(ABC):
    """Interface for processing streaming content."""

    @abstractmethod
    async def process(self, content: StreamingContent) -> StreamingContent:
        """Process a streaming content chunk.

        Args:
            content: The content to process

        Returns:
            The processed content
        """
