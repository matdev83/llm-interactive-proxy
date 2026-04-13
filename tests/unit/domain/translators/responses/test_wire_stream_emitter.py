"""Tests for ResponsesWireStreamEmitter."""

from __future__ import annotations

from src.core.domain.translators.responses.wire_stream_emitter import (
    ResponsesWireStreamEmitter,
)


def test_emitter_single_token_stream() -> None:
    em = ResponsesWireStreamEmitter(model="gpt-test", created_at=1700000000.0)
    out = em.feed(
        {
            "id": "resp_upstream",
            "model": "gpt-test",
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": "H", "role": "assistant"},
                    "finish_reason": None,
                }
            ],
        }
    )
    types = [e["type"] for e in out]
    assert types[:4] == [
        "response.created",
        "response.in_progress",
        "response.output_item.added",
        "response.content_part.added",
    ]
    assert types[4] == "response.output_text.delta"
    assert out[4]["delta"] == "H"
    assert not em.is_finished()

    out2 = em.feed(
        {
            "id": "resp_upstream",
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": "i"},
                    "finish_reason": "stop",
                }
            ],
        }
    )
    assert out2[0]["type"] == "response.output_text.delta"
    assert out2[0]["delta"] == "i"
    assert out2[-1]["type"] == "response.completed"
    assert em.is_finished()

    assert em.finalize() == []


def test_finalize_without_terminal_chunk() -> None:
    em = ResponsesWireStreamEmitter(model="m", created_at=1.0)
    em.feed(
        {
            "id": "r1",
            "choices": [{"index": 0, "delta": {"content": "x"}}],
        }
    )
    assert not em.is_finished()
    fin = em.finalize()
    assert fin[-1]["type"] == "response.completed"
    assert em.is_finished()


def test_emitter_tool_calls_use_wire_function_events() -> None:
    em = ResponsesWireStreamEmitter(model="gpt-test", created_at=1700000000.0)
    out = em.feed(
        {
            "id": "resp_tool",
            "model": "gpt-test",
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "type": "function",
                                "function": {
                                    "name": "fetch_data",
                                    "arguments": '{"query":"status"}',
                                },
                            }
                        ]
                    },
                    "finish_reason": None,
                }
            ],
        }
    )
    assert [evt["type"] for evt in out] == [
        "response.created",
        "response.in_progress",
        "response.output_item.added",
        "response.function_call_arguments.delta",
    ]
    assert out[-1]["delta"] == '{"query":"status"}'

    done = em.feed(
        {
            "id": "resp_tool",
            "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
        }
    )
    done_types = [evt["type"] for evt in done]
    assert done_types == [
        "response.function_call_arguments.done",
        "response.output_item.done",
        "response.completed",
    ]
    assert done[0]["arguments"] == '{"query":"status"}'
    assert done[1]["item"]["name"] == "fetch_data"
    assert done[1]["item"]["arguments"] == '{"query":"status"}'
    assert em.is_finished()


def test_emitter_mixes_text_and_tool_calls_without_legacy_shape() -> None:
    em = ResponsesWireStreamEmitter(model="gpt-test", created_at=1700000000.0)
    em.feed(
        {
            "id": "resp_mix",
            "choices": [
                {"index": 0, "delta": {"content": "Working"}, "finish_reason": None}
            ],
        }
    )
    out = em.feed(
        {
            "id": "resp_mix",
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_mix",
                                "function": {
                                    "name": "run",
                                    "arguments": '{"cmd":"echo hi"}',
                                },
                            }
                        ]
                    },
                    "finish_reason": "tool_calls",
                }
            ],
        }
    )
    assert all("object" not in evt for evt in out)
    assert "response.function_call_arguments.delta" in [evt["type"] for evt in out]
    assert out[-1]["type"] == "response.completed"
