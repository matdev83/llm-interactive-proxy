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
