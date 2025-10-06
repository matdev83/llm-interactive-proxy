"""Tests for ChatMessage serialization helpers."""

from src.core.domain.chat import (
    ChatMessage,
    ImageURL,
    MessageContentPartImage,
    MessageContentPartText,
)


def test_chat_message_to_dict_with_multimodal_content() -> None:
    message = ChatMessage(
        role="user",
        content=[
            MessageContentPartText(text="Line 1"),
            MessageContentPartImage(
                image_url=ImageURL(url="https://example.com/image.png")
            ),
        ],
    )

    result = message.to_dict()

    assert result == {
        "role": "user",
        "content": [
            {"type": "text", "text": "Line 1"},
            {
                "type": "image_url",
                "image_url": {"url": "https://example.com/image.png", "detail": None},
            },
        ],
    }


def test_chat_message_to_dict_preserves_string_content() -> None:
    message = ChatMessage(role="assistant", content="Hello world")

    result = message.to_dict()

    assert result == {"role": "assistant", "content": "Hello world"}
