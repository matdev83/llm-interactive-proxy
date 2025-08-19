from unittest.mock import Mock

from src.core.domain.chat import ChatResponse
from src.core.services.request_processor_service import RequestProcessor


def make_processor() -> RequestProcessor:
    # Create a RequestProcessor with minimal mocked dependencies
    return RequestProcessor(Mock(), Mock(), Mock(), Mock())


def test_extract_response_content_with_dict() -> None:
    # proc = make_processor()
    mock_response_data = {
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "Hello"}}]
    }
    response = ChatResponse.from_legacy_response(mock_response_data)

    content = response.choices[0].message.content
    assert content == "Hello"


def test_extract_response_content_with_object_choices() -> None:
    # proc = make_processor()

    # Simulate a ChatResponse-like object with .choices attribute
    mock_response_data = {
        "choices": [
            {"index": 0, "message": {"role": "assistant", "content": "Hi there"}}
        ]
    }
    fake_response = ChatResponse.from_legacy_response(mock_response_data)

    content = fake_response.choices[0].message.content
    assert content == "Hi there"



