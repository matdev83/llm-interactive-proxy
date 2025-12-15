from __future__ import annotations

from typing import Any

from src.core.domain.translation import Translation
from src.core.domain.translators.raw_text_translator import RawTextTranslator


def test_raw_text_translator_format_names() -> None:
    translator = RawTextTranslator()
    assert "raw_text" in set(translator.format_names)


def test_raw_text_translator_to_domain_request_string_matches_translation_facade() -> (
    None
):
    translator = RawTextTranslator()
    expected = Translation.raw_text_to_domain_request("Hello").model_dump()
    actual = translator.to_domain_request("Hello").model_dump()
    assert actual == expected


def test_raw_text_translator_to_domain_request_openai_dict_matches_translation_facade() -> (
    None
):
    payload = {"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "Hi"}]}

    translator = RawTextTranslator()
    expected = Translation.raw_text_to_domain_request(payload).model_dump()
    actual = translator.to_domain_request(payload).model_dump()
    assert actual == expected


def test_raw_text_translator_to_domain_response_string_matches_translation_facade() -> (
    None
):
    translator = RawTextTranslator()

    expected = Translation.raw_text_to_domain_response("Hello").model_dump()
    actual = translator.to_domain_response("Hello").model_dump()
    expected.pop("id", None)
    expected.pop("created", None)
    actual.pop("id", None)
    actual.pop("created", None)
    assert actual == expected


def test_raw_text_translator_to_domain_stream_chunk_string_matches_translation_facade() -> (
    None
):
    translator = RawTextTranslator()

    expected: Any = Translation.raw_text_to_domain_stream_chunk("hi")
    actual: Any = translator.to_domain_stream_chunk("hi")
    expected.pop("id", None)
    expected.pop("created", None)
    actual.pop("id", None)
    actual.pop("created", None)
    assert actual == expected


def test_raw_text_translator_to_domain_stream_chunk_end_of_stream_matches_translation_facade() -> (
    None
):
    translator = RawTextTranslator()

    expected: Any = Translation.raw_text_to_domain_stream_chunk(None)
    actual: Any = translator.to_domain_stream_chunk(None)
    expected.pop("id", None)
    expected.pop("created", None)
    actual.pop("id", None)
    actual.pop("created", None)
    assert actual == expected


def test_raw_text_translator_to_domain_stream_chunk_wrapped_text_matches_translation_facade() -> (
    None
):
    translator = RawTextTranslator()

    expected: Any = Translation.raw_text_to_domain_stream_chunk({"text": "Hello"})
    actual: Any = translator.to_domain_stream_chunk({"text": "Hello"})
    expected.pop("id", None)
    expected.pop("created", None)
    actual.pop("id", None)
    actual.pop("created", None)
    assert actual == expected


def test_raw_text_translator_to_domain_stream_chunk_invalid_type_matches_translation_facade() -> (
    None
):
    translator = RawTextTranslator()
    expected = Translation.raw_text_to_domain_stream_chunk(123)
    actual = translator.to_domain_stream_chunk(123)
    assert actual == expected
