"""Test that extra_content is properly sanitized from tool_calls before sending to clients.

This file tests the fix for the agent loop breaking issue where Factory Droid CLI
could not parse tool calls from Gemini responses because they contained extra_content
with a thought_signature field.
"""

import json

from src.core.ports.streaming_contracts import StreamingContent


class TestExtraContentSanitization:
    """Tests for extra_content sanitization in tool calls."""

    def test_extra_content_removed_from_embedded_tool_calls(self) -> None:
        """Test that extra_content is removed from tool_calls already in content delta."""
        # Simulate a Gemini response with extra_content in tool_calls
        content_with_extra = {
            "id": "chatcmpl-test",
            "object": "chat.completion.chunk",
            "created": 1234567890,
            "model": "gemini-3-pro-high",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "tool_calls",
                    "delta": {
                        "role": "assistant",
                        "tool_calls": [
                            {
                                "id": "call_test123",
                                "type": "function",
                                "function": {
                                    "name": "Read",
                                    "arguments": '{"file_path": "test.py"}',
                                },
                                "extra_content": {
                                    "google": {
                                        "thought_signature": "EtIQ...massive_base64_string..."
                                    }
                                },
                            }
                        ],
                    },
                }
            ],
        }

        chunk = StreamingContent(
            content=content_with_extra,
            metadata={"finish_reason": "tool_calls"},
            is_done=True,
        )

        # Convert to bytes (SSE format)
        result = chunk.to_bytes()
        result_str = result.decode("utf-8")

        # Parse the SSE data
        lines = result_str.strip().split("\n")
        data_line = [
            line for line in lines if line.startswith("data: ") and "[DONE]" not in line
        ][0]
        json_data = json.loads(data_line[6:])  # Remove "data: " prefix

        # Verify extra_content is NOT in the output
        tool_calls = json_data["choices"][0]["delta"]["tool_calls"]
        assert len(tool_calls) == 1
        assert "extra_content" not in tool_calls[0]
        assert tool_calls[0]["id"] == "call_test123"
        assert tool_calls[0]["type"] == "function"
        assert tool_calls[0]["function"]["name"] == "Read"

    def test_extra_content_removed_from_metadata_tool_calls(self) -> None:
        """Test that extra_content is removed when tool_calls come from metadata."""
        chunk = StreamingContent(
            content="",
            metadata={
                "finish_reason": "tool_calls",
                "tool_calls": [
                    {
                        "id": "call_abc123",
                        "type": "function",
                        "function": {
                            "name": "Execute",
                            "arguments": '{"command": "ls"}',
                        },
                        "extra_content": {
                            "google": {"thought_signature": "base64data"}
                        },
                        "_internal_marker": True,  # Should also be removed
                    }
                ],
            },
            is_done=False,
        )

        result = chunk.to_bytes()
        result_str = result.decode("utf-8")

        # Parse the SSE data
        data_line = [
            line for line in result_str.strip().split("\n") if line.startswith("data: ")
        ][0]
        json_data = json.loads(data_line[6:])

        tool_calls = json_data["choices"][0]["delta"]["tool_calls"]
        assert len(tool_calls) == 1
        assert "extra_content" not in tool_calls[0]
        assert "_internal_marker" not in tool_calls[0]
        assert tool_calls[0]["id"] == "call_abc123"

    def test_standard_tool_call_fields_preserved(self) -> None:
        """Test that standard OpenAI tool call fields (id, type, function) are preserved."""
        content_with_tool_calls = {
            "id": "chatcmpl-test",
            "object": "chat.completion.chunk",
            "created": 1234567890,
            "model": "gpt-4",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "tool_calls",
                    "delta": {
                        "tool_calls": [
                            {
                                "id": "call_standard",
                                "type": "function",
                                "function": {
                                    "name": "get_weather",
                                    "arguments": '{"location": "NYC"}',
                                },
                                "index": 0,  # Non-standard but should be preserved
                            }
                        ],
                    },
                }
            ],
        }

        chunk = StreamingContent(
            content=content_with_tool_calls,
            metadata={"finish_reason": "tool_calls"},
            is_done=True,
        )

        result = chunk.to_bytes()
        result_str = result.decode("utf-8")

        data_line = [
            line
            for line in result_str.strip().split("\n")
            if line.startswith("data: ") and "[DONE]" not in line
        ][0]
        json_data = json.loads(data_line[6:])

        tool_calls = json_data["choices"][0]["delta"]["tool_calls"]
        assert len(tool_calls) == 1
        assert tool_calls[0]["id"] == "call_standard"
        assert tool_calls[0]["type"] == "function"
        assert tool_calls[0]["function"]["name"] == "get_weather"
        # index field should be preserved (not starting with _ and not extra_content)
        assert tool_calls[0]["index"] == 0

    def test_multiple_tool_calls_all_sanitized(self) -> None:
        """Test that multiple tool calls are all sanitized."""
        content_with_multiple_calls = {
            "id": "chatcmpl-multi",
            "object": "chat.completion.chunk",
            "created": 1234567890,
            "model": "gemini-3-pro",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "tool_calls",
                    "delta": {
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {"name": "tool_a", "arguments": "{}"},
                                "extra_content": {"data": "should_be_removed"},
                            },
                            {
                                "id": "call_2",
                                "type": "function",
                                "function": {"name": "tool_b", "arguments": "{}"},
                                "extra_content": {"data": "also_removed"},
                                "_processed": True,
                            },
                        ],
                    },
                }
            ],
        }

        chunk = StreamingContent(
            content=content_with_multiple_calls,
            metadata={},
            is_done=True,
        )

        result = chunk.to_bytes()
        result_str = result.decode("utf-8")

        data_line = [
            line
            for line in result_str.strip().split("\n")
            if line.startswith("data: ") and "[DONE]" not in line
        ][0]
        json_data = json.loads(data_line[6:])

        tool_calls = json_data["choices"][0]["delta"]["tool_calls"]
        assert len(tool_calls) == 2

        for tc in tool_calls:
            assert "extra_content" not in tc
            assert "_processed" not in tc
