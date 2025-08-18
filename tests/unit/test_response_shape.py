from typing import Any
from unittest.mock import Mock

from src.core.domain.chat import ChatResponse
from src.core.services.request_processor_service import RequestProcessor


def make_processor() -> RequestProcessor:
    # Create a RequestProcessor with minimal mocked dependencies
    return RequestProcessor(Mock(), Mock(), Mock(), Mock())


def test_extract_response_content_with_dict():
    proc = make_processor()
    mock_response_data = {
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "Hello"}}]
    }
    response = ChatResponse.from_legacy_response(mock_response_data)

    content = proc._extract_response_content(response)
    assert content == "Hello"


def test_extract_response_content_with_object_choices():
    proc = make_processor()

    # Simulate a ChatResponse-like object with .choices attribute
    mock_response_data = {
        "choices": [
            {"index": 0, "message": {"role": "assistant", "content": "Hi there"}}
        ]
    }
    fake_response = ChatResponse.from_legacy_response(mock_response_data)

    content = proc._extract_response_content(fake_response)
    assert content == "Hi there"


def test_extract_response_content_with_tuple_is_invalid():
    """
    Historically some tests accidentally returned a tuple like (dict, {}) from mocked
    backend calls which caused AttributeError at runtime. Ensure such shapes are
    treated as invalid by the extractor (and will therefore surface in tests).
    """
    proc = make_processor()
    bad_response: Any = ({"choices": []}, {})

    try:
        _ = proc._extract_response_content(bad_response)  # type: ignore[arg-type]
    except Exception as e:
        # We expect an AttributeError or TypeError when a tuple is passed
        assert isinstance(e, (AttributeError | TypeError))
    else:
        raise AssertionError("Tuple response should be treated as invalid")
