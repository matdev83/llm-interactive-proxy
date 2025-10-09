"""
Unit tests for Gemini API converter functions.
Tests the conversion logic between Gemini and OpenAI formats.
"""

import json

from src.core.domain.chat import (
    ChatMessage,
    MessageContentPartImage,
    MessageContentPartText,
)
from src.gemini_converters import (
    gemini_to_openai_messages,
    openai_to_gemini_contents,
    openai_to_gemini_stream_chunk,
)
from src.gemini_models import (
    Blob,
    Content,
    FileData,
    Part,
)


class TestMessageConversion:
    """Test message conversion between formats."""

    def test_gemini_to_openai_simple_message(self) -> None:
        """Test converting simple Gemini content to OpenAI messages."""
        contents = [Content(parts=[Part(text="Hello, how are you?")], role="user")]

        messages = gemini_to_openai_messages(contents)

        assert len(messages) == 1
        assert messages[0].role == "user"
        assert messages[0].content == "Hello, how are you?"

    def test_gemini_to_openai_model_role(self) -> None:
        """Test converting Gemini model role to OpenAI assistant role."""
        contents = [
            Content(parts=[Part(text="I'm doing well, thank you!")], role="model")
        ]

        messages = gemini_to_openai_messages(contents)

        assert len(messages) == 1
        assert messages[0].role == "assistant"
        assert messages[0].content == "I'm doing well, thank you!"

    def test_gemini_to_openai_multiple_parts(self) -> None:
        """Test converting Gemini content with multiple parts."""
        contents = [
            Content(
                parts=[
                    Part(text="Look at this: "),
                    Part(inline_data=Blob(mime_type="image/png", data="base64data")),
                    Part(text=" What do you think?"),
                ],
                role="user",
            )
        ]

        messages = gemini_to_openai_messages(contents)

        assert len(messages) == 1
        assert messages[0].role == "user"
        assert isinstance(messages[0].content, list)
        parts = messages[0].content
        assert len(parts) == 3
        assert isinstance(parts[0], MessageContentPartText)
        assert parts[0].text == "Look at this: "
        assert isinstance(parts[1], MessageContentPartImage)
        assert (
            parts[1].image_url.url
            == "data:image/png;base64,base64data"
        )
        assert isinstance(parts[2], MessageContentPartText)
        assert parts[2].text == " What do you think?"

    def test_gemini_inline_data_only(self) -> None:
        """Ensure inline_data content is preserved as data URI."""
        contents = [
            Content(
                parts=[
                    Part(
                        inline_data=Blob(
                            mime_type="image/jpeg", data="abcd1234"
                        )
                    )
                ],
                role="user",
            )
        ]

        messages = gemini_to_openai_messages(contents)

        assert len(messages) == 1
        assert isinstance(messages[0].content, list)
        image_part = messages[0].content[0]
        assert isinstance(image_part, MessageContentPartImage)
        assert (
            image_part.image_url.url == "data:image/jpeg;base64,abcd1234"
        )

    def test_gemini_file_data_preserves_uri(self) -> None:
        """Ensure file-based parts are converted to image URL parts."""
        contents = [
            Content(
                parts=[
                    Part(
                        file_data=FileData(
                            mime_type="image/png",
                            file_uri="https://example.com/image.png",
                        )
                    )
                ],
                role="user",
            )
        ]

        messages = gemini_to_openai_messages(contents)

        assert len(messages) == 1
        assert isinstance(messages[0].content, list)
        file_part = messages[0].content[0]
        assert isinstance(file_part, MessageContentPartImage)
        assert file_part.image_url.url == "https://example.com/image.png"

    def test_gemini_inline_data_non_image_placeholder(self) -> None:
        """Non-image inline data should produce a textual placeholder."""
        contents = [
            Content(
                parts=[
                    Part(
                        inline_data=Blob(
                            mime_type="application/pdf", data="ZmFrZWJhc2U2NA=="
                        )
                    )
                ],
                role="user",
            )
        ]

        messages = gemini_to_openai_messages(contents)

        assert len(messages) == 1
        assert messages[0].content == "[Attachment: inline data (application/pdf)]"

    def test_gemini_file_data_non_image_placeholder(self) -> None:
        """Non-image file data should produce a textual placeholder."""
        contents = [
            Content(
                parts=[
                    Part(
                        file_data=FileData(
                            mime_type="application/pdf",
                            file_uri="https://example.com/document.pdf",
                        )
                    )
                ],
                role="user",
            )
        ]

        messages = gemini_to_openai_messages(contents)

        assert len(messages) == 1
        assert (
            messages[0].content
            == "[Attachment: https://example.com/document.pdf (application/pdf)]"
        )

    def test_openai_to_gemini_simple_message(self) -> None:
        """Test converting OpenAI message to Gemini content."""
        messages = [ChatMessage(role="user", content="Hello!")]

        contents = openai_to_gemini_contents(messages)

        assert len(contents) == 1
        assert contents[0].role == "user"
        assert len(contents[0].parts) == 1
        assert contents[0].parts[0].text == "Hello!"

    def test_openai_to_gemini_assistant_role(self) -> None:
        """Test converting OpenAI assistant role to Gemini model role."""
        messages = [ChatMessage(role="assistant", content="Hello there!")]

        contents = openai_to_gemini_contents(messages)

        assert len(contents) == 1
        assert contents[0].role == "model"
        assert contents[0].parts[0].text == "Hello there!"

    def test_openai_to_gemini_system_role(self) -> None:
        """Test that system messages are filtered out."""
        messages = [
            ChatMessage(role="system", content="You are a helpful assistant."),
            ChatMessage(role="user", content="Hello!"),
        ]

        contents = openai_to_gemini_contents(messages)

        # Only user message should remain, system message filtered out
        assert len(contents) == 1
        assert contents[0].role == "user"
        assert contents[0].parts[0].text == "Hello!"

    def test_openai_stream_chunk_with_structured_content(self) -> None:
        """Ensure streaming conversion handles list-based delta content."""
        chunk = (
            'data: {"choices": [{"index": 0, "delta": {'
            '"content": [{"type": "text", "text": "Hello"}]}}]}\n\n'
        )

        gemini_chunk = openai_to_gemini_stream_chunk(chunk)
        assert gemini_chunk.startswith("data: ")

        payload = gemini_chunk[6:].strip()
        data = json.loads(payload)

        assert data["candidates"][0]["content"]["parts"][0]["text"] == "Hello"
