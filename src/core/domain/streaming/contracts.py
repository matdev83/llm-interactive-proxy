"""
Typed contracts for streaming data.

This module defines Pydantic v2 models for strongly-typed streaming chunk
representations, providing a canonical structure for payload, metadata,
usage, and error envelopes that can be used across layer boundaries.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from src.core.domain.chat import ToolCall


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


class StreamingMetadata(BaseModel):
    """Metadata for streaming chunks."""

    model_config = ConfigDict(extra="forbid")

    provider: str | None = None
    stream_id: str | None = None
    finish_reason: str | None = None
    role: str | None = None
    tool_calls: list[ToolCall] | None = None
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


__all__ = [
    "StreamingErrorInfo",
    "StreamingUsage",
    "StreamingMetadata",
    "StreamingPayload",
    "StreamingChunk",
]
