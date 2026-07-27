"""Tests for empty tool-name sanitization helpers."""

from __future__ import annotations

from src.core.domain.translation_utils.tool_utils import (
    sanitize_chat_messages_for_empty_tool_names,
    sanitize_responses_input_for_empty_names,
)


class TestSanitizeChatMessagesForEmptyToolNames:
    def test_removes_empty_named_tool_call_and_orphan_tool_result(self) -> None:
        messages = [
            {"role": "user", "content": "go"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_good",
                        "type": "function",
                        "function": {
                            "name": "web_search",
                            "arguments": '{"q":"x"}',
                        },
                    },
                    {
                        "id": "",
                        "type": "function",
                        "function": {"name": "", "arguments": '"}"'},
                    },
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_good",
                "content": "ok",
            },
            {
                "role": "tool",
                "tool_call_id": "",
                "content": "Tool  not found",
            },
        ]

        sanitized, removed = sanitize_chat_messages_for_empty_tool_names(messages)

        assert removed == 2
        assert len(sanitized) == 3
        assert sanitized[1]["tool_calls"] == [
            {
                "id": "call_good",
                "type": "function",
                "function": {"name": "web_search", "arguments": '{"q":"x"}'},
            }
        ]
        assert sanitized[2]["tool_call_id"] == "call_good"

    def test_strips_empty_optional_message_name(self) -> None:
        messages = [{"role": "user", "name": "", "content": "hi"}]
        sanitized, removed = sanitize_chat_messages_for_empty_tool_names(messages)
        assert removed == 1
        assert "name" not in sanitized[0]
        assert sanitized[0]["content"] == "hi"


class TestSanitizeResponsesInputForEmptyNames:
    def test_drops_empty_named_function_call_and_empty_call_id_output(self) -> None:
        items = [
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "hi"}],
            },
            {
                "type": "function_call",
                "call_id": "call_good",
                "name": "bash",
                "arguments": '{"command":"ls"}',
            },
            {
                "type": "function_call",
                "call_id": "call_bad",
                "name": "",
                "arguments": '"}"',
            },
            {
                "type": "function_call_output",
                "call_id": "call_good",
                "output": '{"output":"ok"}',
            },
            {
                "type": "function_call_output",
                "call_id": "",
                "output": '{"output":"Tool  not found"}',
            },
            {"type": "message", "role": "assistant", "name": "", "content": []},
        ]

        sanitized, removed = sanitize_responses_input_for_empty_names(items)

        assert removed == 3
        assert [item.get("type") for item in sanitized] == [
            "message",
            "function_call",
            "function_call_output",
            "message",
        ]
        assert sanitized[1]["name"] == "bash"
        assert "name" not in sanitized[3]
