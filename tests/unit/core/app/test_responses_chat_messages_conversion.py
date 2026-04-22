"""Tests for chat-style messages to Responses input conversion."""

from __future__ import annotations

from src.core.app.controllers.responses_controller import (
    _chat_messages_to_responses_input,
)


def test_plain_user_message() -> None:
    out = _chat_messages_to_responses_input(
        [{"role": "user", "content": "hi"}],
    )
    assert out == [
        {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": "hi"}],
        }
    ]


def test_assistant_tool_calls_and_text() -> None:
    out = _chat_messages_to_responses_input(
        [
            {
                "role": "assistant",
                "content": "ok",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "get_weather", "arguments": '{"x":1}'},
                    }
                ],
            }
        ],
    )
    assert out[0]["type"] == "message"
    assert out[0]["role"] == "assistant"
    assert out[1] == {
        "type": "function_call",
        "call_id": "call_1",
        "name": "get_weather",
        "arguments": '{"x":1}',
    }


def test_tool_result_message() -> None:
    out = _chat_messages_to_responses_input(
        [
            {
                "role": "tool",
                "tool_call_id": "call_1",
                "content": '{"temp": 20}',
            }
        ],
    )
    assert out == [
        {
            "type": "function_call_output",
            "call_id": "call_1",
            "output": '{"temp": 20}',
        }
    ]
