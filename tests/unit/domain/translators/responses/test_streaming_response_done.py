"""Repro + regression: Codex / OpenAI stream terminates with ``response.done`` (not only ``response.completed``)."""

from __future__ import annotations

from collections.abc import Generator

import pytest
from src.core.domain.translators.responses.streaming import (
    reset_active_responses_stream_context,
    responses_to_domain_stream_chunk,
)


@pytest.fixture(autouse=True)
def _reset_responses_stream_context() -> Generator[None, None, None]:
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


def test_partial_tool_call_events_are_buffered_until_output_item_done() -> None:
    """Responses partial tool-call chunks should not surface before the final done event."""
    response_id = "resp_tool_delta_buffer_1"
    call_id = "call_tool_delta_buffer_1"

    responses_to_domain_stream_chunk(
        {
            "type": "response.created",
            "response": {"id": response_id, "model": "gpt-5.4"},
        }
    )
    responses_to_domain_stream_chunk(
        {
            "type": "response.output_item.added",
            "output_index": 1,
            "item": {
                "id": call_id,
                "call_id": call_id,
                "type": "function_call",
                "name": "todowrite",
            },
        }
    )

    partial = responses_to_domain_stream_chunk(
        {
            "type": "response.function_call_arguments.delta",
            "item_id": call_id,
            "output_index": 1,
            "delta": '{"todos":[{"content":"Inspect captures","status":"in_progress"}]}',
        }
    )

    assert partial["choices"][0]["delta"] == {}

    done = responses_to_domain_stream_chunk(
        {
            "type": "response.output_item.done",
            "output_index": 1,
            "item": {
                "id": call_id,
                "call_id": call_id,
                "type": "function_call",
                "name": "todowrite",
                "arguments": "{}",
            },
        }
    )

    tool_calls = done["choices"][0]["delta"]["tool_calls"]
    assert tool_calls[0]["function"]["name"] == "todowrite"
    assert (
        tool_calls[0]["function"]["arguments"]
        == '{"todos":[{"content":"Inspect captures","status":"in_progress"}]}'
    )


def test_apply_patch_placeholder_is_buffered_until_output_item_done() -> None:
    """OpenCode must not see an empty apply_patch tool call before full arguments exist."""
    response_id = "resp_apply_patch_buffer_1"
    call_id = "call_apply_patch_buffer_1"

    responses_to_domain_stream_chunk(
        {
            "type": "response.created",
            "response": {"id": response_id, "model": "gpt-5.4"},
        }
    )

    added = responses_to_domain_stream_chunk(
        {
            "type": "response.output_item.added",
            "output_index": 1,
            "item": {
                "id": call_id,
                "call_id": call_id,
                "type": "function_call",
                "name": "apply_patch",
            },
        }
    )

    assert added["choices"][0]["delta"] == {}

    partial = responses_to_domain_stream_chunk(
        {
            "type": "response.function_call_arguments.delta",
            "item_id": call_id,
            "output_index": 1,
            "delta": "*** Begin Patch\n*** Add File: notes.txt\n+hello\n*** End Patch\n",
        }
    )

    assert partial["choices"][0]["delta"] == {}

    done = responses_to_domain_stream_chunk(
        {
            "type": "response.output_item.done",
            "output_index": 1,
            "item": {
                "id": call_id,
                "call_id": call_id,
                "type": "function_call",
                "name": "apply_patch",
                "arguments": "{}",
            },
        }
    )

    tool_calls = done["choices"][0]["delta"]["tool_calls"]
    assert tool_calls[0]["function"]["name"] == "apply_patch"
    assert (
        tool_calls[0]["function"]["arguments"]
        == "*** Begin Patch\n*** Add File: notes.txt\n+hello\n*** End Patch\n"
    )
