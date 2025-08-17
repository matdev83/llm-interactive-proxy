"""
Tests for multimodal content support.
"""

from src.core.domain.multimodal import (
    ContentPart,
    ContentSource,
    ContentType,
    MultimodalMessage,
)


class TestContentPart:
    """Test the ContentPart class."""

    def test_text_content_part(self):
        """Test creating a text content part."""
        part = ContentPart.text("Hello, world!")

        assert part.type == ContentType.TEXT
        assert part.source == ContentSource.TEXT
        assert part.data == "Hello, world!"
        assert part.mime_type == "text/plain"

    def test_image_url_content_part(self):
        """Test creating an image URL content part."""
        url = "https://example.com/image.jpg"
        part = ContentPart.image_url(url)

        assert part.type == ContentType.IMAGE
        assert part.source == ContentSource.URL
        assert part.data == url
        assert part.mime_type == "image/jpeg"

    def test_image_base64_content_part(self):
        """Test creating an image base64 content part."""
        base64_data = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
        part = ContentPart.image_base64(base64_data, mime_type="image/png")

        assert part.type == ContentType.IMAGE
        assert part.source == ContentSource.BASE64
        assert part.data == base64_data
        assert part.mime_type == "image/png"

    def test_to_dict(self):
        """Test converting a content part to a dictionary."""
        part = ContentPart(
            type=ContentType.AUDIO,
            source=ContentSource.URL,
            data="https://example.com/audio.mp3",
            mime_type="audio/mp3",
            metadata={"duration": 120},
        )

        result = part.to_dict()

        assert result["type"] == ContentType.AUDIO
        assert result["source"] == ContentSource.URL
        assert result["data"] == "https://example.com/audio.mp3"
        assert result["mime_type"] == "audio/mp3"
        assert result["metadata"] == {"duration": 120}

    def test_to_openai_format_text(self):
        """Test converting a text content part to OpenAI format."""
        part = ContentPart.text("Hello, world!")
        result = part.to_openai_format()

        assert result["type"] == "text"
        assert result["text"] == "Hello, world!"

    def test_to_openai_format_image_url(self):
        """Test converting an image URL content part to OpenAI format."""
        url = "https://example.com/image.jpg"
        part = ContentPart.image_url(url)
        result = part.to_openai_format()

        assert result["type"] == "image_url"
        assert result["image_url"]["url"] == url

    def test_to_openai_format_image_base64(self):
        """Test converting an image base64 content part to OpenAI format."""
        base64_data = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
        part = ContentPart.image_base64(base64_data, mime_type="image/png")
        result = part.to_openai_format()

        assert result["type"] == "image_url"
        assert result["image_url"]["url"] == f"data:image/png;base64,{base64_data}"

    def test_to_anthropic_format_text(self):
        """Test converting a text content part to Anthropic format."""
        part = ContentPart.text("Hello, world!")
        result = part.to_anthropic_format()

        assert result["type"] == "text"
        assert result["text"] == "Hello, world!"

    def test_to_anthropic_format_image_url(self):
        """Test converting an image URL content part to Anthropic format."""
        url = "https://example.com/image.jpg"
        part = ContentPart.image_url(url)
        result = part.to_anthropic_format()

        assert result["type"] == "image"
        assert result["source"]["type"] == "url"
        assert result["source"]["url"] == url

    def test_to_anthropic_format_image_base64(self):
        """Test converting an image base64 content part to Anthropic format."""
        base64_data = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
        part = ContentPart.image_base64(base64_data, mime_type="image/png")
        result = part.to_anthropic_format()

        assert result["type"] == "image"
        assert result["source"]["type"] == "base64"
        assert result["source"]["media_type"] == "image/png"
        assert result["source"]["data"] == base64_data

    def test_to_gemini_format_text(self):
        """Test converting a text content part to Gemini format."""
        part = ContentPart.text("Hello, world!")
        result = part.to_gemini_format()

        assert "text" in result
        assert result["text"] == "Hello, world!"

    def test_to_gemini_format_image_base64(self):
        """Test converting an image base64 content part to Gemini format."""
        base64_data = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
        part = ContentPart.image_base64(base64_data, mime_type="image/png")
        result = part.to_gemini_format()

        assert "inline_data" in result
        assert result["inline_data"]["mime_type"] == "image/png"
        assert result["inline_data"]["data"] == base64_data


