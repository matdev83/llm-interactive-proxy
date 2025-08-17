# --- Mocks ---
from collections.abc import AsyncGenerator, Mapping
from typing import Any, cast

import pytest
from fastapi import FastAPI
from src.command_config import CommandParserConfig
from src.command_parser import CommandParser, get_command_pattern
from src.command_processor import parse_arguments
from src.commands import BaseCommand, CommandResult
from src.constants import DEFAULT_COMMAND_PREFIX
from src.core.domain.session import SessionStateAdapter
from src.models import ChatMessage, MessageContentPartText


class MockSuccessCommand(BaseCommand):
    def __init__(self, command_name: str, app: FastAPI | None = None):
        super().__init__(app=app)
        self.name = command_name
        self._called = False
        self._called_with_args: dict[str, Any] | None = None

    @property
    def called(self) -> bool:
        return self._called

    @property
    def called_with_args(self) -> dict[str, Any] | None:
        return self._called_with_args

    def reset_mock_state(self):
        self._called = False
        self._called_with_args = None

    def execute(
        self, args: Mapping[str, Any], state: SessionStateAdapter
    ) -> CommandResult:
        self._called = True
        self._called_with_args = dict(args)  # Convert Mapping to Dict for storage
        return CommandResult(self.name, True, f"{self.name} executed successfully")


# --- Fixtures ---


@pytest.fixture
def mock_app() -> FastAPI:
    app = FastAPI()
    # Essential for CommandParser init if create_command_instances relies on it
    app.state.functional_backends = {"openrouter", "gemini"}
    app.state.config_manager = None  # Mock this if it's used during command loading
    return app


@pytest.fixture
def proxy_state() -> SessionStateAdapter:
    from src.core.domain.session import SessionState

    session_state = SessionState()
    return SessionStateAdapter(session_state)


@pytest.fixture(
    params=[True, False], ids=["preserve_unknown_True", "preserve_unknown_False"]
)
async def command_parser(
    request, mock_app: FastAPI, proxy_state: SessionStateAdapter
) -> AsyncGenerator[CommandParser, None]:
    preserve_unknown_val = request.param
    parser_config = CommandParserConfig(
        proxy_state=proxy_state,
        app=mock_app,
        preserve_unknown=preserve_unknown_val,
        functional_backends=mock_app.state.functional_backends,
    )
    parser = CommandParser(parser_config, command_prefix=DEFAULT_COMMAND_PREFIX)
    parser.handlers.clear()

    # Create fresh mocks for each parametrization to avoid state leakage
    # Pass the mock_app to the command constructor if it needs it (optional here)
    hello_cmd = MockSuccessCommand("hello", app=mock_app)
    another_cmd = MockSuccessCommand("anothercmd", app=mock_app)
    parser.register_command(hello_cmd)
    parser.register_command(another_cmd)
    yield parser


def test_parse_arguments_empty():
    assert parse_arguments("") == {}
    assert parse_arguments("   ") == {}


def test_parse_arguments_simple_key_value():
    assert parse_arguments("key=value") == {"key": "value"}
    assert parse_arguments("  key  =  value  ") == {"key": "value"}


def test_parse_arguments_multiple_key_values():
    expected = {"key1": "value1", "key2": "value2"}
    assert parse_arguments("key1=value1,key2=value2") == expected
    assert parse_arguments("  key1 = value1 ,  key2 = value2  ") == expected


def test_parse_arguments_boolean_true():
    assert parse_arguments("flag") == {"flag": True}
    assert parse_arguments("  flag  ") == {"flag": True}
    assert parse_arguments("flag1,key=value,flag2") == {
        "flag1": True,
        "key": "value",
        "flag2": True,
    }


def test_parse_arguments_mixed_values():
    # E501: Linelength
    expected = {"str_arg": "hello world", "bool_arg": True, "num_arg": "123"}
    assert parse_arguments('str_arg="hello world", bool_arg, num_arg=123') == expected


