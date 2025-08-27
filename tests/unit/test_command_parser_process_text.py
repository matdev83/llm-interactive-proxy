import pytest
from src.core.domain.chat import ChatMessage
from src.core.services.command_processor import (
    CommandProcessor as CoreCommandProcessor,
)
from src.core.services.command_service import CommandRegistry, CommandService

from tests.unit.core.test_doubles import MockSessionService, MockSuccessCommand
from tests.unit.mock_commands import get_mock_commands

# Avoid global backend mocking for these focused unit tests
pytestmark = [pytest.mark.no_global_mock]

# --- Tests for CommandParser.process_text ---


@pytest.mark.asyncio
async def test_process_text_single_command():
    # Setup processor with mock commands
    registry = CommandRegistry()
    for cmd in get_mock_commands().values():
        registry.register(cmd)
    session_service = MockSessionService()
    service = CommandService(registry, session_service)
    processor = CoreCommandProcessor(service)

    # Prepare message with command
    messages = [ChatMessage(role="user", content="!/hello")]
    result = await processor.process_messages(messages, session_id="s1")
    assert result.command_executed
    if result.modified_messages:
        assert result.modified_messages[0].content in ("", " ")
    hello_handler = registry.get("hello")
    assert isinstance(hello_handler, MockSuccessCommand)
    assert hello_handler.called is True


@pytest.mark.asyncio
async def test_process_text_command_with_prefix_text():
    registry = CommandRegistry()
    for cmd in get_mock_commands().values():
        registry.register(cmd)
    session_service = MockSessionService()
    service = CommandService(registry, session_service)
    processor = CoreCommandProcessor(service)

    messages = [ChatMessage(role="user", content="Some text !/hello")]
    result = await processor.process_messages(messages, session_id="s1")
    assert result.command_executed
    if result.modified_messages:
        assert result.modified_messages[0].content.strip() == "Some text"
    hello_handler = registry.get("hello")
    assert isinstance(hello_handler, MockSuccessCommand)
    assert hello_handler.called is True


# Removed @pytest.mark.parametrize for preserve_unknown
@pytest.mark.asyncio
async def test_process_text_command_with_suffix_text():
    registry = CommandRegistry()
    for cmd in get_mock_commands().values():
        registry.register(cmd)
    session_service = MockSessionService()
    service = CommandService(registry, session_service)
    processor = CoreCommandProcessor(service)

    messages = [ChatMessage(role="user", content="!/hello Some text")]
    result = await processor.process_messages(messages, session_id="s1")
    assert result.command_executed
    if result.modified_messages:
        assert result.modified_messages[0].content.strip() == "Some text"
    hello_handler = registry.get("hello")
    assert isinstance(hello_handler, MockSuccessCommand)
    assert hello_handler.called is True


@pytest.mark.asyncio
async def test_process_text_command_with_prefix_and_suffix_text():
    registry = CommandRegistry()
    for cmd in get_mock_commands().values():
        registry.register(cmd)
    session_service = MockSessionService()
    service = CommandService(registry, session_service)
    processor = CoreCommandProcessor(service)

    messages = [ChatMessage(role="user", content="Prefix !/hello Suffix")]
    result = await processor.process_messages(messages, session_id="s1")
    assert result.command_executed
    if result.modified_messages:
        # Current implementation behavior: returns just the suffix part
        assert result.modified_messages[0].content == " Suffix"
    hello_handler = registry.get("hello")
    assert isinstance(hello_handler, MockSuccessCommand)
    assert hello_handler.called is True


@pytest.mark.asyncio
async def test_process_text_multiple_commands_only_first_processed():
    registry = CommandRegistry()
    for cmd in get_mock_commands().values():
        registry.register(cmd)
    session_service = MockSessionService()
    service = CommandService(registry, session_service)
    processor = CoreCommandProcessor(service)

    messages = [ChatMessage(role="user", content="!/hello !/anothercmd")]
    result = await processor.process_messages(messages, session_id="s1")
    assert result.command_executed
    if result.modified_messages:
        assert result.modified_messages[0].content.strip() == "!/anothercmd"
    hello_handler = registry.get("hello")
    another_cmd_handler = registry.get("anothercmd")
    assert isinstance(hello_handler, MockSuccessCommand)
    assert isinstance(another_cmd_handler, MockSuccessCommand)
    assert hello_handler.called is True
    assert another_cmd_handler.called is False


@pytest.mark.asyncio
async def test_process_text_no_command():
    registry = CommandRegistry()
    for cmd in get_mock_commands().values():
        registry.register(cmd)
    session_service = MockSessionService()
    service = CommandService(registry, session_service)
    processor = CoreCommandProcessor(service)

    messages = [ChatMessage(role="user", content="Just some text")]
    result = await processor.process_messages(messages, session_id="s1")
    assert not result.command_executed
    if result.modified_messages:
        assert result.modified_messages[0].content == "Just some text"
    hello_handler = registry.get("hello")
    assert isinstance(hello_handler, MockSuccessCommand)
    assert hello_handler.called is False


# This test now uses the parameterized command_parser fixture
@pytest.mark.asyncio
async def test_process_text_unknown_command():
    registry = CommandRegistry()
    # Do not register unknown command
    for cmd in get_mock_commands().values():
        registry.register(cmd)
    session_service = MockSessionService()
    service = CommandService(registry, session_service)
    processor = CoreCommandProcessor(service)
    messages = [ChatMessage(role="user", content="!/cmd-not-real(arg=val)")]
    result = await processor.process_messages(messages, session_id="s1")
    assert result.command_executed
    if result.modified_messages:
        assert result.modified_messages[0].content in ("", " ")
    hello_handler = registry.get("hello")
    assert isinstance(hello_handler, MockSuccessCommand)
    assert hello_handler.called is False
