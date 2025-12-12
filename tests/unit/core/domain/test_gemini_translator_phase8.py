from __future__ import annotations

from src.core.domain.chat import CanonicalStreamChunk
from src.core.domain.translation import Translation
from src.core.services.translation_service import TranslationService


def test_gemini_translator_format_names() -> None:
    from src.core.domain.translators.gemini_translator import GeminiTranslator

    translator = GeminiTranslator()
    assert "gemini" in set(translator.format_names)


def test_gemini_translator_to_domain_request_matches_translation_facade() -> None:
    from src.core.domain.translators.gemini_translator import GeminiTranslator

    payload = {
        "model": "gemini-1.5-pro",
        "contents": [{"role": "user", "parts": [{"text": "Hello"}]}],
        "generationConfig": {
            "temperature": 0.2,
            "topP": 0.9,
            "maxOutputTokens": 64,
        },
    }

    translator = GeminiTranslator()
    expected = Translation.gemini_to_domain_request(payload).model_dump()
    actual = translator.to_domain_request(payload).model_dump()
    assert actual == expected


def test_gemini_translator_to_domain_response_matches_translation_facade() -> None:
    from src.core.domain.translators.gemini_translator import GeminiTranslator

    payload = {
        "candidates": [
            {
                "content": {"parts": [{"text": "Hello from Gemini."}], "role": "model"},
                "finishReason": "STOP",
                "index": 0,
            }
        ],
        "usageMetadata": {
            "promptTokenCount": 8,
            "candidatesTokenCount": 5,
            "totalTokenCount": 13,
        },
        "modelVersion": "gemini-1.5-pro",
    }

    translator = GeminiTranslator()
    expected = Translation.gemini_to_domain_response(payload)
    actual = translator.to_domain_response(payload)

    assert actual.model == expected.model
    assert actual.usage == expected.usage
    assert actual.choices[0].finish_reason == expected.choices[0].finish_reason
    assert actual.choices[0].message.role == expected.choices[0].message.role
    assert actual.choices[0].message.content == expected.choices[0].message.content


def test_gemini_translator_to_domain_stream_chunk_matches_translation_facade() -> None:
    from src.core.domain.translators.gemini_translator import GeminiTranslator

    chunk = {
        "candidates": [
            {
                "content": {"parts": [{"text": "hi"}], "role": "model"},
                "index": 0,
            }
        ]
    }

    translator = GeminiTranslator()
    expected = Translation.gemini_to_domain_stream_chunk(chunk)
    actual = translator.to_domain_stream_chunk(chunk)

    assert isinstance(expected, CanonicalStreamChunk)
    assert isinstance(actual, CanonicalStreamChunk)
    assert actual.model == expected.model
    assert actual.choices[0].finish_reason == expected.choices[0].finish_reason
    assert actual.choices[0].delta.model_dump(exclude_none=True) == expected.choices[
        0
    ].delta.model_dump(exclude_none=True)


def test_gemini_translator_from_domain_request_matches_translation_facade() -> None:
    from src.core.domain.translators.gemini_translator import GeminiTranslator

    canonical = Translation.gemini_to_domain_request(
        {
            "model": "gemini-1.5-pro",
            "contents": [{"role": "user", "parts": [{"text": "Hello"}]}],
        }
    )

    translator = GeminiTranslator()
    expected = Translation.from_domain_to_gemini_request(canonical)
    actual = translator.from_domain_request(canonical)
    assert actual == expected


def test_gemini_translator_from_domain_response_matches_translation_service() -> None:
    from src.core.domain.translators.gemini_translator import GeminiTranslator

    canonical = Translation.gemini_to_domain_response(
        {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"text": "Hello from Gemini."},
                        ],
                        "role": "model",
                    },
                    "finishReason": "STOP",
                    "index": 0,
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 8,
                "candidatesTokenCount": 5,
                "totalTokenCount": 13,
            },
        }
    )

    translator = GeminiTranslator()
    service = TranslationService()
    expected = service.from_domain_to_gemini_response(canonical)
    actual = translator.from_domain_response(canonical)
    assert actual == expected


def test_gemini_translator_from_domain_stream_chunk_matches_translation_service() -> (
    None
):
    from src.core.domain.translators.gemini_translator import GeminiTranslator

    openai_chunk = {
        "id": "chatcmpl-stream",
        "object": "chat.completion.chunk",
        "created": 1700000000,
        "model": "gpt-4",
        "choices": [{"index": 0, "delta": {"content": "hi"}, "finish_reason": None}],
    }
    canonical_chunk = Translation.openai_to_domain_stream_chunk(openai_chunk)

    translator = GeminiTranslator()
    service = TranslationService()
    expected = service.from_domain_to_gemini_stream_chunk(canonical_chunk)
    actual = translator.from_domain_stream_chunk(canonical_chunk)
    assert actual == expected
