from __future__ import annotations

import json
from typing import Any

from hypothesis import given
from hypothesis import strategies as st
from src.core.domain.chat import (
    CanonicalChatRequest,
    ChatMessage,
    ImageURL,
    MessageContentPartImage,
    MessageContentPartText,
)
from src.core.domain.translation import Translation
from src.core.domain.translation_utils import media_utils

from tests.utils.hypothesis_config import property_test_settings


@st.composite
def tool_arguments_strategy(draw: Any) -> object:
    primitive = st.one_of(
        st.none(),
        st.booleans(),
        st.integers(min_value=-10, max_value=10),
        st.floats(allow_nan=False, allow_infinity=False),
        st.text(min_size=0, max_size=200),
    )
    jsonable = st.recursive(
        primitive,
        lambda children: st.lists(children, max_size=10)
        | st.dictionaries(st.text(min_size=0, max_size=20), children, max_size=10),
        max_leaves=15,
    )

    invalid_json_like = st.sampled_from(
        [
            "{'query': 'weather",  # unterminated string
            "{",  # incomplete
            "[",  # incomplete
            "not json at all",
        ]
    )
    return draw(st.one_of(jsonable, invalid_json_like))


@given(args_value=tool_arguments_strategy())
@property_test_settings()
def test_property_6_edge_case_normalize_tool_arguments_always_valid_json(
    args_value: object,
) -> None:
    """
    **Feature: cross-api-translation-refactoring, Property 6: Edge Case Handling Preservation**
    **Validates: Requirements 10.1**

    For any tool arguments (including malformed JSON-like strings), normalization SHALL
    return a valid JSON string without raising.
    """
    normalized = Translation._normalize_tool_arguments(args_value)
    json.loads(normalized)


def test_gemini_stream_chunk_handles_null_text_part() -> None:
    """
    **Feature: cross-api-translation-refactoring, Property 6: Edge Case Handling Preservation**
    **Validates: Requirements 10.5**
    """
    chunk = {"candidates": [{"content": {"parts": [{"text": None}]}}]}
    result = Translation.gemini_to_domain_stream_chunk(chunk)
    assert hasattr(result, "choices")
    assert result.choices[0].delta.content in (None, "")


def test_gemini_stream_chunk_preserves_thought_signature_in_tool_calls() -> None:
    """
    **Feature: cross-api-translation-refactoring, Property 6: Edge Case Handling Preservation**
    **Validates: Requirements 10.4**
    """
    chunk = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "functionCall": {
                                "name": "get_weather",
                                "args": {"city": "X"},
                            },
                            "thoughtSignature": "sig_123",
                        }
                    ]
                }
            }
        ]
    }
    result = Translation.gemini_to_domain_stream_chunk(chunk)
    assert hasattr(result, "choices")
    tool_calls = result.choices[0].delta.tool_calls
    assert isinstance(tool_calls, list) and tool_calls
    assert tool_calls[0].get("extra_content") == {
        "google": {"thought_signature": "sig_123"}
    }


def test_openai_response_coerces_nested_reasoning_to_reasoning_content() -> None:
    """
    **Feature: cross-api-translation-refactoring, Property 6: Edge Case Handling Preservation**
    **Validates: Requirements 10.3**
    """
    response = {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 123,
        "model": "gpt-test",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": None,
                    "reasoning": {"text": "one", "thinking": ["two"]},
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }

    domain_response = Translation.openai_to_domain_response(response)
    message = domain_response.choices[0].message
    assert message.content is None
    assert message.reasoning_content is not None
    assert set(message.reasoning_content.splitlines()) == {"one", "two"}


def test_from_domain_to_gemini_request_ignores_invalid_image_urls() -> None:
    """
    **Feature: cross-api-translation-refactoring, Property 6: Edge Case Handling Preservation**
    **Validates: Requirements 10.2**
    """
    request = CanonicalChatRequest(
        model="gemini-2.5-pro",
        messages=[
            ChatMessage(
                role="user",
                content=[
                    MessageContentPartText(text="Describe"),
                    MessageContentPartImage(
                        image_url=ImageURL(url="ftp://bad/x.png", detail=None)
                    ),
                ],
            )
        ],
    )

    payload = Translation.from_domain_to_gemini_request(request)
    contents = payload["contents"]
    assert contents
    parts = contents[0]["parts"]
    assert parts == [{"text": "Describe"}]


def test_process_gemini_image_part_handles_data_uri_without_comma() -> None:
    """
    **Feature: cross-api-translation-refactoring, Property 6: Edge Case Handling Preservation**
    **Validates: Requirements 10.2**
    """
    part = MessageContentPartImage(
        image_url=ImageURL(url="data:image/png;base64", detail=None)
    )
    converted = media_utils._process_gemini_image_part(part)
    assert converted == {
        "inline_data": {"mime_type": "image/png", "data": ""},
    }


def test_gemini_stream_chunk_preserves_reasoning_parts() -> None:
    """
    **Feature: cross-api-translation-refactoring, Property 6: Edge Case Handling Preservation**
    **Validates: Requirements 10.3**
    """
    chunk = {
        "candidates": [{"content": {"parts": [{"type": "thinking", "text": "plan"}]}}]
    }
    result = Translation.gemini_to_domain_stream_chunk(chunk)
    assert hasattr(result, "choices")
    delta_dict = result.choices[0].delta.model_dump()
    assert delta_dict["reasoning_content"] == "plan"


def test_anthropic_stream_chunk_preserves_reasoning_delta() -> None:
    """
    **Feature: cross-api-translation-refactoring, Property 6: Edge Case Handling Preservation**
    **Validates: Requirements 10.3**
    """
    chunk = {
        "type": "content_block_delta",
        "delta": {"type": "thinking_delta", "text": "careful plan"},
    }
    mapped = Translation.anthropic_to_domain_stream_chunk(chunk)
    assert mapped["choices"][0]["delta"]["reasoning_content"] == "careful plan"


def test_from_domain_to_anthropic_request_serializes_multimodal_images() -> None:
    """
    **Feature: cross-api-translation-refactoring, Property 6: Edge Case Handling Preservation**
    **Validates: Requirements 10.2**
    """
    request = CanonicalChatRequest(
        model="claude-3-opus-20240229",
        messages=[
            ChatMessage(
                role="user",
                content=[
                    MessageContentPartText(text="Describe"),
                    MessageContentPartImage(
                        image_url=ImageURL(
                            url="data:image/png;base64,aGVsbG8=",
                            detail=None,
                        )
                    ),
                    MessageContentPartImage(
                        image_url=ImageURL(
                            url="https://example.com/cat.png",
                            detail=None,
                        )
                    ),
                ],
            )
        ],
    )

    payload = Translation.from_domain_to_anthropic_request(request)
    content = payload["messages"][0]["content"]
    assert content[0] == {"type": "text", "text": "Describe"}
    assert content[1]["type"] == "image"
    assert content[1]["source"]["type"] == "base64"
    assert content[1]["source"]["media_type"] == "image/png"
    assert content[1]["source"]["data"] == "aGVsbG8="
    assert content[2]["type"] == "image"
    assert content[2]["source"] == {"type": "url", "url": "https://example.com/cat.png"}
