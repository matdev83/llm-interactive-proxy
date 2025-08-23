"""
Enhanced multimodal content support for chat messages.

This module provides enhanced models for representing multimodal content
in chat messages, including text, images, audio, and other media types.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal, TypedDict

from src.core.domain.base import ValueObject


class OpenAIContentPartText(TypedDict):
    type: Literal["text"]
    text: str


class OpenAIContentPartImage(TypedDict):
    type: Literal["image_url"]
    image_url: dict[Literal["url"], str]


OpenAIContent = str | list[OpenAIContentPartText | OpenAIContentPartImage]


class AnthropicContentPartText(TypedDict):
    type: Literal["text"]
    text: str


class AnthropicContentPartImageSource(TypedDict):
    type: Literal["url", "base64"]
    url: str | None
    media_type: str | None
    data: str | None


class AnthropicContentPartImage(TypedDict):
    type: Literal["image"]
    source: AnthropicContentPartImageSource


AnthropicContent = list[AnthropicContentPartText | AnthropicContentPartImage]


class GeminiContentPartText(TypedDict):
    text: str


class GeminiContentPartImage(TypedDict):
    inline_data: dict[Literal["mime_type", "data"], str]


GeminiContent = list[GeminiContentPartText | GeminiContentPartImage]


class OpenAIFormat(TypedDict):
    role: str
    content: OpenAIContent
    name: str | None
    tool_calls: list[dict[str, Any]] | None
    tool_call_id: str | None


class AnthropicFormat(TypedDict):
    role: str
    content: AnthropicContent


class GeminiFormat(TypedDict):
    role: str
    parts: GeminiContent


class ContentType(str, Enum):
    """Types of content that can be included in a message."""

    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    FILE = "file"
    CUSTOM = "custom"


class ContentSource(str, Enum):
    """Source types for content data."""

    URL = "url"
    BASE64 = "base64"
    FILE_PATH = "file_path"
    TEXT = "text"
    CUSTOM = "custom"


class ContentPart(ValueObject):
    """A single part of multimodal content."""

    type: ContentType
    source: ContentSource
    data: str
    mime_type: str | None = None
    metadata: dict[str, Any] | None = None

    @classmethod
    def text(cls, text: str) -> ContentPart:
        """Create a text content part."""
        return cls(
            type=ContentType.TEXT,
            source=ContentSource.TEXT,
            data=text,
            mime_type="text/plain",
        )

    @classmethod
    def image_url(cls, url: str, mime_type: str | None = None) -> ContentPart:
        """Create an image content part from a URL."""
        return cls(
            type=ContentType.IMAGE,
            source=ContentSource.URL,
            data=url,
            mime_type=mime_type or "image/jpeg",
        )

    @classmethod
    def image_base64(
        cls, base64_data: str, mime_type: str | None = None
    ) -> ContentPart:
        """Create an image content part from base64 data."""
        return cls(
            type=ContentType.IMAGE,
            source=ContentSource.BASE64,
            data=base64_data,
            mime_type=mime_type or "image/jpeg",
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to a dictionary."""
        result: dict[str, Any] = {
            "type": self.type,
            "source": self.source,
            "data": self.data,
        }

        if self.mime_type:
            result["mime_type"] = self.mime_type

        if self.metadata:
            result["metadata"] = self.metadata

        return result

    def to_openai_format(self) -> dict[str, Any]:
        """Convert to OpenAI format."""
        if self.type == ContentType.TEXT:
            return {"type": "text", "text": self.data}
        elif self.type == ContentType.IMAGE:
            if self.source == ContentSource.URL:
                return {"type": "image_url", "image_url": {"url": self.data}}
            elif self.source == ContentSource.BASE64:
                return {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{self.mime_type or 'image/jpeg'};base64,{self.data}"
                    },
                }

        # Default fallback for unsupported types
        return {"type": "text", "text": f"[{self.type} content]"}

    def to_anthropic_format(self) -> dict[str, Any]:
        """Convert to Anthropic format."""
        if self.type == ContentType.TEXT:
            return {"type": "text", "text": self.data}
        elif self.type == ContentType.IMAGE:
            if self.source == ContentSource.URL:
                return {"type": "image", "source": {"type": "url", "url": self.data}}
            elif self.source == ContentSource.BASE64:
                return {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": self.mime_type or "image/jpeg",
                        "data": self.data,
                    },
                }

        # Default fallback for unsupported types
        return {"type": "text", "text": f"[{self.type} content]"}

    def to_gemini_format(self) -> dict[str, Any]:
        """Convert to Gemini format."""
        if self.type == ContentType.TEXT:
            return {"text": self.data}
        elif self.type == ContentType.IMAGE:
            if self.source == ContentSource.URL:
                return {
                    "inline_data": {
                        "mime_type": self.mime_type or "image/jpeg",
                        "data": f"URL:{self.data}",  # Gemini doesn't support direct URLs, this is a placeholder
                    }
                }
            elif self.source == ContentSource.BASE64:
                return {
                    "inline_data": {
                        "mime_type": self.mime_type or "image/jpeg",
                        "data": self.data,
                    }
                }

        # Default fallback for unsupported types
        return {"text": f"[{self.type} content]"}


