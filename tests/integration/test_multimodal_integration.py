"""
Integration tests for multimodal content support.

These tests verify that the multimodal content support works correctly
with different backends and in different scenarios.
"""

import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from src.core.app.application_factory import build_app
from src.core.domain.multimodal import (
    ContentPart,
    ContentSource,
    ContentType,
    MultimodalMessage,
)

# Mark all tests in this module as integration tests
pytestmark = pytest.mark.integration


class TestMultimodalIntegration:
    """Test multimodal content integration with different backends."""

    @pytest.fixture
    def app(self):
        """Create a FastAPI app for testing."""
        with patch("src.core.config_adapter._load_config", return_value={}):
            os.environ["DISABLE_AUTH"] = "true"
            os.environ["DISABLE_ACCOUNTING"] = "true"

            app = build_app()
            yield app

    @pytest.fixture
    def client(self, app):
        """TestClient for the app."""
        with TestClient(app) as client:
            yield client

    def test_openai_multimodal_conversion(self):
        """Test converting multimodal content to OpenAI format."""
        # Create a multimodal message
        message = MultimodalMessage.with_image(
            "user", "Describe this image:", "https://example.com/image.jpg"
        )

        # Convert to OpenAI format
        openai_format = message.to_backend_format("openai")

        # Verify the conversion
        assert openai_format["role"] == "user"
        assert isinstance(openai_format["content"], list)
        assert len(openai_format["content"]) == 2
        assert openai_format["content"][0]["type"] == "text"
        assert openai_format["content"][0]["text"] == "Describe this image:"
        assert openai_format["content"][1]["type"] == "image_url"
        assert (
            openai_format["content"][1]["image_url"]["url"]
            == "https://example.com/image.jpg"
        )

    def test_anthropic_multimodal_conversion(self):
        """Test converting multimodal content to Anthropic format."""
        # Create a multimodal message
        message = MultimodalMessage.with_image(
            "user", "Describe this image:", "https://example.com/image.jpg"
        )

        # Convert to Anthropic format
        anthropic_format = message.to_backend_format("anthropic")

        # Verify the conversion
        assert anthropic_format["role"] == "user"
        assert isinstance(anthropic_format["content"], list)
        assert len(anthropic_format["content"]) == 2
        assert anthropic_format["content"][0]["type"] == "text"
        assert anthropic_format["content"][0]["text"] == "Describe this image:"
        assert anthropic_format["content"][1]["type"] == "image"
        assert anthropic_format["content"][1]["source"]["type"] == "url"
        assert (
            anthropic_format["content"][1]["source"]["url"]
            == "https://example.com/image.jpg"
        )

    def test_gemini_multimodal_conversion(self):
        """Test converting multimodal content to Gemini format."""
        # Create a multimodal message
        message = MultimodalMessage.with_image(
            "user", "Describe this image:", "https://example.com/image.jpg"
        )

        # Convert to Gemini format
        gemini_format = message.to_backend_format("gemini")

        # Verify the conversion
        assert gemini_format["role"] == "user"
        assert isinstance(gemini_format["parts"], list)
        assert len(gemini_format["parts"]) == 2
        assert "text" in gemini_format["parts"][0]
        assert gemini_format["parts"][0]["text"] == "Describe this image:"
        assert "inline_data" in gemini_format["parts"][1]

    def test_legacy_compatibility(self):
        """Test compatibility with legacy message format."""
        # Create a legacy message
        legacy_message = {
            "role": "user",
            "content": "Hello, world!",
            "name": "test_user",
        }

        # Convert to multimodal message
        multimodal_message = MultimodalMessage.from_legacy_message(legacy_message)

        # Verify the conversion
        assert multimodal_message.role == "user"
        assert multimodal_message.name == "test_user"
        assert isinstance(multimodal_message.content, list)
        assert len(multimodal_message.content) == 1
        assert multimodal_message.content[0].type == ContentType.TEXT
        assert multimodal_message.content[0].data == "Hello, world!"

        # Convert back to legacy format
        back_to_legacy = multimodal_message.to_legacy_format()

        # Verify the conversion back
        assert back_to_legacy["role"] == legacy_message["role"]
        assert back_to_legacy["name"] == legacy_message["name"]
        assert back_to_legacy["content"] == legacy_message["content"]

    def test_complex_multimodal_message(self):
        """Test a complex multimodal message with multiple content parts."""
        # Create a complex multimodal message
        message = MultimodalMessage(
            role="user",
            name="test_user",
            content=[
                ContentPart.text("Here are some images:"),
                ContentPart.image_url("https://example.com/image1.jpg"),
                ContentPart.image_url("https://example.com/image2.jpg"),
                ContentPart.text("Please describe them."),
            ],
        )

        # Verify the message structure
        assert message.role == "user"
        assert message.name == "test_user"
        assert isinstance(message.content, list)
        assert len(message.content) == 4
        assert message.content[0].type == ContentType.TEXT
        assert message.content[1].type == ContentType.IMAGE
        assert message.content[2].type == ContentType.IMAGE
        assert message.content[3].type == ContentType.TEXT

        # Get text content
        text_content = message.get_text_content()
        assert text_content == "Here are some images: Please describe them."

        # Convert to legacy format
        legacy_format = message.to_legacy_format()
        assert legacy_format["content"] == "Here are some images: Please describe them."

        # Convert to OpenAI format
        openai_format = message.to_backend_format("openai")
        assert len(openai_format["content"]) == 4

        # Convert to Anthropic format
        anthropic_format = message.to_backend_format("anthropic")
        assert len(anthropic_format["content"]) == 4

        # Convert to Gemini format
        gemini_format = message.to_backend_format("gemini")
        assert len(gemini_format["parts"]) == 4

    def test_mixed_content_types(self):
        """Test a message with mixed content types."""
        # Create a message with mixed content types
        message = MultimodalMessage(
            role="user",
            content=[
                ContentPart.text("Here's an audio file:"),
                ContentPart(
                    type=ContentType.AUDIO,
                    source=ContentSource.URL,
                    data="https://example.com/audio.mp3",
                    mime_type="audio/mp3",
                ),
                ContentPart.text("And here's a video:"),
                ContentPart(
                    type=ContentType.VIDEO,
                    source=ContentSource.URL,
                    data="https://example.com/video.mp4",
                    mime_type="video/mp4",
                ),
            ],
        )

        # Verify the message structure
        assert message.role == "user"
        assert isinstance(message.content, list)
        assert len(message.content) == 4
        assert message.content[0].type == ContentType.TEXT
        assert message.content[1].type == ContentType.AUDIO
        assert message.content[2].type == ContentType.TEXT
        assert message.content[3].type == ContentType.VIDEO

        # Get text content
        text_content = message.get_text_content()
        assert text_content == "Here's an audio file: And here's a video:"

        # Convert to legacy format
        legacy_format = message.to_legacy_format()
        assert legacy_format["content"] == "Here's an audio file: And here's a video:"
