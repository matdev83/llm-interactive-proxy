"""Unit tests for Responses streaming legacy helpers."""

from __future__ import annotations

from src.core.app.controllers.responses_stream_coercion import (
    coerce_stream_chunk_payload,
)


def test_coerce_stream_chunk_payload_decodes_json_bytes() -> None:
    raw = b'{"choices": [{"delta": {"content": "Hello"}}]}'
    out = coerce_stream_chunk_payload(raw, default_response_id="resp_default")
    assert out is not None
    assert out["choices"][0]["delta"]["content"] == "Hello"


def test_coerce_stream_chunk_payload_decodes_json_str() -> None:
    raw = '{"choices": [{"delta": {"content": "x"}}]}'
    out = coerce_stream_chunk_payload(raw, default_response_id="resp_default")
    assert out is not None
    assert out["choices"][0]["delta"]["content"] == "x"


def test_coerce_stream_chunk_payload_invalid_bytes_returns_none() -> None:
    assert coerce_stream_chunk_payload(b"not json", default_response_id="r") is None
