from typing import cast

import pytest
from src.command_parser import CommandParser
from tests.unit.core.test_doubles import MockSuccessCommand

# --- Tests for CommandParser.process_text ---


@pytest.mark.asyncio
async def test_process_text_single_command(command_parser: CommandParser):
    text_content = "!/hello"
    # Reset call state of mock command for this specific test run with this parser instance
    cast(MockSuccessCommand, command_parser.handlers["hello"]).reset_mock_state()

    (
        modified_text,
        commands_found,
    ) = await command_parser.command_processor.process_text_and_execute_command(
        text_content
    )
    assert commands_found is True
    assert modified_text == ""  # Command-only message results in empty text
    hello_handler = command_parser.handlers["hello"]
    assert isinstance(hello_handler, MockSuccessCommand)
    assert hello_handler.called is True


@pytest.mark.asyncio
async def test_process_text_command_with_prefix_text(command_parser: CommandParser):
    text_content = "Some text !/hello"
    cast(MockSuccessCommand, command_parser.handlers["hello"]).reset_mock_state()
    # Expected: "Some text " (space after prefix is preserved if command is not line start)
    # The trailing space from "!/hello" is consumed by the match.
    # The parser adds replacement, which is empty for successful known command.
    # So, "Some text " + "" + "" = "Some text "
    # If it were "Some text!/hello", it would be "Some text"
    # Actual behavior due to .strip() at the end of process_text:
    (
        modified_text,
        commands_found,
    ) = await command_parser.command_processor.process_text_and_execute_command(
        text_content
    )
    assert commands_found is True
    assert modified_text == "Some text"  # .strip() removes trailing space
    hello_handler = command_parser.handlers["hello"]
    assert isinstance(hello_handler, MockSuccessCommand)
    assert hello_handler.called is True


# Removed @pytest.mark.parametrize for preserve_unknown
@pytest.mark.asyncio
async def test_process_text_command_with_suffix_text(command_parser: CommandParser):
    text_content = "!/hello Some text"
    cast(MockSuccessCommand, command_parser.handlers["hello"]).reset_mock_state()
    # Expected: " Some text" (space before suffix is preserved)
    # Actual behavior due to .strip() at the end of process_text:
    (
        modified_text,
        commands_found,
    ) = await command_parser.command_processor.process_text_and_execute_command(
        text_content
    )
    assert commands_found is True
    assert modified_text == "Some text"  # .strip() removes leading space
    hello_handler = command_parser.handlers["hello"]
    assert isinstance(hello_handler, MockSuccessCommand)
    assert hello_handler.called is True


@pytest.mark.asyncio
async def test_process_text_command_with_prefix_and_suffix_text(
    command_parser: CommandParser,
):
    text_content = "Prefix !/hello Suffix"
    cast(MockSuccessCommand, command_parser.handlers["hello"]).reset_mock_state()
    # Expected: "Prefix  Suffix" (two spaces if original had one before and one after)
    # "Prefix " + "" + " Suffix"
    # Actual behavior due to re.sub(r"\s+", " ", modified_text).strip()
    (
        modified_text,
        commands_found,
    ) = await command_parser.command_processor.process_text_and_execute_command(
        text_content
    )
    assert commands_found is True
    assert modified_text == "Prefix Suffix"  # Multiple spaces collapsed, then stripped
    hello_handler = command_parser.handlers["hello"]
    assert isinstance(hello_handler, MockSuccessCommand)
    assert hello_handler.called is True


@pytest.mark.asyncio
async def test_process_text_multiple_commands_only_first_processed(
    command_parser: CommandParser,
):
    text_content = "!/hello !/anothercmd"
    cast(MockSuccessCommand, command_parser.handlers["hello"]).reset_mock_state()
    cast(MockSuccessCommand, command_parser.handlers["anothercmd"]).reset_mock_state()
    (
        modified_text,
        commands_found,
    ) = await command_parser.command_processor.process_text_and_execute_command(
        text_content
    )
    assert commands_found is True
    # !/hello is processed and removed. "!/anothercmd" remains.
    # The space before "!/anothercmd" is part of the match of !/hello if we consider it greedy
    # or how splitting works.
    # With current regex and logic:
    # match for !/hello is `match.group(0) = "!/hello"`
    # modified_text = "" (from !/hello) + " !/anothercmd"
    # Actual behavior: final .strip() might remove leading space if !/anothercmd is only thing left.
    # And re.sub(r"\s+", " ", ...) will handle the space between them.
    # Initial: "!/hello !/anothercmd" -> after removing !/hello: " !/anothercmd"
    # Then: re.sub(" +", " ", " !/anothercmd").strip() -> "!/anothercmd"
    assert modified_text == "!/anothercmd"

    hello_handler = command_parser.handlers["hello"]
    another_cmd_handler = command_parser.handlers["anothercmd"]
    assert isinstance(hello_handler, MockSuccessCommand)
    assert isinstance(another_cmd_handler, MockSuccessCommand)
    assert hello_handler.called is True
    assert another_cmd_handler.called is False  # Crucial check


@pytest.mark.asyncio
async def test_process_text_no_command(command_parser: CommandParser):
    text_content = "Just some text"
    cast(MockSuccessCommand, command_parser.handlers["hello"]).reset_mock_state()
    (
        modified_text,
        commands_found,
    ) = await command_parser.command_processor.process_text_and_execute_command(
        text_content
    )
    assert commands_found is False
    assert modified_text == "Just some text"
    hello_handler = command_parser.handlers["hello"]
    assert isinstance(hello_handler, MockSuccessCommand)
    assert hello_handler.called is False


# This test now uses the parameterized command_parser fixture
@pytest.mark.asyncio
async def test_process_text_unknown_command(command_parser: CommandParser):
    # Test with a command that matches regex but isn't in handlers
    text_content_valid_format_unknown = "!/cmd-not-real(arg=val)"
    cast(MockSuccessCommand, command_parser.handlers["hello"]).reset_mock_state()
    cast(MockSuccessCommand, command_parser.handlers["anothercmd"]).reset_mock_state()

    (
        modified_text,
        commands_found,
    ) = await command_parser.command_processor.process_text_and_execute_command(
        text_content_valid_format_unknown
    )
    assert commands_found is True  # Command *format* was detected

    if command_parser.config.preserve_unknown:
        assert modified_text == "!/cmd-not-real(arg=val)"  # Preserved
    else:
        assert modified_text == ""  # Not preserved, removed

    # Check that no known handlers were called (redundant due to reset, but good check)
    hello_handler = command_parser.handlers.get("hello")
    if hello_handler and isinstance(hello_handler, MockSuccessCommand):
        assert hello_handler.called is False
