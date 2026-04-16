from __future__ import annotations

from src.connectors.acp_core.tool_markdown import (
    DEFAULT_MAX_MARKDOWN_FIELD_CHARS,
    coalesce_acp_tool_call_update_session_dict,
    coalesce_acp_tool_session_dict,
    extract_tool_correlation_key,
    extract_tool_input,
    extract_tool_name,
    extract_tool_output,
    format_tool_invocation_block,
    format_tool_output_fragment,
    format_tool_section,
    normalize_display_value,
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


def test_format_tool_section_includes_input_and_output() -> None:
    text = format_tool_section(
        "todowrite",
        input_obj={"todos": [{"content": "x", "status": "completed"}]},
        output_obj=[{"content": "x", "status": "completed"}],
    )
    assert "**Tool: todowrite**" in text
    assert "**Input:**" in text
    assert "```json" in text
    assert "**Output:**" in text


def test_format_tool_output_fragment_status_only() -> None:
    frag = format_tool_output_fragment(None, status="complete")
    assert "**Status:** complete" in frag


def test_normalize_display_value_truncates() -> None:
    long = "x" * (DEFAULT_MAX_MARKDOWN_FIELD_CHARS + 50)
    out = normalize_display_value(long, max_chars=100)
    assert len(out) <= 100 + len("\n\n[truncated]")
    assert "[truncated]" in out


def test_format_tool_invocation_block() -> None:
    block = format_tool_invocation_block("read_file", None)
    assert "**Tool: read_file**" in block


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


def test_format_tool_section_escapes_nested_triple_backticks_in_output() -> None:
    text = format_tool_section(
        "run",
        output_obj="line1\n```python\nprint(1)\n```\nline2",
    )
    assert "```python" in text
    assert text.count("```") >= 4
    lines = [
        ln
        for ln in text.splitlines()
        if ln.strip() and all(c == "`" for c in ln.strip())
    ]
    assert any(len(ln.strip()) > 3 for ln in lines)
