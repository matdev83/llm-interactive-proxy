from typing import Any, TypeVar

from pydantic import Field, field_validator

from src.core.domain.base import ValueObject
from src.core.interfaces.model_bases import DomainModel

# Define a type variable for generic methods
T = TypeVar("T", bound=DomainModel)


# For multimodal content parts
class MessageContentPartText(DomainModel):
    """Represents a text content part in a multimodal message."""

    type: str = "text"
    text: str


class ImageURL(DomainModel):
    """Specifies the URL and optional detail for an image in a multimodal message."""

    # Should be a data URI (e.g., "data:image/jpeg;base64,...") or public URL
    url: str
    detail: str | None = Field(None, examples=["auto", "low", "high"])


class MessageContentPartImage(DomainModel):
    """Represents an image content part in a multimodal message."""

    type: str = "image_url"
    image_url: ImageURL


# Extend with other multimodal types as needed (e.g., audio, video file, documents)
# For now, text and image are common starting points.
MessageContentPart = MessageContentPartText | MessageContentPartImage
"""Type alias for possible content parts in a multimodal message."""


class FunctionCall(DomainModel):
    """Represents a function call within a tool call."""

    name: str
    arguments: str


class ToolCall(DomainModel):
    """Represents a tool call in a chat completion response."""

    id: str
    type: str = "function"
    function: FunctionCall


class FunctionDefinition(DomainModel):
    """Represents a function definition for tool calling."""

    name: str
    description: str | None = None
    parameters: dict[str, Any] | None = None


class ToolDefinition(DomainModel):
    """Represents a tool definition in a chat completion request."""

    type: str = "function"
    function: FunctionDefinition

    @field_validator("function", mode="before")
    @classmethod
    def ensure_function_is_dict(cls, v: Any) -> dict[str, Any] | FunctionDefinition:
        # Accept either a FunctionDefinition or a ToolDefinition/FunctionDefinition instance
        # and normalize to a dict for ChatRequest validation
        if isinstance(v, FunctionDefinition):
            return v.model_dump()
        # If v is already a dict, return it as is
        if isinstance(v, dict):
            return v
        # If v is something else, try to convert it to a dict
        # This should handle cases where v is a dict-like object
        try:
            return dict(v)  # type: ignore
        except (TypeError, ValueError):
            # If we can't convert to dict, raise a ValueError to let Pydantic handle the error properly
            raise ValueError(f"Cannot convert {type(v)} to dict or FunctionDefinition")


