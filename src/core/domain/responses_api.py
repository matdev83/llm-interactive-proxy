"""Domain models for OpenAI Responses API.

This module contains the domain models for the OpenAI Responses API,
following the existing domain model patterns and compatible with the
TranslationService.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from pydantic import ConfigDict, Field, field_validator

from src.core.domain.base import ValueObject
from src.core.domain.chat import ChatMessage
from src.core.interfaces.model_bases import DomainModel


class JsonSchema(DomainModel):
    """Represents a JSON schema for structured output validation."""

    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(..., description="The name of the schema")
    description: str | None = Field(
        None, description="Optional description of the schema"
    )
    schema_dict: dict[str, Any] = Field(
        ..., description="The JSON schema definition", alias="schema"
    )
    strict: bool = Field(
        True, description="Whether to enforce strict schema validation"
    )

    def get_schema(self) -> dict[str, Any]:
        """Get a copy of the schema definition."""
        return deepcopy(self.schema_dict)

    @field_validator("schema_dict")
    @classmethod
    def validate_schema(cls, v: dict[str, Any]) -> dict[str, Any]:
        """Validate that the schema is a valid JSON schema structure."""
        if not isinstance(v, dict):
            raise ValueError("Schema must be a dictionary")

        if "type" not in v:
            raise ValueError("Schema must have a 'type' field")

        return deepcopy(v)

    def model_dump(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """Ensure aliases (e.g., 'schema') are used during serialization."""
        kwargs.setdefault("by_alias", True)
        return super().model_dump(*args, **kwargs)

    def model_post_init(self, __context: Any) -> None:  # type: ignore[override]
        """Ensure schema attribute remains accessible for compatibility."""
        object.__setattr__(self, "schema", self.get_schema())

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "schema":
            validated = self.__class__.validate_schema(value)
            object.__setattr__(self, "schema_dict", deepcopy(validated))
            object.__setattr__(self, "schema", deepcopy(validated))
        else:
            super().__setattr__(name, value)


class ResponseFormat(DomainModel):
    """Represents the response format specification for structured outputs."""

    type: str = Field("json_schema", description="The type of response format")
    json_schema: JsonSchema = Field(..., description="The JSON schema specification")

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        """Validate that the response format type is supported."""
        if v != "json_schema":
            raise ValueError(
                "Only 'json_schema' response format type is currently supported"
            )
        return v

    def model_dump(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """Serialize nested models using aliases."""
        kwargs.setdefault("by_alias", True)
        return super().model_dump(*args, **kwargs)


class ResponsesRequest(ValueObject):
    """A request for the OpenAI Responses API.

    This model represents a request to generate structured outputs with JSON schema validation.
    It extends the existing domain model patterns and is compatible with the TranslationService.
    """

    model: str = Field(..., description="The model to use for generation")
    messages: list[ChatMessage] = Field(..., description="The conversation messages")
    response_format: ResponseFormat = Field(
        ..., description="The structured response format"
    )
    max_tokens: int | None = Field(
        None, description="Maximum number of tokens to generate"
    )
    temperature: float | None = Field(
        None, ge=0.0, le=2.0, description="Sampling temperature"
    )
    top_p: float | None = Field(
        None, ge=0.0, le=1.0, description="Nucleus sampling parameter"
    )
    n: int | None = Field(None, ge=1, description="Number of completions to generate")
    stream: bool | None = Field(None, description="Whether to stream the response")
    stop: list[str] | str | None = Field(None, description="Stop sequences")
    presence_penalty: float | None = Field(
        None, ge=-2.0, le=2.0, description="Presence penalty"
    )
    frequency_penalty: float | None = Field(
        None, ge=-2.0, le=2.0, description="Frequency penalty"
    )
    logit_bias: dict[str, float] | None = Field(
        None, description="Logit bias adjustments"
    )
    user: str | None = Field(None, description="User identifier")
    seed: int | None = Field(None, description="Random seed for reproducibility")
    session_id: str | None = Field(None, description="Session identifier")
    agent: str | None = Field(None, description="Agent identifier")
    extra_body: dict[str, Any] | None = Field(
        None, description="Additional request parameters"
    )

    @field_validator("messages")
    @classmethod
    def validate_messages(cls, v: list[Any]) -> list[ChatMessage]:
        """Validate and convert messages."""
        if not v:
            raise ValueError("At least one message is required")
        return [m if isinstance(m, ChatMessage) else ChatMessage(**m) for m in v]

    @field_validator("n")
    @classmethod
    def validate_n(cls, v: int | None) -> int | None:
        """Validate that n is positive if provided."""
        if v is not None and v < 1:
            raise ValueError("n must be at least 1")
        return v

    def model_dump(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """Ensure nested response format serializes with aliases."""
        kwargs.setdefault("by_alias", True)
        return super().model_dump(*args, **kwargs)


class ResponseMessage(DomainModel):
    """Represents a message in a Responses API response."""

    role: str = Field("assistant", description="The role of the message sender")
    content: str = Field(..., description="The message content")
    parsed: dict[str, Any] | None = Field(
        None, description="The parsed structured output"
    )

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        """Validate that the role is 'assistant' for response messages."""
        if v != "assistant":
            raise ValueError("Response message role must be 'assistant'")
        return v


class ResponseChoice(DomainModel):
    """Represents a choice in a Responses API response."""

    index: int = Field(..., description="The index of this choice")
    message: ResponseMessage = Field(..., description="The response message")
    finish_reason: str = Field(..., description="The reason the generation finished")

    @field_validator("index")
    @classmethod
    def validate_index(cls, v: int) -> int:
        """Validate that the index is non-negative."""
        if v < 0:
            raise ValueError("Choice index must be non-negative")
        return v

    @field_validator("finish_reason")
    @classmethod
    def validate_finish_reason(cls, v: str) -> str:
        """Validate that the finish reason is one of the expected values."""
        valid_reasons = {
            "stop",
            "length",
            "content_filter",
            "tool_calls",
            "function_call",
        }
        if v not in valid_reasons:
            # Allow other finish reasons for flexibility with different backends
            pass
        return v


class ResponsesResponse(ValueObject):
    """A response from the OpenAI Responses API.

    This model represents the structured response format returned by the Responses API,
    following the existing domain model patterns.
    """

    id: str = Field(..., description="Unique identifier for the response")
    object: str = Field("response", description="The object type")
    created: int = Field(
        ..., description="Unix timestamp of when the response was created"
    )
    model: str = Field(..., description="The model used for generation")
    choices: list[ResponseChoice] = Field(..., description="The generated choices")
    usage: dict[str, Any] | None = Field(None, description="Token usage information")
    system_fingerprint: str | None = Field(None, description="System fingerprint")

    @field_validator("object")
    @classmethod
    def validate_object(cls, v: str) -> str:
        """Validate that the object type is 'response'."""
        if v != "response":
            raise ValueError("Object type must be 'response'")
        return v

    @field_validator("choices")
    @classmethod
    def validate_choices(cls, v: list[Any]) -> list[ResponseChoice]:
        """Validate and convert choices."""
        if not v:
            raise ValueError("At least one choice is required")
        return [c if isinstance(c, ResponseChoice) else ResponseChoice(**c) for c in v]

    @field_validator("created")
    @classmethod
    def validate_created(cls, v: int) -> int:
        """Validate that the created timestamp is positive."""
        if v <= 0:
            raise ValueError("Created timestamp must be positive")
        return v


# Streaming response models for future use
class StreamingResponsesChoice(DomainModel):
    """Represents a streaming choice in a Responses API response."""

    index: int = Field(..., description="The index of this choice")
    delta: dict[str, Any] = Field(..., description="The incremental content delta")
    finish_reason: str | None = Field(
        None, description="The reason the generation finished"
    )


class StreamingResponsesResponse(ValueObject):
    """A streaming chunk from the OpenAI Responses API."""

    id: str = Field(..., description="Unique identifier for the response")
    object: str = Field("response.chunk", description="The object type for streaming")
    created: int = Field(
        ..., description="Unix timestamp of when the response was created"
    )
    model: str = Field(..., description="The model used for generation")
    choices: list[StreamingResponsesChoice] = Field(
        ..., description="The streaming choices"
    )
    system_fingerprint: str | None = Field(None, description="System fingerprint")

    @field_validator("object")
    @classmethod
    def validate_object(cls, v: str) -> str:
        """Validate that the object type is 'response.chunk'."""
        if v != "response.chunk":
            raise ValueError("Streaming object type must be 'response.chunk'")
        return v
