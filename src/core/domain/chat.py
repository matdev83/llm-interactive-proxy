from __future__ import annotations

from typing import Any, TypeVar

from pydantic import BaseModel, field_validator

from src.core.domain.base import ValueObject

# Define a type variable for generic methods
T = TypeVar("T", bound="BaseModel")


class ChatMessage(BaseModel):
    """
    A chat message in a conversation.
    """

    role: str
    content: str | None
    name: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert the message to a dictionary."""
        result: dict[str, Any] = {"role": self.role}
        if self.content is not None:
            result["content"] = self.content
        if self.name:
            result["name"] = self.name
        if self.tool_calls:
            result["tool_calls"] = self.tool_calls
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
    reasoning_effort: float | None = None
    reasoning: str | None = None
    thinking_budget: int | None = None
    generation_config: dict[str, Any] | None = None

    @field_validator("messages")
    @classmethod
    def validate_messages(cls, v: list[Any]) -> list[ChatMessage]:
        """Validate and convert messages."""
        if not v:
            raise ValueError("At least one message is required")
        return [m if isinstance(m, ChatMessage) else ChatMessage(**m) for m in v]

    def to_legacy_format(self) -> dict[str, Any]:
        """
        Convert to a format compatible with the legacy code.

        Returns:
            A dictionary representation for legacy code
        """
        result = {"model": self.model, "messages": [m.to_dict() for m in self.messages]}

        # Add optional fields if they have values
        for field in self.__fields__:
            if field not in ["model", "messages", "session_id", "extra_body"]:
                value = getattr(self, field)
                if value is not None:
                    result[field] = value

        # Add extra_body fields directly to result
        if self.extra_body:
            result.update(self.extra_body)

        return result


class ChatResponse(ValueObject):
    """
    A response from a chat completion.
    """

    id: str
    created: int
    model: str
    choices: list[dict[str, Any]]
    usage: dict[str, Any] | None = None
    system_fingerprint: str | None = None

    @classmethod
    def from_legacy_response(cls, response: dict[str, Any]) -> ChatResponse:
        """
        Create a ChatResponse from a legacy response format.

        Args:
            response: A legacy response dictionary

        Returns:
            A new ChatResponse
        """
        # Extract required fields with defaults
        id = response.get("id", "")
        created = response.get("created", 0)
        model = response.get("model", "unknown")
        choices = response.get("choices", [])

        # Extract optional fields
        usage = response.get("usage")
        system_fingerprint = response.get("system_fingerprint")

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
    def from_legacy_chunk(cls, chunk: dict[str, Any]) -> StreamingChatResponse:
        """
        Create a StreamingChatResponse from a legacy chunk format.

        Args:
            chunk: A legacy streaming chunk

        Returns:
            A new StreamingChatResponse
        """
        # Extract the response content and other fields from the chunk
        content = None
        if chunk.get("choices"):
            choice = chunk["choices"][0]
            if "delta" in choice:
                delta = choice["delta"]
                if "content" in delta:
                    content = delta["content"]

                # Might have tool calls in delta
                tool_calls = delta.get("tool_calls")

                # The delta is the actual delta object
                delta_obj = delta
            else:
                # Simpler format
                content = choice.get("text", "")
                tool_calls = None
                delta_obj = None

            # Extract finish reason if present
            finish_reason = choice.get("finish_reason")
        else:
            # Anthropic format
            if "content" in chunk:
                if isinstance(chunk["content"], list):
                    content_parts = [
                        p["text"] for p in chunk["content"] if p.get("type") == "text"
                    ]
                    content = "".join(content_parts)
                else:
                    content = chunk["content"]

            tool_calls = chunk.get("tool_calls")
            delta_obj = None
            finish_reason = chunk.get("stop_reason")

        # Extract model
        model = chunk.get("model", "unknown")

        # Extract system fingerprint
        system_fingerprint = chunk.get("system_fingerprint")

        return cls(
            content=content,
            model=model,
            finish_reason=finish_reason,
            tool_calls=tool_calls,
            delta=delta_obj,
            system_fingerprint=system_fingerprint,
        )


class ChatUsage(BaseModel):
    """
    Usage information for a chat completion.
    """

    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
