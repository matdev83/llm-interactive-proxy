from __future__ import annotations

from src.connectors.acp_core.tool_markdown import (
    DEFAULT_MAX_MARKDOWN_FIELD_CHARS,
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
