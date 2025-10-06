from typing import Any

from src.command_utils import (
    extract_feedback_from_tool_result,
    get_text_for_command_check,
    is_content_effectively_empty,
    is_original_purely_command,
    is_tool_call_result,
)
from src.core.domain.chat import (
    ImageURL,
    MessageContentPartImage,
    MessageContentPartText,
)
from src.core.services.command_utils import get_command_pattern


def test_is_content_effectively_empty_with_strings() -> None:
    assert is_content_effectively_empty("") is True
    assert is_content_effectively_empty("   \n\t") is True
    assert is_content_effectively_empty("hello") is False


def test_is_content_effectively_empty_with_list_text_parts() -> None:
    parts: list[Any] = [
        MessageContentPartText(text=" "),
        MessageContentPartText(text="\n"),
    ]
    assert is_content_effectively_empty(parts) is True

    parts = [MessageContentPartText(text=" command ")]
    assert is_content_effectively_empty(parts) is False


def test_is_content_effectively_empty_with_non_text_part() -> None:
    image = MessageContentPartImage(image_url=ImageURL(url="https://example.com/x.png"))
    parts: list[Any] = [image]
    # Presence of a non-text part means it's not empty
    assert is_content_effectively_empty(parts) is False


def test_is_tool_call_result_detection() -> None:
    assert (
        is_tool_call_result("[read_file for 'foo.txt'] Result: contents here\n") is True
    )
    assert is_tool_call_result("normal user text without tool result header") is False


def test_extract_feedback_from_tool_result() -> None:
    text = (
        "[attempt_completion] Result:\n<feedback>\n!/set(project=demo)\n</feedback>\n"
    )
    assert extract_feedback_from_tool_result(text) == "!/set(project=demo)"

    # No feedback present
    assert extract_feedback_from_tool_result("[x] Result: no feedback") == ""


def test_get_text_for_command_check_basic_and_comments() -> None:
    # Comments should be stripped
    raw = "# heading\n!/run(task)\n# trailing comment\n"
    assert get_text_for_command_check(raw) == "!/run(task)"

    # From multimodal content
    parts = [
        MessageContentPartText(text="# preface\n"),
        MessageContentPartText(text="!/apply(x=1)\n"),
    ]
    assert get_text_for_command_check(parts) == "!/apply(x=1)"


def test_get_text_for_command_check_with_tool_result_feedback() -> None:
    text = (
        "[tool_name for 'abc'] Result:\n<feedback>\n# note\n!/do_it(now)\n</feedback>\n"
    )
    # Should extract only the feedback block and strip comments
    assert get_text_for_command_check(text) == "!/do_it(now)"


def test_is_original_purely_command_for_strings_and_lists() -> None:
    pattern = get_command_pattern("!/")

    # Exact command string
    assert is_original_purely_command("!/echo(hi)", pattern) is True
    # Any additional non-command text or comments disqualify
    assert is_original_purely_command("!/echo(hi)\n# meta", pattern) is False
    assert is_original_purely_command(" context !/echo(hi)", pattern) is False

    # Single text part list with exact command
    parts = [MessageContentPartText(text="!/x(1)")]
    assert is_original_purely_command(parts, pattern) is True

    # Multiple parts or non-text parts disqualify
    image = MessageContentPartImage(image_url=ImageURL(url="https://example.com/x.png"))
    parts2: list[Any] = [MessageContentPartText(text="!/x(1)"), image]
    assert is_original_purely_command(parts2, pattern) is False
