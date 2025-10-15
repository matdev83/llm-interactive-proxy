"""
Pydantic models for Anthropic API request/response structures.
"""

from typing import Any

from pydantic import AliasChoices, Field, field_validator

from src.core.interfaces.model_bases import DomainModel


class AnthropicMessage(DomainModel):
    """Represents a message in the Anthropic API."""

    role: str
    content: str | list[dict[str, Any]]


class AnthropicMessagesRequest(DomainModel):
    """Represents a request to the Anthropic Messages API."""

    model: str
    messages: list[AnthropicMessage]
    system: str | None = None

    @field_validator("system", mode="before")
    @classmethod
    def clean_system_field(cls, value: Any) -> str | None:
        """Allow 'system' to be a list with a single text block, like [{'text': '...'}]."""
        if isinstance(value, list) and value:
            first_item = value[0]
            if isinstance(first_item, dict) and "text" in first_item:
                return str(first_item["text"])
        if isinstance(value, str):
            return value
        return None

    max_tokens: int | None = Field(
        default=None,
        validation_alias=AliasChoices("max_output_tokens", "max_tokens"),
    )
    metadata: dict[str, Any] | None = None
    stop_sequences: list[str] | None = Field(default=None, alias="stop_sequences")
    stream: bool | None = False
    temperature: float | None = None
    top_p: float | None = None
    top_k: int | None = None
    tools: list[dict[str, Any]] | None = None
    tool_choice: str | dict[str, Any] | None = None


class ContentBlock(DomainModel):
    """Represents a content block in an Anthropic message."""

    type: str
    text: str


class ToolUseBlock(DomainModel):
    """Represents a tool invocation block in Anthropic messages."""

    type: str = "tool_use"
    id: str | None = None
    name: str | None = None


class Usage(DomainModel):
    """Represents the usage statistics for a request."""

    input_tokens: int
    output_tokens: int


class AnthropicMessagesResponse(DomainModel):
    """Represents a response from the Anthropic Messages API."""

    id: str
    type: str
    role: str
    content: list[ContentBlock]
    model: str
    stop_reason: str | None = Field(None, alias="stop_reason")
    usage: Usage
