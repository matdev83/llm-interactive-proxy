import pytest
from src.core.commands.parser import CommandParser
from src.core.commands.service import NewCommandService
from src.core.domain.chat import ChatMessage
from src.core.services.command_processor import (
    CommandProcessor as CoreCommandProcessor,
)

from tests.unit.core.test_doubles import MockSessionService

# Avoid global backend mocking for these focused unit tests
pytestmark = [pytest.mark.no_global_mock]


# --- Tests for CommandParser.process_text ---


@pytest.mark.asyncio
async def test_process_text_single_command():
    # Setup processor with mock commands
    session_service = MockSessionService()
    command_parser = CommandParser()
    service = NewCommandService(session_service, command_parser)
    processor = CoreCommandProcessor(service)

    # Prepare message with command
    messages = [ChatMessage(role="user", content="!/hello")]
    result = await processor.process_messages(messages, session_id="s1")
    assert result.command_executed
    if result.modified_messages:
        assert result.modified_messages[0].content in ("", " ")


@pytest.mark.asyncio
async def test_process_text_command_with_prefix_text():
    session_service = MockSessionService()
    command_parser = CommandParser()
    service = NewCommandService(session_service, command_parser)
    processor = CoreCommandProcessor(service)

    messages = [ChatMessage(role="user", content="Some text !/hello")]
    result = await processor.process_messages(messages, session_id="s1")
    assert result.command_executed
    if result.modified_messages:
        assert result.modified_messages[0].content.strip() == "Some text"


# Removed @pytest.mark.parametrize for preserve_unknown
@pytest.mark.asyncio
async def test_process_text_command_with_suffix_text():
    session_service = MockSessionService()
    command_parser = CommandParser()
    service = NewCommandService(session_service, command_parser)
    processor = CoreCommandProcessor(service)

    messages = [ChatMessage(role="user", content="!/hello Some text")]
    result = await processor.process_messages(messages, session_id="s1")
    assert result.command_executed
    if result.modified_messages:
        assert result.modified_messages[0].content.strip() == "Some text"


@pytest.mark.asyncio
async def test_process_text_command_with_prefix_and_suffix_text():
    session_service = MockSessionService()
    command_parser = CommandParser()
    service = NewCommandService(session_service, command_parser)
    processor = CoreCommandProcessor(service)

    messages = [ChatMessage(role="user", content="Prefix !/hello Suffix")]
    result = await processor.process_messages(messages, session_id="s1")
    assert result.command_executed
    if result.modified_messages:
        # Current implementation behavior: preserves prefix and suffix, removes command
        assert result.modified_messages[0].content == "Prefix  Suffix"


@pytest.mark.asyncio
async def test_process_text_multiple_commands_only_first_processed():
    session_service = MockSessionService()
    command_parser = CommandParser()
    service = NewCommandService(session_service, command_parser)
    processor = CoreCommandProcessor(service)

    messages = [ChatMessage(role="user", content="!/hello !/anothercmd")]
    result = await processor.process_messages(messages, session_id="s1")
    assert result.command_executed
    if result.modified_messages:
        assert result.modified_messages[0].content.strip() == "!/anothercmd"


@pytest.mark.asyncio
async def test_process_text_no_command():
    session_service = MockSessionService()
    command_parser = CommandParser()
    service = NewCommandService(session_service, command_parser)
    processor = CoreCommandProcessor(service)

    messages = [ChatMessage(role="user", content="Just some text")]
    result = await processor.process_messages(messages, session_id="s1")
    assert not result.command_executed
    if result.modified_messages:
        assert result.modified_messages[0].content == "Just some text"


# This test now uses the parameterized command_parser fixture
@pytest.mark.asyncio
async def test_process_text_unknown_command():
    # Do not register unknown command
    session_service = MockSessionService()
    command_parser = CommandParser()
    service = NewCommandService(session_service, command_parser)
    processor = CoreCommandProcessor(service)
    messages = [ChatMessage(role="user", content="!/cmd-not-real(arg=val)")]
    result = await processor.process_messages(messages, session_id="s1")
    assert not result.command_executed
    if result.modified_messages:
        assert result.modified_messages[0].content in ("", " ")
