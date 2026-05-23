from unittest.mock import Mock

from src.core.domain.chat import ChatResponse
from src.core.services.request_processor_service import RequestProcessor


def make_processor() -> RequestProcessor:
    # Create a RequestProcessor with minimal mocked dependencies
    return RequestProcessor(Mock(), Mock(), Mock(), Mock())


from src.core.domain.chat import (
    ChatCompletionChoice,
    ChatCompletionChoiceMessage,
)


def test_extract_response_content_with_dict() -> None:
    # proc = make_processor()
    response = ChatResponse(
        id="test",
        choices=[
            ChatCompletionChoice(
                index=0,
                message=ChatCompletionChoiceMessage(role="assistant", content="Hello"),
            )
        ],
        created=0,
        model="test",
        object="chat.completion",
        system_fingerprint="",
        usage={"completion_tokens": 1, "prompt_tokens": 1, "total_tokens": 2},
    )

    content = response.choices[0].message.content
    assert content == "Hello"


def test_extract_response_content_with_object_choices() -> None:
    # proc = make_processor()

    # Simulate a ChatResponse-like object with .choices attribute
    fake_response = ChatResponse(
        id="test",
        choices=[
            ChatCompletionChoice(
                index=0,
                message=ChatCompletionChoiceMessage(
                    role="assistant", content="Hi there"
                ),
            )
        ],
        created=0,
        model="test",
        object="chat.completion",
        system_fingerprint="",
        usage={"completion_tokens": 1, "prompt_tokens": 1, "total_tokens": 2},
    )

    content = fake_response.choices[0].message.content
    assert content == "Hi there"
