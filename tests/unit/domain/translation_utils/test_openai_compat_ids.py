"""Tests for OpenAI-compatible id coercion (strict clients / NIM quirks)."""

from __future__ import annotations

from src.core.domain.translation_utils.openai_compat_ids import (
    coerce_openai_completion_id,
    normalize_tool_call_dict_id_inplace,
    sanitize_openai_chunk_tool_call_ids_inplace,
    sanitize_openai_compatible_sse_payload_inplace,
)
from src.core.domain.translators.openai.response import openai_to_domain_response
from src.core.domain.translators.openai.streaming import openai_to_domain_stream_chunk


def test_coerce_openai_completion_id_preserves_non_empty_str() -> None:
    assert coerce_openai_completion_id("  abc  ") == "abc"


def test_coerce_openai_completion_id_numeric() -> None:
    assert coerce_openai_completion_id(42) == "42"
    assert coerce_openai_completion_id(3.0) == "3"


def test_coerce_openai_completion_id_fallback_uses_created() -> None:
    assert coerce_openai_completion_id(None, created_fallback=1700000000) == (
        "chatcmpl-1700000000"
    )


def test_normalize_tool_call_dict_id_inplace() -> None:
    d: dict = {"id": None, "index": 0}
    normalize_tool_call_dict_id_inplace(d)
    assert "id" not in d

    d2 = {"id": 7, "index": 1}
    normalize_tool_call_dict_id_inplace(d2)
    assert d2["id"] == "7"


def test_sanitize_openai_chunk_tool_call_ids_inplace() -> None:
    chunk = {
        "choices": [
            {
                "delta": {
                    "tool_calls": [{"id": 9, "index": 0, "type": "function"}],
                }
            }
        ]
    }
    sanitize_openai_chunk_tool_call_ids_inplace(chunk)
    assert chunk["choices"][0]["delta"]["tool_calls"][0]["id"] == "9"


def test_sanitize_openai_compatible_sse_payload_inplace_coerces_ids() -> None:
    payload = {
        "object": "chat.completion.chunk",
        "id": 4242,
        "created": 1700000002,
        "model": "m",
        "choices": [
            {
                "index": 0,
                "delta": {"tool_calls": [{"id": 1, "index": 0, "type": "function"}]},
            }
        ],
    }
    sanitize_openai_compatible_sse_payload_inplace(payload)
    assert payload["id"] == "4242"
    assert payload["choices"][0]["delta"]["tool_calls"][0]["id"] == "1"


def test_sanitize_openai_compatible_sse_payload_inplace_error_dict_numeric_id() -> None:
    err = {"id": 99, "error": {"message": "x", "type": "api_error"}}
    sanitize_openai_compatible_sse_payload_inplace(err)
    assert err["id"] == "99"


def test_openai_to_domain_stream_chunk_accepts_null_top_level_id() -> None:
    import json

    payload = {
        "id": None,
        "object": "chat.completion.chunk",
        "created": 1700000001,
        "model": "x",
        "choices": [{"index": 0, "delta": {"content": "hi"}}],
    }
    msg = f"data: {json.dumps(payload)}\n\n"
    out = openai_to_domain_stream_chunk(msg)
    assert hasattr(out, "id")
    assert isinstance(out.id, str)
    assert out.id == "chatcmpl-1700000001"


def test_openai_to_domain_response_coerces_numeric_id() -> None:
    body = {
        "id": 1001,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "ok"},
                "finish_reason": "stop",
            }
        ],
        "model": "m",
        "created": 1,
    }
    domain = openai_to_domain_response(body)
    assert domain.id == "1001"
