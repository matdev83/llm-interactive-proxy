from __future__ import annotations

import json

import pytest
from src.core.domain.translation import Translation


@pytest.mark.parametrize(
    "event_type",
    [
        # Tool call payload is emitted on output_item.done; arguments.done is a no-op delta.
        "response.output_item.done",
    ],
)
def test_stream_adapter_cleanup_removes_rendered_tool_text_from_content(
    event_type: str,
) -> None:
    """
    Verify that the stream adapter cleanup removes rendered tool text from the
    content field of the delta, while preserving it in _tool_call_text.
    """
    from unittest.mock import patch

    # Mock the render_tool_call to return expected XML content
    with patch(
        "src.core.domain.translators.responses.streaming.render_tool_call"
    ) as mock_render:
        mock_render.return_value = (
            "<execute_command><command>ls -l</command></execute_command>"
        )

        # Arrange
        item = (
            {
                "type": "function_call",
                "call_id": "call_123",
                "name": "shell",
                "arguments": '{"command": "ls -l"}',
            }
            if event_type == "response.output_item.done"
            else {}
        )

        chunk = {
            "type": event_type,
            "item_id": "call_123",
            "name": "shell",
            "arguments": '{"command": "ls -l"}',
            "output_index": 0,
            "item": item,
        }

        # Act
        translated_chunk = Translation.responses_to_domain_stream_chunk(chunk)

        # Assert
        assert "choices" in translated_chunk
        assert len(translated_chunk["choices"]) == 1
        delta = translated_chunk["choices"][0].get("delta", {})

        # The 'content' field should NOT contain the rendered XML.
        assert "content" not in delta or delta["content"] is None

        # The '_tool_call_text' field SHOULD (for now) contain the rendered XML.
        assert "_tool_call_text" in delta
        assert isinstance(delta["_tool_call_text"], str)
        assert "<execute_command>" in delta["_tool_call_text"]
        assert "<command>ls -l</command>" in delta["_tool_call_text"]

        # The 'tool_calls' structure must be preserved.
        assert "tool_calls" in delta
        assert len(delta["tool_calls"]) == 1
        tool_call = delta["tool_calls"][0]
        assert tool_call["id"] == "call_123"
        assert tool_call["function"]["name"] == "bash"
        assert json.loads(tool_call["function"]["arguments"]) == {
            "command": "ls -l",
            "description": "",
        }