def test_parse_arguments_quotes_stripping():
    assert parse_arguments('key="value"') == {"key": "value"}
    assert parse_arguments("key='value'") == {"key": "value"}
    # E501: Linelength
    assert parse_arguments('key=" value with spaces "') == {
        "key": " value with spaces "
    }


# --- Tests for get_command_pattern ---


def test_get_command_pattern_default_prefix():
    pattern = get_command_pattern(DEFAULT_COMMAND_PREFIX)
    assert pattern.match("!/hello")
    assert pattern.match("!/cmd(arg=val)")
    assert not pattern.match("/hello")
    m = pattern.match("!/hello")
    assert m and m.group("cmd") == "hello" and (m.group("args") or "") == ""
    m = pattern.match("!/cmd(arg=val)")
    assert m and m.group("cmd") == "cmd" and m.group("args") == "arg=val"


def test_get_command_pattern_custom_prefix():
    pattern = get_command_pattern("@")
    assert pattern.match("@hello")
    assert pattern.match("@cmd(arg=val)")
    assert not pattern.match("!/hello")


# --- Tests for CommandParser.process_text ---


@pytest.mark.asyncio
async def test_process_text_single_command(command_parser: CommandParser):
    text_content = "!/hello"
    # Reset call state of mock command for this specific test run with this parser instance
    cast(MockSuccessCommand, command_parser.handlers["hello"]).reset_mock_state()

    modified_text, commands_found = (
        command_parser.command_processor.process_text_and_execute_command(text_content)
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
    modified_text, commands_found = (
        command_parser.command_processor.process_text_and_execute_command(text_content)
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
    modified_text, commands_found = (
        command_parser.command_processor.process_text_and_execute_command(text_content)
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
    modified_text, commands_found = (
        command_parser.command_processor.process_text_and_execute_command(text_content)
    )
    assert commands_found is True
    assert modified_text == "Prefix Suffix"  # Multiple spaces collapsed, then stripped
    hello_handler = command_parser.handlers["hello"]
    assert isinstance(hello_handler, MockSuccessCommand)
    assert hello_handler.called is True


async def test_process_text_multiple_commands_only_first_processed(
    command_parser: CommandParser,
):
    text_content = "!/hello !/anothercmd"
    cast(MockSuccessCommand, command_parser.handlers["hello"]).reset_mock_state()
    cast(MockSuccessCommand, command_parser.handlers["anothercmd"]).reset_mock_state()
    modified_text, commands_found = (
        command_parser.command_processor.process_text_and_execute_command(text_content)
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
    modified_text, commands_found = (
        command_parser.command_processor.process_text_and_execute_command(text_content)
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

    modified_text, commands_found = (
        command_parser.command_processor.process_text_and_execute_command(
            text_content_valid_format_unknown
        )
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


# --- Tests for CommandParser.process_messages ---


@pytest.mark.asyncio
async def test_process_messages_single_message_with_command(
    command_parser: CommandParser,
):
    messages = [ChatMessage(role="user", content="!/hello")]
    cast(MockSuccessCommand, command_parser.handlers["hello"]).reset_mock_state()
    processed_messages, any_command_processed = command_parser.process_messages(
        messages
    )

    assert any_command_processed is True
    # The message content becomes "" if it was a command-only message and command succeeded
    assert len(processed_messages) == 1
    # Based on current main.py logic, command-only messages are kept if they start with prefix
    # but their content is set to ""
    assert processed_messages[0].content == ""

    hello_handler = command_parser.handlers["hello"]
    assert isinstance(hello_handler, MockSuccessCommand)
    assert hello_handler.called is True


@pytest.mark.asyncio
async def test_process_messages_stops_after_first_command_in_message_content_list(
    command_parser: CommandParser,
):
    messages = [
        ChatMessage(
            role="user",
            content=[
                MessageContentPartText(type="text", text="!/hello"),
                MessageContentPartText(type="text", text="!/anothercmd"),
            ],
        )
    ]
    # Reset call states for handlers
    cast(MockSuccessCommand, command_parser.handlers["hello"]).reset_mock_state()
    cast(MockSuccessCommand, command_parser.handlers["anothercmd"]).reset_mock_state()

    processed_messages, any_command_processed = command_parser.process_messages(
        messages
    )

    assert any_command_processed is True
    assert len(processed_messages) == 1

    # The first part with !/hello should be processed and its text potentially emptied or modified
    # The second part with !/anothercmd should remain as is because processing stops after the first command.
    # process_text will make the first part's text ""
    # The second part's text will be "!/anothercmd"
    # The _clean_remaining_text in process_text might affect this if not handled carefully,
    # but process_messages calls process_text on each part *until a command is found*.

    # The logic is: process_messages iterates parts. For first part, calls process_text("!/hello").
    # process_text processes "!/hello", returns ("", True). Handler for "hello" is called.
    # `part_level_found_in_current_message` becomes True.
    # `already_processed_commands_in_a_message` becomes True.
    # If a part results in empty text AND was a command, it's dropped from new_parts.
    # Loop continues to next part. `already_processed_commands_in_a_message` is True, so process_text is NOT called for "!/anothercmd".
    # So the second text part "!/anothercmd" is added to new_parts as is.

    assert isinstance(processed_messages[0].content, list)
    content_list = processed_messages[0].content
    assert len(content_list) == 1  # !/hello part was processed to "" and dropped

    # The remaining part is "!/anothercmd"
    remaining_part = content_list[0]
    assert isinstance(remaining_part, MessageContentPartText)
    assert remaining_part.text == "!/anothercmd"  # Unprocessed

    hello_handler = command_parser.handlers["hello"]
    another_cmd_handler = command_parser.handlers["anothercmd"]
    assert isinstance(hello_handler, MockSuccessCommand)
    assert isinstance(another_cmd_handler, MockSuccessCommand)
    assert hello_handler.called is True
    assert another_cmd_handler.called is False


# Removed @pytest.mark.parametrize for preserve_unknown
@pytest.mark.asyncio
async def test_process_messages_processes_command_in_last_message_and_stops(
    command_parser: CommandParser,
):
    messages = [
        ChatMessage(role="user", content="!/hello"),
        ChatMessage(role="user", content="!/anothercmd"),
    ]
    # Reset call states for handlers
    cast(MockSuccessCommand, command_parser.handlers["hello"]).reset_mock_state()
    cast(MockSuccessCommand, command_parser.handlers["anothercmd"]).reset_mock_state()

    # `process_messages` iterates from last to first message to find the *last* message
    # containing a command. It then processes only that message and stops.
    # In this case, "!/anothercmd" is in the last message, so it will be processed.
    # "!/hello" will not be processed.

    processed_messages, any_command_processed = command_parser.process_messages(
        messages
    )

    assert any_command_processed is True
    assert len(processed_messages) == 2

    # The command in the last message ("!/anothercmd") is processed, and its content becomes empty.
    # The command in the first message ("!/hello") is not processed, so its content remains.
    assert processed_messages[0].content == "!/hello"  # Unprocessed !/hello
    assert processed_messages[1].content == ""  # Processed !/anothercmd

    hello_handler = command_parser.handlers["hello"]
    another_cmd_handler = command_parser.handlers["anothercmd"]
    assert isinstance(hello_handler, MockSuccessCommand)
    assert isinstance(another_cmd_handler, MockSuccessCommand)

    assert hello_handler.called is False  # Because processing stopped after anothercmd
    assert (
        another_cmd_handler.called is True
    )  # Because it was the command in the last message with a command


# This test is now covered by test_process_messages_processes_command_in_last_message_and_stops.
# The previous test name was misleading given the actual reverse iteration and processing logic.
# No further action needed for this specific test.
