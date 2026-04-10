"""
Typed contracts for streaming data.

This module defines Pydantic v2 models for strongly-typed streaming chunk
representations, providing a canonical structure for payload, metadata,
usage, and error envelopes that can be used across layer boundaries.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.core.domain.chat import StreamingToolCall, ToolCall


class StreamingErrorInfo(BaseModel):
    """Error envelope for streaming chunks."""

    model_config = ConfigDict(extra="forbid")

    type: str
    message: str
    code: str | None = None
    retryable: bool | None = None
    status_code: int | None = None


class StreamingUsage(BaseModel):
    """Token usage information for streaming chunks."""

    model_config = ConfigDict(extra="forbid")

    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    cache_creation_input_tokens: int | None = None
    cache_read_input_tokens: int | None = None

    @model_validator(mode="before")
    @classmethod
    def _map_anthropic_style_usage_keys(cls, data: Any) -> Any:
        """Anthropic/Messages API streams use input_tokens/output_tokens naming."""

        if not isinstance(data, dict):
            return data
        mapped = dict(data)
        if "prompt_tokens" not in mapped and "input_tokens" in mapped:
            mapped["prompt_tokens"] = mapped.get("input_tokens")
        if "completion_tokens" not in mapped and "output_tokens" in mapped:
            mapped["completion_tokens"] = mapped.get("output_tokens")
        mapped.pop("input_tokens", None)
        mapped.pop("output_tokens", None)
        return mapped


class StreamingMetadata(BaseModel):
    """Metadata for streaming chunks."""

    model_config = ConfigDict(extra="forbid")

    provider: str | None = None
    stream_id: str | None = None
    finish_reason: str | None = None
    role: str | None = None
    tool_calls: list[ToolCall | StreamingToolCall] | None = None
    reasoning_content: str | None = None

    error: StreamingErrorInfo | None = None
    usage: StreamingUsage | None = None


class StreamingPayload(BaseModel):
    """Payload content for streaming chunks."""

    model_config = ConfigDict(extra="allow")

    kind: Literal["text", "opaque_json", "binary", "empty", "opaque_json_dict"] = (
        "empty"
    )
    text: str | None = None
    opaque_json: str | None = None
    binary_b64: str | None = None
    opaque_json_dict: dict[str, Any] | None = None


class StreamingChunk(BaseModel):
    """Complete streaming chunk with typed payload and metadata."""

    model_config = ConfigDict(extra="forbid")

    payload: StreamingPayload = Field(default_factory=StreamingPayload)
    metadata: StreamingMetadata = Field(default_factory=StreamingMetadata)
    is_done: bool = False
    is_empty: bool = False
    is_cancellation: bool = False


class OpenAIError(BaseModel):
    """OpenAI-compatible error object."""

    message: str
    type: str
    code: str | int | None = None

    model_config = ConfigDict(extra="forbid")


class OpenAIErrorChoice(BaseModel):
    """Choice object for OpenAI error chunks."""

    index: int = 0
    delta: dict[str, Any] = Field(default_factory=dict)
    finish_reason: str = "error"

    model_config = ConfigDict(extra="forbid")


class OpenAIErrorChunk(BaseModel):
    """Standard OpenAI-compatible error chunk for streaming responses."""

    id: str
    object: str = "chat.completion.chunk"
    created: int
    model: str
    choices: list[OpenAIErrorChoice] = Field(
        default_factory=lambda: [OpenAIErrorChoice()]
    )
    error: OpenAIError

    model_config = ConfigDict(extra="forbid")


__all__ = [
    "StreamingErrorInfo",
    "StreamingUsage",
    "StreamingMetadata",
    "StreamingPayload",
    "StreamingChunk",
    "OpenAIError",
    "OpenAIErrorChoice",
    "OpenAIErrorChunk",
]
