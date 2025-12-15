from src.core.commands.tool_call_text_parser import parse_textual_tool_invocation


def test_parse_use_mcp_tool_with_json_arguments():
    text = (
        '<use_mcp_tool tool_name="patch_file">'
        '{"patch_content": "<<<< SEARCH>>>", "file_path": "main.py"}'
        "</use_mcp_tool>"
    )

    result = parse_textual_tool_invocation(text)

    assert result is not None
    assert result.canonical_name == "use_mcp_tool"
    assert result.arguments["tool_name"] == "patch_file"
    assert result.arguments["tool_arguments"] == {
        "patch_content": "<<<< SEARCH>>>",
        "file_path": "main.py",
    }
    assert result.arguments["patch_content"] == "<<<< SEARCH>>>"
