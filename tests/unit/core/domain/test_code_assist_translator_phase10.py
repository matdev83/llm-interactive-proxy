from __future__ import annotations

from src.core.domain.translation import Translation
from src.core.domain.translators.code_assist_translator import CodeAssistTranslator


def test_code_assist_translator_format_names() -> None:
    translator = CodeAssistTranslator()
    assert "code_assist" in set(translator.format_names)


def test_code_assist_translator_to_domain_request_matches_translation_facade() -> None:
    payload = {
        "project": "my-project",
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": "Hello"}],
        "temperature": 0.2,
        "stream": False,
    }

    translator = CodeAssistTranslator()
    expected = Translation.code_assist_to_domain_request(payload).model_dump()
    actual = translator.to_domain_request(payload).model_dump()
    assert actual == expected


def test_code_assist_translator_to_domain_response_matches_translation_facade() -> None:
    payload = {
        "model": "code-assist-model",
        "response": {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"text": "Hello"},
                            {
                                "functionCall": {
                                    "id": "call_1",
                                    "name": "lookup",
                                    "args": {"q": "x"},
                                }
                            },
                        ]
                    },
                    "finishReason": "STOP",
                }
            ]
        },
    }

    translator = CodeAssistTranslator()
    expected = Translation.code_assist_to_domain_response(payload).model_dump()
    actual = translator.to_domain_response(payload).model_dump()
    expected.pop("id", None)
    expected.pop("created", None)
    actual.pop("id", None)
    actual.pop("created", None)
    assert actual == expected


def test_code_assist_translator_to_domain_stream_chunk_matches_translation_facade() -> (
    None
):
    payload = {
        "response": {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"text": "Hi"},
                            {
                                "functionCall": {
                                    "id": "call_2",
                                    "name": "lookup",
                                    "args": {"q": "y"},
                                }
                            },
                        ]
                    },
                    "finishReason": "STOP",
                }
            ]
        }
    }

    translator = CodeAssistTranslator()
    expected = Translation.code_assist_to_domain_stream_chunk(payload)
    actual = translator.to_domain_stream_chunk(payload)
    expected.pop("id", None)
    expected.pop("created", None)
    actual.pop("id", None)
    actual.pop("created", None)
    assert actual == expected
