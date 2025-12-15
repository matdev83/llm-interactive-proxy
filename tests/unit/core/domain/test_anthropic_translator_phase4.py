from __future__ import annotations

import json

from src.core.domain.translation import Translation
from src.core.domain.translators.anthropic_translator import AnthropicTranslator
from src.core.services.translation_service import TranslationService


def test_anthropic_translator_format_names() -> None:
    translator = AnthropicTranslator()
    assert "anthropic" in set(translator.format_names)


def test_anthropic_translator_to_domain_request_matches_translation_facade() -> None:
    payload = {
        "model": "claude-3-opus-20240229",
        "system": "You are helpful.",
        "messages": [{"role": "user", "content": "Hello"}],
        "max_tokens": 123,
        "stream": False,
        "stop_sequences": ["\n\n"],
        "temperature": 0.2,
        "top_p": 0.9,
        "top_k": 20,
    }

    translator = AnthropicTranslator()
    expected = Translation.anthropic_to_domain_request(payload).model_dump()
    actual = translator.to_domain_request(payload).model_dump()
    assert actual == expected


def test_anthropic_translator_to_domain_response_matches_translation_facade() -> None:
    payload = {
        "id": "msg_01A0QnE4S7rD8nSW2C9d9gM1",
        "type": "message",
        "role": "assistant",
        "model": "claude-3-opus-20240229",
        "content": [
            {"type": "thinking", "thinking": "Step through the plan."},
            {"type": "text", "text": "Solution summary."},
        ],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": 25},
    }

    translator = AnthropicTranslator()
    expected = Translation.anthropic_to_domain_response(payload).model_dump()
    actual = translator.to_domain_response(payload).model_dump()
    assert actual == expected


def test_anthropic_translator_to_domain_stream_chunk_matches_translation_facade() -> (
    None
):
    sse_chunk = (
        "event: content_block_delta\n"
        'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Hello"}}\n\n'
    )

    translator = AnthropicTranslator()
    expected = Translation.anthropic_to_domain_stream_chunk(sse_chunk)
    actual = translator.to_domain_stream_chunk(sse_chunk)
    for payload in (expected, actual):
        payload.pop("id", None)
        payload.pop("created", None)
    assert actual == expected


def test_anthropic_translator_from_domain_request_matches_translation_facade() -> None:
    canonical = Translation.anthropic_to_domain_request(
        {
            "model": "claude-3-opus-20240229",
            "system": "You are helpful.",
            "messages": [{"role": "user", "content": "Hello"}],
            "max_tokens": 123,
            "stream": False,
            "stop_sequences": ["\n\n"],
        }
    )

    translator = AnthropicTranslator()
    expected = Translation.from_domain_to_anthropic_request(canonical)
    actual = translator.from_domain_request(canonical)
    assert actual == expected


def test_anthropic_translator_from_domain_response_matches_translation_service() -> (
    None
):
    canonical = Translation.anthropic_to_domain_response(
        {
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": "claude-3-opus-20240229",
            "content": [{"type": "text", "text": "Hello"}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 1, "output_tokens": 2},
        }
    )

    translator = AnthropicTranslator()
    service = TranslationService()
    expected = service.from_domain_to_anthropic_response(canonical)
    actual = translator.from_domain_response(canonical)
    assert actual == expected


def test_anthropic_translator_from_domain_stream_chunk_matches_translation_service() -> (
    None
):
    canonical_chunk = Translation.openai_to_domain_stream_chunk(
        {
            "id": "chatcmpl-stream",
            "object": "chat.completion.chunk",
            "created": 1700000000,
            "model": "gpt-4",
            "choices": [
                {"index": 0, "delta": {"content": "hi"}, "finish_reason": None}
            ],
        }
    )

    translator = AnthropicTranslator()
    service = TranslationService()
    expected = service.from_domain_to_anthropic_stream_chunk(canonical_chunk)
    actual = translator.from_domain_stream_chunk(canonical_chunk)
    assert actual == expected


def test_anthropic_translator_from_domain_to_anthropic_response_preserves_tool_args_json() -> (
    None
):
    canonical = Translation.openai_to_domain_response(
        {
            "id": "chatcmpl-123",
            "object": "chat.completion",
            "created": 1677652288,
            "model": "gpt-4",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "Hi",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {
                                    "name": "lookup",
                                    "arguments": '{"q":"x"}',
                                },
                            }
                        ],
                    },
                    "finish_reason": "stop",
                }
            ],
        }
    )

    translator = AnthropicTranslator()
    response = translator.from_domain_response(canonical)

    tool_use = next(
        block
        for block in response.get("content", [])
        if isinstance(block, dict) and block.get("type") == "tool_use"
    )
    assert tool_use["name"] == "lookup"
    assert json.dumps(tool_use["input"], sort_keys=True) == json.dumps(
        {"q": "x"}, sort_keys=True
    )
