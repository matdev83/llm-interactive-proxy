from __future__ import annotations

from src.core.domain.chat import CanonicalStreamChunk
from src.core.domain.translation import Translation
from src.core.domain.translators.openai_translator import OpenAITranslator
from src.core.services.translation_service import TranslationService


def test_openai_translator_format_names() -> None:
    translator = OpenAITranslator()
    assert "openai" in set(translator.format_names)


def test_openai_translator_to_domain_request_matches_translation_facade() -> None:
    payload = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello"},
        ],
        "top_p": 0.9,
        "temperature": 0.2,
        "max_tokens": 123,
        "stream": False,
        "reasoning": {"effort": "high"},
    }

    translator = OpenAITranslator()
    expected = Translation.openai_to_domain_request(payload).model_dump()
    actual = translator.to_domain_request(payload).model_dump()
    assert actual == expected


def test_openai_translator_to_domain_response_matches_translation_facade() -> None:
    payload = {
        "id": "chatcmpl-123",
        "object": "chat.completion",
        "created": 1677652288,
        "model": "gpt-4",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "Hello from OpenAI.",
                    "reasoning": {
                        "content": [{"type": "output_text", "text": "Think."}]
                    },
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "lookup", "arguments": '{"q":"x"}'},
                        }
                    ],
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 8, "completion_tokens": 5, "total_tokens": 13},
    }

    translator = OpenAITranslator()
    expected = Translation.openai_to_domain_response(payload).model_dump()
    actual = translator.to_domain_response(payload).model_dump()
    assert actual == expected


def test_openai_translator_to_domain_stream_chunk_matches_translation_facade() -> None:
    chunk = {
        "id": "chatcmpl-stream",
        "object": "chat.completion.chunk",
        "created": 1700000000,
        "model": "gpt-4",
        "choices": [
            {
                "index": 0,
                "delta": {"role": "assistant", "content": "hi"},
                "finish_reason": None,
            }
        ],
    }

    translator = OpenAITranslator()
    expected = Translation.openai_to_domain_stream_chunk(chunk)
    actual = translator.to_domain_stream_chunk(chunk)

    assert isinstance(expected, CanonicalStreamChunk)
    assert isinstance(actual, CanonicalStreamChunk)
    assert actual.model_dump(exclude_none=True) == expected.model_dump(
        exclude_none=True
    )


def test_openai_stream_chunk_maps_thinking_to_reasoning_content() -> None:
    chunk = {
        "id": "chatcmpl-stream-thinking",
        "object": "chat.completion.chunk",
        "created": 1700000001,
        "model": "gpt-4",
        "choices": [
            {
                "index": 0,
                "delta": {"thinking": "Plan the response."},
                "finish_reason": None,
            }
        ],
    }

    result = Translation.openai_to_domain_stream_chunk(chunk)
    assert isinstance(result, CanonicalStreamChunk)
    assert result.choices[0].delta.reasoning_content == "Plan the response."


def test_openai_translator_from_domain_request_matches_translation_facade() -> None:
    payload = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": "Hello"}],
        "stop": ["\n\n"],
        "seed": 123,
    }
    canonical = Translation.openai_to_domain_request(payload)

    translator = OpenAITranslator()
    expected = Translation.from_domain_to_openai_request(canonical)
    actual = translator.from_domain_request(canonical)
    assert actual == expected


def test_openai_translator_from_domain_response_matches_translation_service() -> None:
    payload = {
        "id": "chatcmpl-123",
        "object": "chat.completion",
        "created": 1677652288,
        "model": "gpt-4",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "Hello from OpenAI."},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 8, "completion_tokens": 5, "total_tokens": 13},
    }
    canonical = Translation.openai_to_domain_response(payload)

    translator = OpenAITranslator()
    service = TranslationService()
    expected = service.from_domain_to_openai_response(canonical)
    actual = translator.from_domain_response(canonical)
    assert actual == expected


def test_openai_translator_from_domain_stream_chunk_matches_translation_service() -> (
    None
):
    openai_chunk = {
        "id": "chatcmpl-stream",
        "object": "chat.completion.chunk",
        "created": 1700000000,
        "model": "gpt-4",
        "choices": [{"index": 0, "delta": {"content": "hi"}, "finish_reason": None}],
    }
    canonical_chunk = Translation.openai_to_domain_stream_chunk(openai_chunk)

    translator = OpenAITranslator()
    service = TranslationService()
    expected = service.from_domain_to_openai_stream_chunk(canonical_chunk)
    actual = translator.from_domain_stream_chunk(canonical_chunk)
    assert actual == expected
