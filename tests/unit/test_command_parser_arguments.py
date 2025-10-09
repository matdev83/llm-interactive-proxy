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
def test_parser_handles_complex_arguments(content: str, expected_args: dict[str, str]) -> None:
    """Ensure the parser keeps argument values intact when they contain commas."""

    parser = CommandParser()
    parsed = parser.parse(content)
    assert parsed is not None
    command, matched_text = parsed

    assert matched_text == content
    assert command.name == "set"
    assert command.args == expected_args
