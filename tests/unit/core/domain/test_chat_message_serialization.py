"""Tests for ChatMessage serialization helpers."""

from src.core.domain.chat import (
    ChatMessage,
    ImageURL,
    MessageContentPart,
    MessageContentPartImage,
    MessageContentPartText,
)


def test_serialize_content_string_branch() -> None:
    assert ChatMessage._serialize_content("plain") == "plain"


def test_serialize_content_domain_model_branch() -> None:
    part = MessageContentPartText(text="x")
    out = ChatMessage._serialize_content(part)
    assert out == {"type": "text", "text": "x"}


def test_serialize_content_sequence_branch() -> None:
    parts: list[MessageContentPart] = [
        MessageContentPartText(text="a"),
        MessageContentPartImage(
            image_url=ImageURL(url="https://example.com/i.png", detail="low")
        ),
    ]
    out = ChatMessage._serialize_content(parts)
    assert out == [
        {"type": "text", "text": "a"},
        {
            "type": "image_url",
            "image_url": {"url": "https://example.com/i.png", "detail": "low"},
        },
    ]


def test_serialize_content_none() -> None:
    assert ChatMessage._serialize_content(None) is None


def test_chat_message_to_dict_with_multimodal_content() -> None:
    message = ChatMessage(
        role="user",
        content=[
            MessageContentPartText(text="Line 1"),
            MessageContentPartImage(
                image_url=ImageURL(url="https://example.com/image.png", detail=None)
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
