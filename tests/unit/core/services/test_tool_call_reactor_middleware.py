from unittest.mock import AsyncMock

import pytest
from src.core.domain.chat import ChatMessage, FunctionCall, ToolCall
from src.core.interfaces.command_processor_interface import ICommandProcessor
from src.core.interfaces.tool_call_reactor_interface import IToolCallReactor
from src.core.services.tool_call_reactor_middleware import ToolCallReactorMiddleware


@pytest.fixture
def mock_tool_call_reactor() -> AsyncMock:
    """Fixture for a mock tool call reactor."""
    return AsyncMock(spec=IToolCallReactor)


@pytest.fixture
def mock_command_processor() -> AsyncMock:
    """Fixture for a mock command processor."""
    return AsyncMock(spec=ICommandProcessor)


@pytest.fixture
def tool_call_reactor_middleware(
    mock_tool_call_reactor: AsyncMock,
) -> ToolCallReactorMiddleware:
    """Fixture for a ToolCallReactorMiddleware instance."""
    return ToolCallReactorMiddleware(tool_call_reactor=mock_tool_call_reactor)


@pytest.mark.asyncio
async def test_middleware_bypassed_when_capability_is_true(
    tool_call_reactor_middleware: ToolCallReactorMiddleware,
    mock_tool_call_reactor: AsyncMock,
) -> None:
    """Test that the middleware is bypassed when the bypass_tool_call_reactor capability is True."""
    tool_call = ToolCall(
        id="call_123",
        function=FunctionCall(name="shell", arguments='{"command": "ls"}'),
        type="function",
    )
    message = ChatMessage(role="assistant", tool_calls=[tool_call])
    context = {
        "session_id": "test_session",
        "bypass_tool_call_reactor": True,
    }

    result = await tool_call_reactor_middleware.process(
        response=message, session_id="test_session", context=context
    )

    assert result is message
    mock_tool_call_reactor.process_tool_call.assert_not_called()


@pytest.mark.asyncio
async def test_middleware_processes_tool_call_when_capability_is_false(
    tool_call_reactor_middleware: ToolCallReactorMiddleware,
    mock_tool_call_reactor: AsyncMock,
) -> None:
    """Test that the middleware processes the tool call when the bypass_tool_call_reactor capability is False."""
    tool_call = ToolCall(
        id="call_123",
        function=FunctionCall(name="shell", arguments='{"command": "ls"}'),
        type="function",
    )
    message = ChatMessage(role="assistant", tool_calls=[tool_call])
    context = {
        "session_id": "test_session",
        "bypass_tool_call_reactor": False,
    }

    await tool_call_reactor_middleware.process(
        response=message, session_id="test_session", context=context
    )

    mock_tool_call_reactor.process_tool_call.assert_called_once()


@pytest.mark.asyncio
async def test_middleware_processes_tool_call_when_capability_is_not_present(
    tool_call_reactor_middleware: ToolCallReactorMiddleware,
    mock_tool_call_reactor: AsyncMock,
) -> None:
    """Test that the middleware processes the tool call when the bypass_tool_call_reactor capability is not present."""
    tool_call = ToolCall(
        id="call_123",
        function=FunctionCall(name="shell", arguments='{"command": "ls"}'),
        type="function",
    )
    message = ChatMessage(role="assistant", tool_calls=[tool_call])
    context = {"session_id": "test_session"}

    await tool_call_reactor_middleware.process(
        response=message, session_id="test_session", context=context
    )

    mock_tool_call_reactor.process_tool_call.assert_called_once()


@pytest.mark.asyncio
async def test_middleware_skips_already_processed_tool_calls(
    tool_call_reactor_middleware: ToolCallReactorMiddleware,
    mock_tool_call_reactor: AsyncMock,
) -> None:
    """Test that the middleware skips tool calls that have already been processed."""
    # Create a tool call that's already been processed
    tool_call = ToolCall(
        id="call_123",
        function=FunctionCall(name="shell", arguments='{"command": "ls"}'),
        type="function",
    )
    # Mark the tool call object as processed
    tool_call._already_processed = True

    message = ChatMessage(role="assistant", tool_calls=[tool_call])
    context = {"session_id": "test_session"}

    result = await tool_call_reactor_middleware.process(
        response=message, session_id="test_session", context=context
    )

    # Should not process the tool call
    mock_tool_call_reactor.process_tool_call.assert_not_called()
    # Should return the original response
    assert result is message


