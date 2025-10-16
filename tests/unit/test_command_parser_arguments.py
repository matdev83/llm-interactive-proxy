"""Tests for the command parser argument handling."""

import pytest
from src.core.commands.parser import CommandParser


@pytest.mark.parametrize(
    "content, expected_args",
    [
        (
            "!/set(gemini-generation-config={'thinkingConfig': {'thinkingBudget': 1024, 'foo': 'bar'}})",
            {
                "gemini-generation-config": "{'thinkingConfig': {'thinkingBudget': 1024, 'foo': 'bar'}}"
            },
        ),
        (
            "!/set(pattern=(?P<name>[a-zA-Z_][\\w-]+),flag=yes)",
            {
                "pattern": "(?P<name>[a-zA-Z_][\\w-]+)",
                "flag": "yes",
            },
        ),
    ],
)
def test_parser_handles_complex_arguments(
    content: str, expected_args: dict[str, str]
) -> None:
    """Ensure the parser keeps argument values intact when they contain commas."""

    parser = CommandParser()
    parsed = parser.parse(content)
    assert len(parsed) == 1
    command = parsed[0].command
    matched_text = parsed[0].matched_text

    assert matched_text == content
    assert command.name == "set"
    assert command.args == expected_args


def test_parser_returns_multiple_commands_in_order() -> None:
    parser = CommandParser()
    content = "!/hello !/set(temperature=0.2) \nother text !/unset(model)"

    parsed = parser.parse(content)

    assert [item.command.name for item in parsed] == ["hello", "set", "unset"]
    assert parsed[1].command.args == {"temperature": "0.2"}
