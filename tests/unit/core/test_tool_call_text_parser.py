from src.core.commands.tool_call_text_parser import parse_textual_tool_invocation


def test_parse_tool_call_block_with_json_parameter() -> None:
    payload = """<tool_call>
<function=read_file>
<parameter=files>
[{"path": "src/connectors/zenmux.py", "line_ranges": ["40", "55"]}]
</parameter>
</function>
</tool_call>"""

    invocation = parse_textual_tool_invocation(payload)
    assert invocation is not None
    assert invocation.canonical_name == "read_file"
    assert "files" in invocation.arguments
    assert invocation.arguments["files"] == [
        {"path": "src/connectors/zenmux.py", "line_ranges": ["40", "55"]}
    ]
