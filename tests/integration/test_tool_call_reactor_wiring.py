import asyncio

import pytest
from src.core.app.application_builder import ApplicationBuilder
from src.core.config.app_config import AppConfig
from src.core.services.tool_call_reactor_middleware import ToolCallReactorMiddleware


@pytest.mark.asyncio
async def test_tool_call_reactor_handlers_are_wired_up():
    """
    Integration test to ensure that all default tool call reactor handlers
    are correctly registered in the dependency injection container.
    """
    # Arrange
    config = AppConfig()
    builder = ApplicationBuilder().add_default_stages()

    # Act
    app = await builder.build(config)
    await asyncio.sleep(0.1)  # Allow time for handlers to register
    service_provider = app.state.service_provider
    reactor_middleware = service_provider.get_required_service(
        ToolCallReactorMiddleware
    )

    registered_handlers = reactor_middleware.get_registered_handlers()

    # Assert
    assert "config_steering_handler" in registered_handlers
    assert "dangerous_command_handler" in registered_handlers
    assert "pytest_compression_handler" in registered_handlers

    # Also test the service directly
    from src.core.services.tool_call_reactor_service import ToolCallReactorService

    reactor_service = service_provider.get_required_service(ToolCallReactorService)
    service_handlers = reactor_service.get_registered_handlers()
    assert "config_steering_handler" in service_handlers
    assert "dangerous_command_handler" in service_handlers
    assert "pytest_compression_handler" in service_handlers


@pytest.mark.asyncio
async def test_pytest_context_saving_handler_wires_when_enabled():
    """
    The pytest context saving handler should be registered when the feature flag
    is enabled in configuration.
    """
    # Arrange
    config = AppConfig.model_validate(
        {
            "session": {
                "tool_call_reactor": {"pytest_context_saving_enabled": True},
            }
        }
    )
    builder = ApplicationBuilder().add_default_stages()

    # Act
    app = await builder.build(config)
    await asyncio.sleep(0.1)
    service_provider = app.state.service_provider
    reactor_middleware = service_provider.get_required_service(
        ToolCallReactorMiddleware
    )

    registered_handlers = reactor_middleware.get_registered_handlers()

    # Assert
    assert "pytest_context_saving_handler" in registered_handlers


@pytest.mark.asyncio
@pytest.mark.integration
async def test_reactor_middleware_only_processes_new_tool_calls():
    """
    Integration test to verify that the reactor middleware only processes
    new tool calls and skips historical ones.
    """
    from src.core.domain.chat import ChatMessage, FunctionCall, ToolCall

    # Arrange
    config = AppConfig()
    builder = ApplicationBuilder().add_default_stages()
    app = await builder.build(config)
    await asyncio.sleep(0.1)
    service_provider = app.state.service_provider
    reactor_middleware = service_provider.get_required_service(
        ToolCallReactorMiddleware
    )

    # Create a tool call that's already been processed
    processed_tool_call = ToolCall(
        id="call_old",
        function=FunctionCall(name="shell", arguments='{"command": "ls"}'),
        type="function",
    )
    processed_tool_call._already_processed = True

    # Create a new tool call
    new_tool_call = ToolCall(
        id="call_new",
        function=FunctionCall(name="readFile", arguments='{"path": "test.txt"}'),
        type="function",
    )

    message = ChatMessage(
        role="assistant", tool_calls=[processed_tool_call, new_tool_call]
    )
    context = {"session_id": "test_session"}

    # Act
    result = await reactor_middleware.process(
        response=message, session_id="test_session", context=context
    )

    # Assert
    # The new tool call should be marked as processed
    assert getattr(new_tool_call, "_already_processed", False) is True
    # The processed tool call should still be marked as processed
    assert getattr(processed_tool_call, "_already_processed", False) is True
    # Result should be the original message
    assert result is message