class MultimodalMessage(ValueObject):
    """Enhanced chat message with multimodal content support."""

    role: str
    content: str | list[ContentPart] | None = None
    name: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None

    def is_multimodal(self) -> bool:
        """Check if this message contains multimodal content."""
        return isinstance(self.content, list)

    def get_text_content(self) -> str:
        """Get the text content of the message."""
        if self.content is None:
            return ""

        if isinstance(self.content, str):
            return self.content

        # Extract text from content parts
        text_parts = []
        for part in self.content:
            if part.type == ContentType.TEXT:
                text_parts.append(part.data)

        return " ".join(text_parts) if text_parts else "[Multimodal content]"

    def to_dict(self) -> dict[str, Any]:
        """Convert to a dictionary."""
        result: dict[str, Any] = {"role": self.role}

        # Handle content based on type
        if self.content is not None:
            if isinstance(self.content, str):
                result["content"] = self.content
            else:
                result["content"] = [part.to_dict() for part in self.content]

        # Add other fields
        if self.name:
            result["name"] = self.name
        if self.tool_calls:
            result["tool_calls"] = self.tool_calls
        if self.tool_call_id:
            result["tool_call_id"] = self.tool_call_id

        return result

    def to_backend_format(self, backend_type: str) -> dict[str, Any]:
        """Convert to backend-specific format."""
        if backend_type == "openai":
            return self._to_openai_format()
        elif backend_type == "anthropic":
            return self._to_anthropic_format()
        elif backend_type == "gemini":
            return self._to_gemini_format()
        else:
            # Fallback for unsupported types, consider raising an error or a default conversion
            return self._to_openai_format()

    def _to_openai_format(self) -> dict[str, Any]:
        """Convert to OpenAI format."""
        result: dict[str, Any] = {"role": self.role}

        # Handle name if present
        if self.name:
            result["name"] = self.name

        # Handle content
        if self.content is not None:
            if isinstance(self.content, str):
                result["content"] = self.content
            else:
                result["content"] = [part.to_openai_format() for part in self.content]

        # Handle tool calls
        if self.tool_calls:
            result["tool_calls"] = self.tool_calls

        # Handle tool call ID
        if self.tool_call_id:
            result["tool_call_id"] = self.tool_call_id

        return result

    def _to_anthropic_format(self) -> dict[str, Any]:
        """Convert to Anthropic format."""
        # Map roles to Anthropic roles
        role_mapping = {
            "user": "user",
            "assistant": "assistant",
            "system": "system",
            "tool": "assistant",  # Anthropic doesn't have a tool role
        }

        result: dict[str, Any] = {"role": role_mapping.get(self.role, self.role)}

        # Handle content
        if self.content is not None:
            if isinstance(self.content, str):
                result["content"] = [{"type": "text", "text": self.content}]
            else:
                result["content"] = [
                    part.to_anthropic_format() for part in self.content
                ]
        else:
            result["content"] = []

        return result

    def _to_gemini_format(self) -> dict[str, Any]:
        """Convert to Gemini format."""
        # Map roles to Gemini roles
        role_mapping = {
            "user": "user",
            "assistant": "model",
            "system": "system",
            "tool": "function",
        }

        result: dict[str, Any] = {"role": role_mapping.get(self.role, self.role)}

        # Handle content
        if self.content is not None:
            if isinstance(self.content, str):
                result["parts"] = [{"text": self.content}]
            else:
                result["parts"] = [part.to_gemini_format() for part in self.content]
        else:
            result["parts"] = []

        return result

    @classmethod
    def text(
        cls, role: str, content: str, name: str | None = None
    ) -> MultimodalMessage:
        """Create a text-only message."""
        return cls(role=role, content=[ContentPart.text(content)], name=name)

    @classmethod
    def with_image(
        cls, role: str, text: str, image_url: str, name: str | None = None
    ) -> MultimodalMessage:
        """Create a message with text and an image."""
        return cls(
            role=role,
            content=[ContentPart.text(text), ContentPart.image_url(image_url)],
            name=name,
        )
