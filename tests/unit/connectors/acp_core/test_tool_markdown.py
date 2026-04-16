from __future__ import annotations

from src.connectors.acp_core.tool_markdown import (
    coalesce_acp_tool_call_update_session_dict,
    coalesce_acp_tool_session_dict,
    extract_tool_correlation_key,
    extract_tool_input,
    extract_tool_name,
    extract_tool_output,
    format_acp_tool_completion_summary,
    format_acp_tool_status_line,
    is_terminal_tool_status,
    payload_utf8_byte_length,
)


def test_extract_tool_fields() -> None:
    tc = {
        "toolCallId": "x1",
        "name": "todo",
        "arguments": '{"a": 1}',
        "result": {"ok": True},
    }
    assert extract_tool_correlation_key(tc) == "x1"
    assert extract_tool_name(tc) == "todo"
    assert extract_tool_input(tc) == '{"a": 1}'
    assert extract_tool_output(tc) == {"ok": True}


def test_format_acp_tool_status_line_plain() -> None:
    assert format_acp_tool_status_line("in_progress") == "Status: in_progress\n"


def test_format_acp_tool_completion_summary_shape() -> None:
    text = format_acp_tool_completion_summary(
        "list_dir",
        input_bytes=12,
        output_bytes=34,
        started_iso="2026-01-01T00:00:00+00:00",
        ended_iso="2026-01-01T00:00:01+00:00",
        elapsed_s=1.25,
    )
    assert text.startswith("Tool: list_dir")
    assert "Input size: 12 bytes" in text
    assert "Output size: 34 bytes" in text
    assert "Started: 2026-01-01T00:00:00+00:00" in text
    assert "Ended: 2026-01-01T00:00:01+00:00" in text
    assert "(1.250 s)" in text


def test_payload_utf8_byte_length() -> None:
    assert payload_utf8_byte_length({"a": 1}) > 0
    assert payload_utf8_byte_length("hello") == 5


def test_is_terminal_tool_status() -> None:
    assert is_terminal_tool_status("completed")
    assert not is_terminal_tool_status("in_progress")


def test_coalesce_flat_acp_tool_call_shape() -> None:
    upd = {
        "sessionUpdate": "tool_call",
        "toolCallId": "call_001",
        "title": "Reading configuration file",
        "kind": "read",
        "status": "pending",
        "rawInput": {"path": "/config.json"},
    }
    merged = coalesce_acp_tool_session_dict(upd)
    assert merged["toolCallId"] == "call_001"
    assert extract_tool_name(merged) == "Reading configuration file"
    assert extract_tool_input(merged) == {"path": "/config.json"}


def test_coalesce_tool_call_update_flattens_content_blocks() -> None:
    upd = {
        "sessionUpdate": "tool_call_update",
        "toolCallId": "call_001",
        "content": [
            {
                "type": "content",
                "content": {"type": "text", "text": "Found 3 files"},
            }
        ],
    }
    merged = coalesce_acp_tool_call_update_session_dict(upd)
    out = extract_tool_output(merged)
    assert out == "Found 3 files"
