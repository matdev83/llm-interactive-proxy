from typing import cast

import pytest
from src.command_parser import CommandParser
from src.core.domain.chat import ChatMessage, MessageContentPartText

from tests.unit.core.test_doubles import MockSuccessCommand

# --- Tests for CommandParser.process_messages ---


@pytest.mark.asyncio
async def test_process_messages_single_message_with_command(
    command_parser: CommandParser,
):
    messages = [ChatMessage(role="user", content="!/hello")]
    cast(MockSuccessCommand, command_parser.handlers["hello"]).reset_mock_state()
    processed_messages, any_command_processed = await command_parser.process_messages(
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

    processed_messages, any_command_processed = await command_parser.process_messages(
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

    processed_messages, any_command_processed = await command_parser.process_messages(
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
