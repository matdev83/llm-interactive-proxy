from __future__ import annotations

import json
import logging
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
        return not bool(self.content)

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
        data = {"choices": [{"delta": {"content": self.content}}]}

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

        Args:
            raw_data: The raw data received from the streaming source.

        Returns:
            A StreamingContent object.
        """
        content = ""
        is_done = False
        metadata: dict[str, Any] = {}
        usage: dict[str, Any] | None = None

        if isinstance(raw_data, dict):
            # Handle dictionary (e.g., OpenAI chat completion chunk)
            is_done = raw_data.get("done", False)

            choices = raw_data.get("choices")
            if choices and isinstance(choices, list) and len(choices) > 0:
                choice = choices[0]
                if isinstance(choice, dict):
                    if "delta" in choice:
                        delta = choice["delta"]
                        if isinstance(delta, dict) and "content" in delta:
                            content = delta.get("content") or ""
                    elif "message" in choice:
                        message = choice["message"]
                        if isinstance(message, dict) and "content" in message:
                            content = message.get("content") or ""
                    elif "text" in choice:  # For older models or specific APIs
                        content = choice.get("text") or ""

            if "id" in raw_data:
                metadata["id"] = raw_data["id"]
            if "model" in raw_data:
                metadata["model"] = raw_data["model"]
            if "created" in raw_data:
                metadata["created"] = raw_data["created"]

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