class TestMultimodalMessage:
    """Test the MultimodalMessage class."""

    def test_text_message(self):
        """Test creating a text message."""
        message = MultimodalMessage.text("user", "Hello, world!")

        assert message.role == "user"
        assert isinstance(message.content, list)
        assert len(message.content) == 1
        assert message.content[0].type == ContentType.TEXT
        assert message.content[0].data == "Hello, world!"

    def test_with_image_message(self):
        """Test creating a message with text and an image."""
        message = MultimodalMessage.with_image(
            "user", "Check out this image:", "https://example.com/image.jpg"
        )

        assert message.role == "user"
        assert isinstance(message.content, list)
        assert len(message.content) == 2
        assert message.content[0].type == ContentType.TEXT
        assert message.content[0].data == "Check out this image:"
        assert message.content[1].type == ContentType.IMAGE
        assert message.content[1].data == "https://example.com/image.jpg"

    def test_is_multimodal(self):
        """Test checking if a message is multimodal."""
        text_message = MultimodalMessage(role="user", content="Hello, world!")
        multimodal_message = MultimodalMessage.with_image(
            "user", "Check out this image:", "https://example.com/image.jpg"
        )

        assert not text_message.is_multimodal()
        assert multimodal_message.is_multimodal()

    def test_get_text_content(self):
        """Test getting the text content of a message."""
        text_message = MultimodalMessage(role="user", content="Hello, world!")
        multimodal_message = MultimodalMessage.with_image(
            "user", "Check out this image:", "https://example.com/image.jpg"
        )
        no_text_message = MultimodalMessage(
            role="user",
            content=[ContentPart.image_url("https://example.com/image.jpg")],
        )

        assert text_message.get_text_content() == "Hello, world!"
        assert multimodal_message.get_text_content() == "Check out this image:"
        assert no_text_message.get_text_content() == "[Multimodal content]"

    def test_to_dict(self):
        """Test converting a message to a dictionary."""
        message = MultimodalMessage.with_image(
            "user",
            "Check out this image:",
            "https://example.com/image.jpg",
            name="test_user",
        )

        result = message.to_dict()

        assert result["role"] == "user"
        assert result["name"] == "test_user"
        assert isinstance(result["content"], list)
        assert len(result["content"]) == 2
        assert result["content"][0]["type"] == ContentType.TEXT
        assert result["content"][1]["type"] == ContentType.IMAGE

    def test_to_legacy_format(self):
        """Test converting a message to legacy format."""
        message = MultimodalMessage.with_image(
            "user",
            "Check out this image:",
            "https://example.com/image.jpg",
            name="test_user",
        )

        result = message.to_legacy_format()

        assert result["role"] == "user"
        assert result["name"] == "test_user"
        assert result["content"] == "Check out this image:"

    def test_to_legacy_format_no_text(self):
        """Test converting a message with no text to legacy format."""
        message = MultimodalMessage(
            role="user",
            content=[ContentPart.image_url("https://example.com/image.jpg")],
            name="test_user",
        )

        result = message.to_legacy_format()

        assert result["role"] == "user"
        assert result["name"] == "test_user"
        assert result["content"] == "[Multimodal content]"

    def test_to_openai_format(self):
        """Test converting a message to OpenAI format."""
        message = MultimodalMessage.with_image(
            "user",
            "Check out this image:",
            "https://example.com/image.jpg",
            name="test_user",
        )

        result = message._to_openai_format()

        assert result["role"] == "user"
        assert result["name"] == "test_user"
        assert isinstance(result["content"], list)
        assert len(result["content"]) == 2
        assert result["content"][0]["type"] == "text"
        assert result["content"][1]["type"] == "image_url"

    def test_to_anthropic_format(self):
        """Test converting a message to Anthropic format."""
        message = MultimodalMessage.with_image(
            "user", "Check out this image:", "https://example.com/image.jpg"
        )

        result = message._to_anthropic_format()

        assert result["role"] == "user"
        assert isinstance(result["content"], list)
        assert len(result["content"]) == 2
        assert result["content"][0]["type"] == "text"
        assert result["content"][1]["type"] == "image"

    def test_to_gemini_format(self):
        """Test converting a message to Gemini format."""
        message = MultimodalMessage.with_image(
            "user", "Check out this image:", "https://example.com/image.jpg"
        )

        result = message._to_gemini_format()

        assert result["role"] == "user"
        assert isinstance(result["parts"], list)
        assert len(result["parts"]) == 2
        assert "text" in result["parts"][0]
        assert "inline_data" in result["parts"][1]

    def test_from_legacy_message(self):
        """Test creating a message from a legacy message."""
        legacy_message = {
            "role": "user",
            "content": "Hello, world!",
            "name": "test_user",
        }

        message = MultimodalMessage.from_legacy_message(legacy_message)

        assert message.role == "user"
        assert message.name == "test_user"
        assert isinstance(message.content, list)
        assert len(message.content) == 1
        assert message.content[0].type == ContentType.TEXT
        assert message.content[0].data == "Hello, world!"

    def test_backend_format_selection(self):
        """Test selecting the correct backend format."""
        message = MultimodalMessage.text("user", "Hello, world!")

        openai_result = message.to_backend_format("openai")
        anthropic_result = message.to_backend_format("anthropic")
        gemini_result = message.to_backend_format("gemini")
        unknown_result = message.to_backend_format("unknown")

        assert "content" in openai_result
        assert isinstance(openai_result["content"], list)

        assert "content" in anthropic_result
        assert isinstance(anthropic_result["content"], list)

        assert "parts" in gemini_result
        assert isinstance(gemini_result["parts"], list)

        assert "content" in unknown_result
        assert unknown_result["content"] == "Hello, world!"
