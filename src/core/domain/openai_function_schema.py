"""OpenAI-compatible function tool schema (shared typing boundary)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class OpenAIFunctionSchema(BaseModel):
    """OpenAI function schema format for advertised tools."""

    type: str = Field(
        default="function", description="Type identifier (always 'function')"
    )
    name: str = Field(description="Function name")
    description: str = Field(default="", description="Function description")
    strict: bool = Field(default=False, description="Whether strict mode is enabled")
    parameters: dict[str, Any] = Field(
        default_factory=dict, description="JSON Schema parameters"
    )
