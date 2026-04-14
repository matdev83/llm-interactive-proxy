"""Repro + regression: Codex / OpenAI stream terminates with ``response.done`` (not only ``response.completed``)."""

from __future__ import annotations

import pytest
from src.core.domain.translators.responses.streaming import (
    reset_active_responses_stream_context,
    responses_to_domain_stream_chunk,
)


@pytest.fixture(autouse=True)
def _reset_responses_stream_context() -> None:
    reset_active_responses_stream_context()
    yield
    reset_active_responses_stream_context()


def test_repro_codex_style_response_done_carries_usage() -> None:
    """Codex SSE often ends with type=response.done + nested usage (parity with response.completed)."""
    raw = {
        "type": "response.done",
        "response": {
            "id": "resp_codex_done_1",
            "object": "response",
            "model": "gpt-5.4",
            "status": "completed",
            "usage": {
                "input_tokens": 42,
                "output_tokens": 7,
                "total_tokens": 49,
            },
        },
    }
    out = responses_to_domain_stream_chunk(raw)
    assert isinstance(out, dict)
    assert out.get("usage"), "expected usage on terminal response.done chunk"
    usage = out["usage"]
    assert usage.get("input_tokens") == 42 or usage.get("prompt_tokens") == 42
    assert out["choices"][0].get("finish_reason") == "stop"


def test_response_completed_usage_unchanged() -> None:
    """Control: response.completed still maps usage."""
    raw = {
        "type": "response.completed",
        "response": {
            "id": "resp_completed_1",
            "usage": {"input_tokens": 1, "output_tokens": 2, "total_tokens": 3},
        },
    }
    out = responses_to_domain_stream_chunk(raw)
    assert out.get("usage")
    assert out["choices"][0].get("finish_reason") == "stop"