@pytest.mark.asyncio
async def test_middleware_processes_only_new_tool_calls(
    tool_call_reactor_middleware: ToolCallReactorMiddleware,
    mock_tool_call_reactor: AsyncMock,
) -> None:
    """Test that the middleware processes only new tool calls and skips processed ones."""
    # Create one processed and one new tool call
    processed_tool_call = ToolCall(
        id="call_123",
        function=FunctionCall(name="shell", arguments='{"command": "ls"}'),
        type="function",
    )
    processed_tool_call._already_processed = True

    new_tool_call = ToolCall(
        id="call_456",
        function=FunctionCall(name="readFile", arguments='{"path": "test.txt"}'),
        type="function",
    )

    message = ChatMessage(
        role="assistant", tool_calls=[processed_tool_call, new_tool_call]
    )
    context = {"session_id": "test_session"}

    await tool_call_reactor_middleware.process(
        response=message, session_id="test_session", context=context
    )

    # Should process only the new tool call
    mock_tool_call_reactor.process_tool_call.assert_called_once()
    call_args = mock_tool_call_reactor.process_tool_call.call_args[0][0]
    assert call_args.tool_name == "readFile"


@pytest.mark.asyncio
async def test_middleware_marks_tool_calls_as_processed(
    tool_call_reactor_middleware: ToolCallReactorMiddleware,
    mock_tool_call_reactor: AsyncMock,
) -> None:
    """Test that the middleware marks tool calls as processed after execution."""
    tool_call = ToolCall(
        id="call_123",
        function=FunctionCall(name="shell", arguments='{"command": "ls"}'),
        type="function",
    )

    message = ChatMessage(role="assistant", tool_calls=[tool_call])
    context = {"session_id": "test_session"}

    await tool_call_reactor_middleware.process(
        response=message, session_id="test_session", context=context
    )

    # Tool call should be marked as processed
    assert getattr(message.tool_calls[0], "_already_processed", False) is True


@pytest.mark.asyncio
async def test_middleware_marks_tool_calls_as_processed_even_on_error(
    tool_call_reactor_middleware: ToolCallReactorMiddleware,
    mock_tool_call_reactor: AsyncMock,
) -> None:
    """Test that the middleware marks tool calls as processed even when reactor raises an error."""
    # Make the reactor raise an error
    mock_tool_call_reactor.process_tool_call.side_effect = Exception("Test error")

    tool_call = ToolCall(
        id="call_123",
        function=FunctionCall(name="shell", arguments='{"command": "ls"}'),
        type="function",
    )

    message = ChatMessage(role="assistant", tool_calls=[tool_call])
    context = {"session_id": "test_session"}

    # Should not raise the exception
    result = await tool_call_reactor_middleware.process(
        response=message, session_id="test_session", context=context
    )

    # Tool call should still be marked as processed to avoid retry loops
    assert getattr(message.tool_calls[0], "_already_processed", False) is True
    # Should return the original response
    assert result is message


@pytest.mark.asyncio
async def test_middleware_no_duplicate_reactor_executions(
    tool_call_reactor_middleware: ToolCallReactorMiddleware,
    mock_tool_call_reactor: AsyncMock,
) -> None:
    """Test that reactors are not executed multiple times for the same tool call."""
    tool_call = ToolCall(
        id="call_123",
        function=FunctionCall(name="shell", arguments='{"command": "ls"}'),
        type="function",
    )

    message = ChatMessage(role="assistant", tool_calls=[tool_call])
    context = {"session_id": "test_session"}

    # Process the message twice
    await tool_call_reactor_middleware.process(
        response=message, session_id="test_session", context=context
    )
    await tool_call_reactor_middleware.process(
        response=message, session_id="test_session", context=context
    )

    # Reactor should only be called once
    mock_tool_call_reactor.process_tool_call.assert_called_once()
