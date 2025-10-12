from src.core.app.controllers.chat_controller import ChatController
from src.core.domain.chat import MessageContentPartText


def test_coerce_message_content_to_text_handles_sequence_parts() -> None:
    """Ensure multimodal sequences retain textual payloads when flattened."""

    content = [
        MessageContentPartText(text="First"),
        {"type": "text", "text": "Second"},
        "Third",
    ]

    result = ChatController._coerce_message_content_to_text(content)

    assert result == "First\n\nSecond\n\nThird"


def test_coerce_message_content_to_text_decodes_bytes() -> None:
    """Byte content should be decoded instead of being dropped."""

    payload = b"binary-text"

    result = ChatController._coerce_message_content_to_text(payload)

    assert result == "binary-text"


def test_coerce_message_content_to_text_handles_nested_model_dump() -> None:
    """Domain models using model_dump should still surface their text."""

    part = MessageContentPartText(text="Nested")

    result = ChatController._coerce_message_content_to_text(part)

    assert result == "Nested"
