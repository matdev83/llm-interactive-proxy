"""
Pydantic models for Anthropic API request/response structures.

Based on official Anthropic Messages API specification.
See: https://docs.anthropic.com/en/api/messages
"""

from typing import Any, Literal

from pydantic import AliasChoices, Field, field_validator

from src.core.interfaces.model_bases import DomainModel


class AnthropicMessage(DomainModel):
    """Represents a message in the Anthropic API."""

    role: str
    content: str | list[dict[str, Any]]


class ThinkingConfig(DomainModel):
    """Configuration for Claude's extended thinking feature.

    When enabled, responses include 'thinking' content blocks showing
    Claude's reasoning process before the final answer.
    """

    type: Literal["enabled", "disabled"]
    budget_tokens: int | None = Field(
        default=None,
        description="Token budget for thinking. Must be >= 1024 and < max_tokens. Required when type is 'enabled'.",
    )


class AnthropicMessagesRequest(DomainModel):
    """Represents a request to the Anthropic Messages API.

    Based on official Anthropic API specification.
    """

    model: str
    messages: list[AnthropicMessage]
    system: str | list[dict[str, Any]] | None = None

    @field_validator("system", mode="before")
    @classmethod
    def clean_system_field(cls, value: Any) -> str | list[dict[str, Any]] | None:
        """Allow 'system' to be a string or list of text blocks with cache_control."""
        if isinstance(value, list):
            # Keep list format for cache_control support
            # But if it's a simple list with just text, extract the text
            if len(value) == 1 and isinstance(value[0], dict):
                first_item = value[0]
                # Simple text block without cache_control - convert to string
                if (
                    first_item.get("type") == "text"
                    and "text" in first_item
                    and "cache_control" not in first_item
                ):
                    return str(first_item["text"])
                # Has cache_control or other properties - keep as list
                if "text" in first_item:
                    return value
            # Multiple blocks or complex structure - keep as list
            return value
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

    # New fields per Anthropic API spec
    service_tier: Literal["auto", "standard_only"] | None = Field(
        default=None,
        description="Determines whether to use priority capacity or standard capacity.",
    )
    anthropic_beta: list[str] | str | None = Field(
        default=None,
        description="Optional beta features (e.g. prompt-caching-2024-07-31).",
    )
    thinking: ThinkingConfig | dict[str, Any] | None = Field(
        default=None,
        description="Configuration for extended thinking. Enables Claude to show reasoning process.",
    )


class TextBlock(DomainModel):
    """Represents a text content block in an Anthropic message."""

    type: Literal["text"] = "text"
    text: str
    citations: list[dict[str, Any]] | None = None


class ImageSource(DomainModel):
    """Represents an image source in Anthropic API."""

    type: Literal["base64", "url"]
    media_type: str | None = Field(
        default=None,
        description="MIME type: image/jpeg, image/png, image/gif, image/webp",
    )
    data: str | None = Field(default=None, description="Base64-encoded image data")
    url: str | None = Field(default=None, description="URL of the image")


class ImageBlock(DomainModel):
    """Represents an image content block in an Anthropic message."""

    type: Literal["image"] = "image"
    source: ImageSource


class DocumentSource(DomainModel):
    """Represents a document source (e.g., PDF) in Anthropic API."""

    type: Literal["base64", "url", "file"]
    media_type: str | None = Field(
        default=None, description="MIME type, e.g., application/pdf"
    )
    data: str | None = Field(default=None, description="Base64-encoded document data")
    url: str | None = Field(default=None, description="URL of the document")
    file_id: str | None = Field(default=None, description="File ID for uploaded files")


class DocumentBlock(DomainModel):
    """Represents a document content block (e.g., PDF) in an Anthropic message."""

    type: Literal["document"] = "document"
    source: DocumentSource
    title: str | None = None
    context: str | None = None
    citations: dict[str, Any] | None = None


class ToolUseBlock(DomainModel):
    """Represents a tool invocation block in Anthropic messages."""

    type: Literal["tool_use"] = "tool_use"
    id: str
    name: str
    input: dict[str, Any] = Field(default_factory=dict)


class ToolResultBlock(DomainModel):
    """Represents a tool result block in Anthropic messages."""

    type: Literal["tool_result"] = "tool_result"
    tool_use_id: str
    content: str | list[dict[str, Any]] | None = None
    is_error: bool | None = None


class ThinkingBlock(DomainModel):
    """Represents a thinking content block in an Anthropic response."""

    type: Literal["thinking"] = "thinking"
    thinking: str
    signature: str | None = None


class RedactedThinkingBlock(DomainModel):
    """Represents a redacted thinking content block."""

    type: Literal["redacted_thinking"] = "redacted_thinking"
    data: str


# Union type for all content blocks
ContentBlock = (
    TextBlock
    | ImageBlock
    | DocumentBlock
    | ToolUseBlock
    | ToolResultBlock
    | ThinkingBlock
    | RedactedThinkingBlock
    | dict[str, Any]  # Allow unknown block types for forward compatibility
)


class Usage(DomainModel):
    """Represents the usage statistics for a request."""

    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int | None = None
    cache_read_input_tokens: int | None = None


class AnthropicMessagesResponse(DomainModel):
    """Represents a response from the Anthropic Messages API."""

    id: str
    type: Literal["message"] = "message"
    role: Literal["assistant"] = "assistant"
    content: list[ContentBlock]  # type: ignore[valid-type]
    model: str
    stop_reason: (
        Literal[
            "end_turn",
            "max_tokens",
            "stop_sequence",
            "tool_use",
            "pause_turn",
            "refusal",
        ]
        | None
    ) = Field(None, alias="stop_reason")
    stop_sequence: str | None = Field(
        None,
        description="The stop sequence that was matched, if stop_reason is 'stop_sequence'",
    )
    usage: Usage
