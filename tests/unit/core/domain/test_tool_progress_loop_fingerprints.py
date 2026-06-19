from src.core.domain.chat import FunctionCall, ToolCall
from src.core.domain.tool_progress_loop import (
    fingerprint_tool_call,
    fingerprint_tool_output,
)


def test_tool_call_fingerprint_canonicalizes_json_argument_order() -> None:
    first = ToolCall(
        function=FunctionCall(
            name="read", arguments='{"limit": 20, "filePath": "C:/Repo/File.py"}'
        )
    )
    second = ToolCall(
        function=FunctionCall(
            name="read", arguments='{"filePath": "c:\\\\repo\\\\file.py", "limit": 20}'
        )
    )

    assert (
        fingerprint_tool_call(first).arguments_hash
        == fingerprint_tool_call(second).arguments_hash
    )


def test_tool_call_fingerprint_keeps_shape_stable_for_volatile_values() -> None:
    first = {
        "function": {
            "name": "bash",
            "arguments": '{"command":"tool --request-id abc123 --timeout 10"}',
        }
    }
    second = {
        "function": {
            "name": "bash",
            "arguments": '{"command":"tool --request-id def456 --timeout 10"}',
        }
    }

    first_fp = fingerprint_tool_call(first)
    second_fp = fingerprint_tool_call(second)

    assert first_fp.arguments_hash != second_fp.arguments_hash
    assert first_fp.arguments_shape_hash == second_fp.arguments_shape_hash


def test_tool_call_fingerprint_keeps_legitimate_prefixed_tokens_distinct() -> None:
    first = {
        "function": {
            "name": "bash",
            "arguments": '{"command":"tool --format req_template"}',
        }
    }
    second = {
        "function": {
            "name": "bash",
            "arguments": '{"command":"tool --format req_signature"}',
        }
    }

    assert (
        fingerprint_tool_call(first).arguments_shape_hash
        != fingerprint_tool_call(second).arguments_shape_hash
    )


def test_tool_call_fingerprint_extracts_apply_patch_target_files() -> None:
    fp = fingerprint_tool_call(
        {
            "function": {
                "name": "apply_patch",
                "arguments": '{"patchText":"*** Begin Patch\\n*** Update File: src/app.py\\n@@\\n-old\\n+new\\n*** End Patch"}',
            }
        }
    )

    assert fp.target_resource == "src/app.py"


def test_tool_output_fingerprint_normalizes_timestamps_and_ansi() -> None:
    first = "\x1b[32m2026-06-19 13:21:31 OK result\x1b[0m"
    second = "2026-06-19 13:22:44 OK result"

    assert (
        fingerprint_tool_output(first).output_hash
        == fingerprint_tool_output(second).output_hash
    )


def test_tool_output_fingerprint_classifies_empty_error_and_no_match() -> None:
    assert fingerprint_tool_output("").kind == "empty"
    assert fingerprint_tool_output("ERROR: file not found").kind == "error"
    assert fingerprint_tool_output("No matches found").kind == "no_match"
