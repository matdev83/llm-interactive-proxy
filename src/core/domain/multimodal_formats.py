"""
Pydantic models for multimodal content backend formats.

This module defines the data structures for different backend-specific
multimodal content formats, replacing manual dictionary construction
with type-safe Pydantic models.
"""

from typing import Any

from pydantic import BaseModel, Field


# OpenAI Format Models
class OpenAITextContent(BaseModel):
    """OpenAI text content format."""

    type: str = Field(default="text", description="Content type")
    text: str = Field(description="Text content")


class OpenAIImageUrl(BaseModel):
    """OpenAI image URL structure."""

    url: str = Field(description="Image URL or data URI")
    detail: str | None = Field(default=None, description="Image detail level")


class OpenAIImageContent(BaseModel):
    """OpenAI image content format."""

    type: str = Field(default="image_url", description="Content type")
    image_url: OpenAIImageUrl = Field(description="Image URL information")


class OpenAIAudioContent(BaseModel):
    """OpenAI audio content format."""

    type: str = Field(default="audio", description="Content type")
    audio_url: dict[str, str] = Field(description="Audio URL information")


class OpenAIVideoContent(BaseModel):
    """OpenAI video content format."""

    type: str = Field(default="video", description="Content type")
    video_url: dict[str, str] = Field(description="Video URL information")


OpenAIContentPart = (
    OpenAITextContent | OpenAIImageContent | OpenAIAudioContent | OpenAIVideoContent
)


class OpenAIMultimodalMessage(BaseModel):
    """OpenAI multimodal message format."""

    role: str = Field(description="Message role")
    content: str | list[OpenAIContentPart] = Field(description="Message content")
    name: str | None = Field(default=None, description="Message name")

    def model_dump(self, **kwargs) -> dict[str, Any]:
        """Convert to dictionary format expected by OpenAI API."""
        result = super().model_dump(**kwargs)
        # Convert Union types to proper dictionaries
        if isinstance(result.get("content"), list):
            content_list = []
            for item in result["content"]:
                if hasattr(item, "model_dump"):
                    content_list.append(item.model_dump())
                else:
                    content_list.append(item)
            result["content"] = content_list
        return result


# Anthropic Format Models
class AnthropicTextContent(BaseModel):
    """Anthropic text content format."""

    type: str = Field(default="text", description="Content type")
    text: str = Field(description="Text content")


class AnthropicImageSource(BaseModel):
    """Anthropic image source information."""

    type: str = Field(description="Source type (url, base64)")
    url: str | None = Field(default=None, description="Image URL")
    media_type: str | None = Field(default=None, description="Media type for base64")
    data: str | None = Field(default=None, description="Base64 data")


class AnthropicImageContent(BaseModel):
    """Anthropic image content format."""

    type: str = Field(default="image", description="Content type")
    source: AnthropicImageSource = Field(description="Image source information")


class AnthropicAudioContent(BaseModel):
    """Anthropic audio content format."""

    type: str = Field(default="audio", description="Content type")
    source: dict[str, Any] = Field(description="Audio source information")


class AnthropicVideoContent(BaseModel):
    """Anthropic video content format."""

    type: str = Field(default="video", description="Content type")
    source: dict[str, Any] = Field(description="Video source information")


AnthropicContentPart = (
    AnthropicTextContent
    | AnthropicImageContent
    | AnthropicAudioContent
    | AnthropicVideoContent
)


class AnthropicMultimodalMessage(BaseModel):
    """Anthropic multimodal message format."""

    role: str = Field(description="Message role")
    content: str | list[AnthropicContentPart] = Field(description="Message content")
    name: str | None = Field(default=None, description="Message name")

    def model_dump(self, **kwargs) -> dict[str, Any]:
        """Convert to dictionary format expected by Anthropic API."""
        result = super().model_dump(**kwargs)
        # Convert Union types to proper dictionaries
        if isinstance(result.get("content"), list):
            content_list = []
            for item in result["content"]:
                if hasattr(item, "model_dump"):
                    content_list.append(item.model_dump())
                else:
                    content_list.append(item)
            result["content"] = content_list
        return result


# Gemini Format Models
class GeminiTextPart(BaseModel):
    """Gemini text part format."""

    text: str = Field(description="Text content")


class GeminiInlineData(BaseModel):
    """Gemini inline data structure."""

    mime_type: str = Field(description="MIME type of the data")
    data: str = Field(description="Base64 encoded data")


class GeminiInlineDataPart(BaseModel):
    """Gemini inline data part format."""

    inline_data: GeminiInlineData = Field(description="Inline data information")


class GeminiFileData(BaseModel):
    """Gemini file data structure."""

    mime_type: str = Field(description="MIME type of the file")
    file_uri: str = Field(description="URI of the file")


class GeminiFileDataPart(BaseModel):
    """Gemini file data part format."""

    file_data: GeminiFileData = Field(description="File data information")


GeminiContentPart = GeminiTextPart | GeminiInlineDataPart | GeminiFileDataPart


class GeminiMultimodalMessage(BaseModel):
    """Gemini multimodal message format."""

    role: str = Field(description="Message role")
    parts: list[GeminiContentPart] = Field(description="Message parts")

    def model_dump(self, **kwargs) -> dict[str, Any]:
        """Convert to dictionary format expected by Gemini API."""
        result = super().model_dump(**kwargs)
        # Convert Union types to proper dictionaries
        parts_list = []
        for part in result["parts"]:
            if hasattr(part, "model_dump"):
                parts_list.append(part.model_dump())
            else:
                parts_list.append(part)
        result["parts"] = parts_list
        return result


# Factory functions for creating backend-specific content
def create_openai_text_content(text: str) -> OpenAITextContent:
    """Create OpenAI text content."""
    return OpenAITextContent(text=text)


def create_openai_image_content(
    url: str, detail: str | None = None
) -> OpenAIImageContent:
    """Create OpenAI image content."""
    return OpenAIImageContent(image_url=OpenAIImageUrl(url=url, detail=detail))


def create_anthropic_text_content(text: str) -> AnthropicTextContent:
    """Create Anthropic text content."""
    return AnthropicTextContent(text=text)


def create_anthropic_image_content(
    source_type: str,
    url: str | None = None,
    media_type: str | None = None,
    data: str | None = None,
) -> AnthropicImageContent:
    """Create Anthropic image content."""
    source = AnthropicImageSource(
        type=source_type, url=url, media_type=media_type, data=data
    )
    return AnthropicImageContent(source=source)


def create_gemini_text_part(text: str) -> GeminiTextPart:
    """Create Gemini text part."""
    return GeminiTextPart(text=text)


def create_gemini_inline_data_part(mime_type: str, data: str) -> GeminiInlineDataPart:
    """Create Gemini inline data part."""
    return GeminiInlineDataPart(
        inline_data=GeminiInlineData(mime_type=mime_type, data=data)
    )


def create_gemini_file_data_part(mime_type: str, file_uri: str) -> GeminiFileDataPart:
    """Create Gemini file data part."""
    return GeminiFileDataPart(
        file_data=GeminiFileData(mime_type=mime_type, file_uri=file_uri)
    )
