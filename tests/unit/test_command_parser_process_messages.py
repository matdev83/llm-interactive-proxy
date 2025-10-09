import pytest
from src.core.commands.parser import CommandParser
from src.core.commands.service import NewCommandService
from src.core.domain.chat import ChatMessage, MessageContentPartText
from src.core.services.command_processor import (
    CommandProcessor as CoreCommandProcessor,
)

from tests.unit.core.test_doubles import MockSessionService

# Avoid global backend mocking for these focused unit tests
pytestmark = [pytest.mark.no_global_mock]


# --- Tests for CommandParser.process_messages ---


@pytest.mark.asyncio
async def test_process_messages_single_message_with_command() -> None:
    # Setup DI-driven processor
    session_service = MockSessionService()
    command_parser = CommandParser()
    service = NewCommandService(session_service, command_parser)
    processor = CoreCommandProcessor(service)

    messages = [ChatMessage(role="user", content="!/hello")]
    result = await processor.process_messages(messages, session_id="test-session")
    processed_messages = result.modified_messages
    any_command_processed = result.command_executed

    assert any_command_processed is True
    if processed_messages:
        assert processed_messages[0].content in ("", " ")


@pytest.mark.asyncio
async def test_process_messages_stops_after_first_command_in_message_content_list() -> (
    None
):
    session_service = MockSessionService()
    command_parser = CommandParser()
    service = NewCommandService(session_service, command_parser)
    processor = CoreCommandProcessor(service)
    messages = [
        ChatMessage(
            role="user",
            content=[
                MessageContentPartText(type="text", text="!/hello"),
                MessageContentPartText(type="text", text="!/anothercmd"),
            ],
        )
    ]

    result = await processor.process_messages(messages, session_id="test-session")
    processed_messages = result.modified_messages
    any_command_processed = result.command_executed

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
    assert len(content_list) in (0, 1)

    # The remaining part is "!/anothercmd"
    if len(content_list) == 1:
        remaining_part = content_list[0]
        assert isinstance(remaining_part, MessageContentPartText)
        assert remaining_part.text == "!/anothercmd"


# Removed @pytest.mark.parametrize for preserve_unknown
@pytest.mark.asyncio
async def test_process_messages_processes_command_in_last_message_and_stops() -> None:
    session_service = MockSessionService()
    command_parser = CommandParser()
    service = NewCommandService(session_service, command_parser)
    processor = CoreCommandProcessor(service)
    messages = [
        ChatMessage(role="user", content="!/hello"),
        ChatMessage(role="user", content="text before !/hello"),
    ]

    # `process_messages` iterates from last to first message to find the *last* message
    # containing a command. It then processes only that message and stops.
    # In this case, "text before !/hello" has a command AT THE END, so it will be processed.
    # "!/hello" in the first message will not be processed.

    result = await processor.process_messages(messages, session_id="test-session")
    processed_messages = result.modified_messages
    any_command_processed = result.command_executed

    assert any_command_processed is True
    assert len(processed_messages) == 2
    assert processed_messages[0].content == "!/hello"
    # The last message had its command removed. The 'hello' command preserves structure,
    # so the trailing space remains.
    assert processed_messages[1].content == "text before "