@pytest.mark.asyncio
@pytest.mark.integration
async def test_reactor_middleware_no_duplicate_executions_integration():
    """
    Integration test to verify that reactors are not executed multiple times
    for the same tool call in a real scenario.
    """
    from unittest.mock import AsyncMock, patch

    from src.core.domain.chat import ChatMessage, FunctionCall, ToolCall

    # Arrange
    config = AppConfig()
    builder = ApplicationBuilder().add_default_stages()
    app = await builder.build(config)
    await asyncio.sleep(0.1)
    service_provider = app.state.service_provider
    reactor_middleware = service_provider.get_required_service(
        ToolCallReactorMiddleware
    )

    # Create a tool call
    tool_call = ToolCall(
        id="call_123",
        function=FunctionCall(name="shell", arguments='{"command": "ls"}'),
        type="function",
    )

    message = ChatMessage(role="assistant", tool_calls=[tool_call])
    context = {"session_id": "test_session"}

    # Mock the reactor's process_tool_call method to track calls
    mock_process = AsyncMock()
    with patch.object(
        reactor_middleware._tool_call_reactor, "process_tool_call", mock_process
    ):
        # Act - Process the message twice
        await reactor_middleware.process(
            response=message, session_id="test_session", context=context
        )
        await reactor_middleware.process(
            response=message, session_id="test_session", context=context
        )

        # Assert - Reactor should only be called once
        assert mock_process.call_count == 1


@pytest.mark.asyncio
@pytest.mark.integration
async def test_all_reactor_handlers_work_with_filtering():
    """
    Integration test to verify that all registered reactor handlers
    work correctly with the tool call filtering logic.
    """
    from src.core.domain.chat import ChatMessage, FunctionCall, ToolCall

    # Arrange
    config = AppConfig()
    builder = ApplicationBuilder().add_default_stages()
    app = await builder.build(config)
    await asyncio.sleep(0.1)
    service_provider = app.state.service_provider
    reactor_middleware = service_provider.get_required_service(
        ToolCallReactorMiddleware
    )

    # Get all registered handlers
    registered_handlers = reactor_middleware.get_registered_handlers()
    assert len(registered_handlers) > 0, "No handlers registered"

    # Test with a generic tool call that shouldn't trigger specific handlers
    tool_call = ToolCall(
        id="call_test",
        function=FunctionCall(name="generic_tool", arguments='{"param": "value"}'),
        type="function",
    )

    message = ChatMessage(role="assistant", tool_calls=[tool_call])
    context = {"session_id": "test_session"}

    # Act - Process the message
    result = await reactor_middleware.process(
        response=message, session_id="test_session", context=context
    )

    # Assert - Tool call should be marked as processed
    assert getattr(tool_call, "_already_processed", False) is True
    # Result should be returned (not swallowed)
    assert result is message

    # Act - Process again with the same message
    result2 = await reactor_middleware.process(
        response=message, session_id="test_session", context=context
    )

    # Assert - Should still work and return the message
    assert result2 is message


@pytest.mark.asyncio
@pytest.mark.integration
async def test_droid_antigravity_path_fix_handler_wires_when_enabled():
    """
    The DroidAntigravityPathFixHandler should be registered when the feature flag
    is enabled in configuration.
    """
    # Arrange
    config = AppConfig.model_validate(
        {
            "session": {
                "droid_antigravity_path_fix_enabled": True,
            }
        }
    )
    builder = ApplicationBuilder().add_default_stages()

    # Act
    app = await builder.build(config)
    await asyncio.sleep(0.1)
    service_provider = app.state.service_provider
    reactor_middleware = service_provider.get_required_service(
        ToolCallReactorMiddleware
    )

    registered_handlers = reactor_middleware.get_registered_handlers()

    # Assert
    assert "droid_antigravity_path_fix_handler" in registered_handlers


@pytest.mark.asyncio
@pytest.mark.integration
async def test_droid_antigravity_path_fix_handler_not_wired_when_disabled():
    """
    The DroidAntigravityPathFixHandler should NOT be registered when the feature flag
    is disabled (default).
    """
    # Arrange
    config = AppConfig()
    builder = ApplicationBuilder().add_default_stages()

    # Act
    app = await builder.build(config)
    await asyncio.sleep(0.1)
    service_provider = app.state.service_provider
    reactor_middleware = service_provider.get_required_service(
        ToolCallReactorMiddleware
    )

    registered_handlers = reactor_middleware.get_registered_handlers()

    # Assert
    assert "droid_antigravity_path_fix_handler" not in registered_handlers
