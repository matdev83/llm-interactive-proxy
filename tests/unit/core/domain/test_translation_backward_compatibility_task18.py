from __future__ import annotations

from typing import Any

from hypothesis import given
from hypothesis import strategies as st
from src.core.domain.chat import CanonicalChatRequest, CanonicalStreamChunk, ChatMessage
from src.core.domain.translation import Translation
from src.core.services.translation_service import TranslationService

from tests.utils.hypothesis_config import property_test_settings


@st.composite
def _openai_request_payload(draw: Any) -> dict[str, Any]:
    model = draw(st.text(min_size=1, max_size=30))
    num_messages = draw(st.integers(min_value=1, max_value=5))
    role_strategy = st.sampled_from(["user", "assistant", "system"])
    messages = [
        {
            "role": draw(role_strategy),
            "content": draw(st.text(min_size=0, max_size=200)),
        }
        for _ in range(num_messages)
    ]
    return {"model": model, "messages": messages}


@given(payload=_openai_request_payload())
@property_test_settings()
def test_property_3_translation_service_to_domain_request_matches_translation_facade_openai(
    payload: dict[str, Any],
) -> None:
    """
    **Feature: cross-api-translation-refactoring, Property 3: Backward Compatibility Equivalence**
    **Validates: Requirements 5.1, 5.3**
    """
    service = TranslationService()
    expected = Translation.openai_to_domain_request(payload).model_dump()
    actual = service.to_domain_request(payload, source_format="openai").model_dump()
    assert actual == expected


@given(
    model=st.text(min_size=1, max_size=30),
    contents=st.lists(st.text(min_size=0, max_size=200), min_size=1, max_size=5),
)
@property_test_settings()
def test_property_3_translation_service_from_domain_request_matches_translation_facade_openai(
    model: str,
    contents: list[str],
) -> None:
    """
    **Feature: cross-api-translation-refactoring, Property 3: Backward Compatibility Equivalence**
    **Validates: Requirements 5.2, 5.4**
    """
    request = CanonicalChatRequest(
        model=model,
        messages=[ChatMessage(role="user", content=content) for content in contents],
    )

    service = TranslationService()
    expected = Translation.from_domain_to_openai_request(request)
    actual = service.from_domain_request(request, target_format="openai")
    assert actual == expected


def test_translation_service_openai_stream_chunk_matches_translation_facade() -> None:
    """
    **Feature: cross-api-translation-refactoring, Property 3: Backward Compatibility Equivalence**
    **Validates: Requirements 5.1, 5.3**
    """
    payload = {
        "id": "chatcmpl_x",
        "object": "chat.completion.chunk",
        "created": 1,
        "model": "gpt-test",
        "choices": [{"index": 0, "delta": {"content": "hi"}, "finish_reason": None}],
    }

    service = TranslationService()
    service_chunk = service.to_domain_stream_chunk(payload, source_format="openai")

    facade_chunk = Translation.openai_to_domain_stream_chunk(payload)
    if isinstance(facade_chunk, dict):
        facade_chunk_obj = CanonicalStreamChunk.model_validate(facade_chunk)
    else:
        facade_chunk_obj = facade_chunk

    assert service_chunk.model_dump() == facade_chunk_obj.model_dump()


def test_translation_service_responses_alias_openai_responses_equivalent() -> None:
    """
    **Feature: cross-api-translation-refactoring, Property 3: Backward Compatibility Equivalence**
    **Validates: Requirements 5.3, 5.4**
    """
    payload = {
        "model": "gpt-4o-mini",
        "instructions": "You are helpful.",
        "input": "Hello",
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "greeting",
                "schema": {
                    "type": "object",
                    "properties": {"answer": {"type": "string"}},
                    "required": ["answer"],
                },
                "strict": True,
            },
        },
        "max_output_tokens": 64,
    }

    service = TranslationService()
    responses = service.to_domain_request(
        payload, source_format="responses"
    ).model_dump()
    aliased = service.to_domain_request(
        payload, source_format="openai-responses"
    ).model_dump()
    assert aliased == responses

    canonical = Translation.openai_to_domain_request(
        {
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "Hello"}],
            "extra_body": {"response_format": payload["response_format"]},
        }
    )
    target_responses = service.from_domain_request(canonical, target_format="responses")
    target_aliased = service.from_domain_request(
        canonical, target_format="openai-responses"
    )
    assert target_aliased == target_responses


def test_backward_compatible_exports_anthropic_converters() -> None:
    """
    **Feature: cross-api-translation-refactoring, Property 3: Backward Compatibility Equivalence**
    **Validates: Requirements 5.5**
    """
    import src.anthropic_converters as anthropic_converters

    for name in anthropic_converters.__all__:
        assert hasattr(anthropic_converters, name)
