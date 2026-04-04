from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ProtocolFamily = Literal["openai", "anthropic", "gemini"]


class BackendCapabilityDescriptor(BaseModel):
    """Typed capability descriptor for a backend instance.

    Declared in config under each backend's capability_descriptor key.
    Routing and validation read these flags instead of inferring from
    implicit backend attributes or hard-coded provider names.
    """

    protocol_family: ProtocolFamily = Field(
        default="openai",
        description="Wire protocol family this backend speaks",
    )
    supports_streaming: bool = Field(
        default=True,
        description="Backend supports SSE streaming responses",
    )
    supports_tool_calls: bool = Field(
        default=True,
        description="Backend supports tool/function calling",
    )
    supports_vision: bool = Field(
        default=False,
        description="Backend accepts image inputs",
    )
    supports_json_mode: bool = Field(
        default=False,
        description="Backend supports structured JSON output mode",
    )
    max_context_tokens: int | None = Field(
        default=None,
        description="Maximum context window in tokens (None = unknown)",
    )

    @classmethod
    def from_dict(cls, data: dict) -> BackendCapabilityDescriptor:
        return cls.model_validate(data)