class ChatMessage(DomainModel):
    """
    A chat message in a conversation.
    """

    role: str
    content: str | list[MessageContentPart] | None = None
    name: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert the message to a dictionary."""
        result: dict[str, Any] = {"role": self.role}
        if self.content is not None:
            result["content"] = self.content
        if self.name:
            result["name"] = self.name
        if self.tool_calls:
            result["tool_calls"] = [tc.model_dump() for tc in self.tool_calls]
        if self.tool_call_id:
            result["tool_call_id"] = self.tool_call_id
        return result


class ChatRequest(ValueObject):
    """
    A request for a chat completion.
    """

    model: str
    messages: list[ChatMessage]
    temperature: float | None = None
    top_p: float | None = None
    n: int | None = None
    stream: bool | None = None
    stop: list[str] | str | None = None
    max_tokens: int | None = None
    presence_penalty: float | None = None
    frequency_penalty: float | None = None
    logit_bias: dict[str, float] | None = None
    user: str | None = None
    tools: list[dict[str, Any]] | None = None
    tool_choice: str | dict[str, Any] | None = None
    session_id: str | None = None
    extra_body: dict[str, Any] | None = None

    # Reasoning parameters for o1, o3, o4-mini and other reasoning models
    reasoning_effort: float | None = None
    reasoning: dict[str, Any] | None = None

    # Gemini-specific reasoning parameters
    thinking_budget: int | None = None
    generation_config: dict[str, Any] | None = None

    @field_validator("messages")
    @classmethod
    def validate_messages(cls, v: list[Any]) -> list[ChatMessage]:
        """Validate and convert messages."""
        if not v:
            raise ValueError("At least one message is required")
        return [m if isinstance(m, ChatMessage) else ChatMessage(**m) for m in v]

    @field_validator("tools", mode="before")
    @classmethod
    def validate_tools(cls, v: Any) -> list[dict[str, Any]] | None:
        """Allow passing ToolDefinition instances or dicts for tools."""
        if v is None:
            return None
        result: list[dict[str, Any]] = []
        for item in v:
            if isinstance(item, ToolDefinition):
                result.append(item.model_dump())
            elif isinstance(item, dict):
                result.append(item)
            else:
                # Attempt to coerce
                try:
                    td = ToolDefinition(**item)
                    result.append(td.model_dump())
                except Exception:
                    raise ValueError("Invalid tool definition")
        return result

    def to_legacy_format(self) -> dict[str, Any]:
        """
        Convert to a format compatible with the legacy code.

        Returns:
            A dictionary representation for legacy code
        """
        result = {"model": self.model, "messages": [m.to_dict() for m in self.messages]}

        # Add optional fields if they have values
        for field_name in self.model_fields:
            if field_name not in ["model", "messages", "session_id", "extra_body"]:
                value = getattr(self, field_name)
                if value is not None:
                    result[field_name] = value

        # Add extra_body fields directly to result
        if self.extra_body:
            result.update(self.extra_body)

        return result


class ChatCompletionChoiceMessage(DomainModel):
    """Represents the message content within a chat completion choice."""

    role: str
    content: str | None = None
    tool_calls: list[ToolCall] | None = None


class ChatCompletionChoice(DomainModel):
    """Represents a single choice in a chat completion response."""

    index: int
    message: ChatCompletionChoiceMessage
    finish_reason: str | None = None


# ChatUsage class is defined elsewhere in this file


class ChatResponse(ValueObject):
    """
    A response from a chat completion.
    """

    id: str
    created: int
    model: str
    choices: list[ChatCompletionChoice]
    usage: dict[str, Any] | None = None
    system_fingerprint: str | None = None
    object: str = "chat.completion"

    @classmethod
    def from_legacy_response(cls, response: dict[str, Any]) -> "ChatResponse":
        """
        Create a ChatResponse from a legacy response format.

        Args:
            response: A legacy response dictionary

        Returns:
            A new ChatResponse
        """
        # Extract required fields with defaults
        id: str = response.get("id", "")
        created: int = response.get("created", 0)
        model: str = response.get("model", "unknown")
        choices: list[Any] = response.get("choices", [])

        # Extract optional fields
        usage: dict[str, Any] | None = response.get("usage")
        system_fingerprint: str | None = response.get("system_fingerprint")

        return cls(
            id=id,
            created=created,
            model=model,
            choices=choices,
            usage=usage,
            system_fingerprint=system_fingerprint,
        )


class StreamingChatResponse(ValueObject):
    """
    A streaming chunk of a chat completion response.
    """

    content: str | None
    model: str
    finish_reason: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    delta: dict[str, Any] | None = None
    system_fingerprint: str | None = None

    @classmethod
    def from_legacy_chunk(cls, chunk: dict[str, Any]) -> "StreamingChatResponse":
        """
        Create a StreamingChatResponse from a legacy chunk format.

        Args:
            chunk: A legacy streaming chunk

        Returns:
            A new StreamingChatResponse
        """
        # Extract the response content and other fields from the chunk
        content: str | None = None
        if chunk.get("choices"):
            choice: dict[str, Any] = chunk["choices"][0]
            if "delta" in choice:
                delta: dict[str, Any] = choice["delta"]
                if "content" in delta:
                    content = delta["content"]

                # Might have tool calls in delta
                tool_calls: list[dict[str, Any]] | None = delta.get("tool_calls")

                # The delta is the actual delta object
                delta_obj: dict[str, Any] | None = delta
            else:
                # Simpler format
                content = choice.get("text", "")
                tool_calls = None
                delta_obj = None

            # Extract finish reason if present
            finish_reason: str | None = choice.get("finish_reason")
        else:
            # Anthropic format
            if "content" in chunk:
                if isinstance(chunk["content"], list):
                    content_parts: list[str] = [
                        p["text"] for p in chunk["content"] if p.get("type") == "text"
                    ]
                    content = "".join(content_parts)
                else:
                    content = chunk["content"]

            tool_calls = chunk.get("tool_calls")
            delta_obj = None
            finish_reason = chunk.get("stop_reason")

        # Extract model
        model: str = chunk.get("model", "unknown")

        # Extract system fingerprint
        system_fingerprint: str | None = chunk.get("system_fingerprint")

        return cls(
            content=content,
            model=model,
            finish_reason=finish_reason,
            tool_calls=tool_calls,
            delta=delta_obj,
            system_fingerprint=system_fingerprint,
        )


# ChatUsage class is defined elsewhere in this file