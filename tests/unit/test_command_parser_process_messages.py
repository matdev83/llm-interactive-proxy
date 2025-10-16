import pytest
from src.core.commands.parser import CommandParser
from src.core.domain.chat import ChatMessage, MessageContentPartText
from src.core.services.application_state_service import ApplicationStateService
from src.core.services.command_processor import (
    CommandProcessor as CoreCommandProcessor,
)

from tests.unit.core.test_doubles import MockSessionService
from tests.utils.command_service_utils import build_new_command_service

# Avoid global backend mocking for these focused unit tests
pytestmark = [pytest.mark.no_global_mock]


# --- Tests for CommandParser.process_messages ---


@pytest.mark.asyncio
async def test_process_messages_single_message_with_command() -> None:
    # Setup DI-driven processor
    session_service = MockSessionService()
    command_parser = CommandParser()
    service = build_new_command_service(session_service, command_parser)
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
    service = build_new_command_service(session_service, command_parser)
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
    assert result.command_executed is False
    assert processed_messages == messages


# Removed @pytest.mark.parametrize for preserve_unknown
@pytest.mark.asyncio
async def test_process_messages_processes_command_in_last_message_and_stops() -> None:
    session_service = MockSessionService()
    command_parser = CommandParser()
    service = build_new_command_service(session_service, command_parser)
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
    assert processed_messages[1].content == "text before"


@pytest.mark.asyncio
async def test_process_messages_uses_runtime_command_prefix() -> None:
    session_service = MockSessionService()
    command_parser = CommandParser()
    app_state = ApplicationStateService()
    app_state.set_command_prefix("$/")

    service = build_new_command_service(
        session_service,
        command_parser,
        app_state=app_state,
    )
    processor = CoreCommandProcessor(service)

    messages = [ChatMessage(role="user", content="$/hello")]
    result = await processor.process_messages(messages, session_id="test-session")

    assert result.command_executed is True
    assert command_parser.command_prefix == "$/"


@pytest.mark.asyncio
async def test_process_messages_respects_interactive_disable() -> None:
    session_service = MockSessionService()
    command_parser = CommandParser()
    app_state = ApplicationStateService()
    app_state.set_disable_interactive_commands(True)

    service = build_new_command_service(
        session_service,
        command_parser,
        app_state=app_state,
    )
    processor = CoreCommandProcessor(service)

    messages = [ChatMessage(role="user", content="!/hello")]
    result = await processor.process_messages(messages, session_id="test-session")

    assert result.command_executed is False
    assert result.modified_messages == messages


@pytest.mark.asyncio
async def test_process_messages_trailing_whitespace_command() -> None:
    session_service = MockSessionService()
    command_parser = CommandParser()
    service = build_new_command_service(session_service, command_parser)
    processor = CoreCommandProcessor(service)

    messages = [
        ChatMessage(
            role="user",
            content="Please adjust settings\n!/set(project=demo)   ",
        )
    ]

    result = await processor.process_messages(messages, session_id="test-session")
    processed_messages = result.modified_messages

    assert result.command_executed is True
    assert result.command_results[-1].name == "set"
    assert processed_messages[0].content == "Please adjust settings"


@pytest.mark.asyncio
async def test_process_messages_only_last_command_in_line_executed() -> None:
    session_service = MockSessionService()
    command_parser = CommandParser()
    service = build_new_command_service(session_service, command_parser)
    processor = CoreCommandProcessor(service)

    messages = [
        ChatMessage(
            role="user",
            content="Run diagnostics !/hello !/set(model=openrouter:foo)",
        )
    ]

    result = await processor.process_messages(messages, session_id="test-session")
    processed_messages = result.modified_messages

    assert result.command_executed is True
    assert result.command_results[-1].name == "set"
    assert processed_messages[0].content == "Run diagnostics !/hello"


@pytest.mark.asyncio
async def test_process_messages_multimodal_tail_command_with_whitespace() -> None:
    session_service = MockSessionService()
    command_parser = CommandParser()
    service = build_new_command_service(session_service, command_parser)
    processor = CoreCommandProcessor(service)

    messages = [
        ChatMessage(
            role="user",
            content=[
                MessageContentPartText(type="text", text="Notes for later"),
                MessageContentPartText(
                    type="text", text="Next actions\n!/set(project=demo)   "
                ),
            ],
        )
    ]

    result = await processor.process_messages(messages, session_id="test-session")
    processed_messages = result.modified_messages

    assert result.command_executed is True
    assert result.command_results[-1].name == "set"
    assert isinstance(processed_messages[0].content, list)
    assert processed_messages[0].content[1].text == "Next actions"
