import asyncio

import pytest
from src.core.app.application_builder import ApplicationBuilder
from src.core.config.app_config import AppConfig
from src.core.services.tool_call_reactor_middleware import ToolCallReactorMiddleware


@pytest.mark.asyncio
async def test_tool_call_reactor_handlers_are_wired_up(
    app_config_legacy_log_disabled: AppConfig,
):
    """
    Integration test to ensure that all default tool call reactor handlers
    are correctly registered in the dependency injection container.
    """
    # Arrange
    config = app_config_legacy_log_disabled
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
    assert "unified_steering_handler" in registered_handlers
    assert "unified_tool_security_handler" in registered_handlers
    # Legacy handler should NOT be present when unified is active (default)
    assert "config_steering_handler" not in registered_handlers
    assert "unified_tool_security_handler" in registered_handlers
    assert "pytest_compression_handler" in registered_handlers

    # Assert that emit_legacy_log_enabled is correctly passed through
    from src.services.steering import UnifiedSteeringHandler

    unified_handler = service_provider.get_required_service(UnifiedSteeringHandler)
    assert unified_handler._emit_legacy_log_enabled is False

    # Also test the service directly
    from src.core.services.tool_call_reactor_service import ToolCallReactorService

    reactor_service = service_provider.get_required_service(ToolCallReactorService)
    service_handlers = reactor_service.get_registered_handlers()

    # Same assertions for the service directly
    assert "unified_steering_handler" in service_handlers
    assert "unified_tool_security_handler" in service_handlers
    assert "config_steering_handler" not in service_handlers
    assert "unified_tool_security_handler" in service_handlers
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
    from unittest.mock import AsyncMock, patch

    from src.core.domain.chat import ChatMessage, FunctionCall, ToolCall
    from src.core.interfaces.response_processor_interface import ProcessedResponse

    # Arrange
    config = AppConfig()
    builder = ApplicationBuilder().add_default_stages()
    app = await builder.build(config)
    await asyncio.sleep(0.1)
    service_provider = app.state.service_provider
    reactor_middleware = service_provider.get_required_service(
        ToolCallReactorMiddleware
    )

    # Create a tool call that will be processed first time
    processed_tool_call = ToolCall(
        id="call_old",
        function=FunctionCall(name="shell", arguments='{"command": "ls"}'),
        type="function",
    )

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

    # Mock the orchestrator's reactor to track calls
    mock_process = AsyncMock()
    with patch.object(
        reactor_middleware._orchestrator._reactor, "process_tool_call", mock_process
    ):
        # Act - Process the message
        result = await reactor_middleware.process(
            response=message, session_id="test_session", context=context
        )

        # Assert - Both tool calls should be processed (first time)
        assert mock_process.call_count == 2

        # Reset mock for second call
        mock_process.reset_mock()

        # Act - Process the same message again
        result2 = await reactor_middleware.process(
            response=message, session_id="test_session", context=context
        )

        # Assert - No new tool calls should be processed (deduplication)
        assert mock_process.call_count == 0

    # Assert - Results should be ProcessedResponse instances
    assert isinstance(result, ProcessedResponse)
    assert isinstance(result2, ProcessedResponse)
    # Content should be equivalent to original message
    assert result.content == message


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

    # Mock the orchestrator's reactor process_tool_call method to track calls
    mock_process = AsyncMock()
    with patch.object(
        reactor_middleware._orchestrator._reactor, "process_tool_call", mock_process
    ):
        # Act - Process the message twice
        await reactor_middleware.process(
            response=message, session_id="test_session", context=context
        )
        await reactor_middleware.process(
            response=message, session_id="test_session", context=context
        )

        # Assert - Reactor should only be called once (deduplication prevents second call)
        assert mock_process.call_count == 1


@pytest.mark.asyncio
@pytest.mark.integration
async def test_all_reactor_handlers_work_with_filtering():
    """
    Integration test to verify that all registered reactor handlers
    work correctly with the tool call filtering logic.
    """
    from unittest.mock import AsyncMock, patch

    from src.core.domain.chat import ChatMessage, FunctionCall, ToolCall
    from src.core.interfaces.response_processor_interface import ProcessedResponse

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

    # Mock the orchestrator's reactor to track calls
    mock_process = AsyncMock()
    with patch.object(
        reactor_middleware._orchestrator._reactor, "process_tool_call", mock_process
    ):
        # Act - Process the message
        result = await reactor_middleware.process(
            response=message, session_id="test_session", context=context
        )

        # Assert - Tool call should be processed (reactor called once)
        assert mock_process.call_count == 1
        # Result should be ProcessedResponse (not swallowed)
        assert isinstance(result, ProcessedResponse)
        assert result.content == message

        # Reset mock for second call
        mock_process.reset_mock()

        # Act - Process again with the same message
        result2 = await reactor_middleware.process(
            response=message, session_id="test_session", context=context
        )

        # Assert - Tool call should NOT be processed again (deduplication)
        assert mock_process.call_count == 0
        # Should still work and return ProcessedResponse
        assert isinstance(result2, ProcessedResponse)
        assert result2.content == message


@pytest.mark.asyncio
@pytest.mark.integration
async def test_droid_path_fix_handler_wires_when_enabled():
    """
    The DroidPathFixHandler should be registered when the feature flag
    is enabled in configuration.
    """
    # Arrange
    config = AppConfig.model_validate(
        {
            "session": {
                "droid_path_fix_enabled": True,
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
async def test_droid_path_fix_handler_not_wired_when_disabled():
    """
    The DroidPathFixHandler should NOT be registered when the feature flag
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


@pytest.mark.asyncio
async def test_unified_steering_policy_priority_overrides():
    """
    Integration test to ensure unified steering policy priorities can be overridden
    via configuration and are correctly applied.
    """
    # Arrange: Define policies with default priorities
    # InlinePythonPolicy has priority 80
    # BinaryFileEditPolicy has priority 90 (default)
    # ConfiguredRulesPolicy has priority 90
    # PytestFullSuitePolicy has priority 70
    # We want to override them such that InlinePythonPolicy runs first (highest priority)
    config = AppConfig.model_validate(
        {
            "session": {
                "tool_call_reactor": {
                    "unified_steering_enabled": True,
                    "steering_policy_priorities": {
                        "inline_python": 100,  # Override to make it highest
                        "configured_rules": 80,  # Override to make it lower than inline_python
                        "binary_file_edit": 75,  # Override to lower priority
                        "pytest_full_suite": 70,  # Keep default or override explicitly
                    },
                },
            }
        }
    )
    builder = ApplicationBuilder().add_default_stages()

    # Act
    app = await builder.build(config)
    await asyncio.sleep(0.1)  # Allow time for handlers to register
    service_provider = app.state.service_provider

    from src.services.steering import UnifiedSteeringHandler

    unified_handler = service_provider.get_required_service(UnifiedSteeringHandler)

    # Assert that policies are sorted by the overridden priorities
    policies = unified_handler._policies
    # We expect 4 policies: InlinePythonPolicy, ConfiguredRulesPolicy, BinaryFileEditPolicy, PytestFullSuitePolicy
    assert len(policies) == 4

    # Find the policies by name and check their order based on overridden priorities
    policy_names_in_order = [p.name for p in policies]

    # Expect InlinePythonPolicy to be first due to priority 100
    assert policy_names_in_order[0] == "inline_python"
    # Expect ConfiguredRulesPolicy to be second due to priority 80
    assert policy_names_in_order[1] == "configured_rules"
    # Expect BinaryFileEditPolicy to be third due to priority 75
    assert policy_names_in_order[2] == "binary_file_edit"
    # Expect PytestFullSuitePolicy to be fourth due to priority 70
    assert policy_names_in_order[3] == "pytest_full_suite"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_unified_steering_legacy_log_enabled(
    app_config_legacy_log_enabled: AppConfig,
):
    """
    Integration test to verify that emit_legacy_steering_log=True is correctly
    passed through to UnifiedSteeringHandler.
    """
    # Arrange
    config = app_config_legacy_log_enabled
    builder = ApplicationBuilder().add_default_stages()

    # Act
    app = await builder.build(config)
    await asyncio.sleep(0.1)
    service_provider = app.state.service_provider

    from src.services.steering import UnifiedSteeringHandler

    unified_handler = service_provider.get_required_service(UnifiedSteeringHandler)

    # Assert
    assert unified_handler._emit_legacy_log_enabled is True


@pytest.mark.asyncio
@pytest.mark.integration
async def test_unified_steering_emits_both_log_formats_when_legacy_enabled(
    app_config_legacy_log_enabled: AppConfig, caplog
):
    """
    Integration test to verify that when emit_legacy_steering_log=True,
    both the structured log and the legacy log are emitted on steering events.
    """
    import logging

    from src.core.domain.chat import ChatMessage, FunctionCall, ToolCall

    # Arrange
    config = app_config_legacy_log_enabled
    builder = ApplicationBuilder().add_default_stages()
    app = await builder.build(config)
    await asyncio.sleep(0.1)
    service_provider = app.state.service_provider

    reactor_middleware = service_provider.get_required_service(
        ToolCallReactorMiddleware
    )

    # Create a tool call that triggers inline python steering
    tool_call = ToolCall(
        id="call_legacy_test",
        function=FunctionCall(
            name="shell", arguments='{"command": "python -c \\"print(1)\\"" }'
        ),
        type="function",
    )

    message = ChatMessage(role="assistant", tool_calls=[tool_call])
    context = {"session_id": "test_legacy_log_session"}

    # Act - Process the message to trigger steering handler
    with caplog.at_level(logging.INFO):
        result = await reactor_middleware.process(
            response=message, session_id="test_legacy_log_session", context=context
        )

    # Assert - Verify tool call was processed (result should be ProcessedResponse)
    from src.core.interfaces.response_processor_interface import ProcessedResponse

    assert isinstance(result, ProcessedResponse)

    # Assert - check for structured log
    assert "Unified steering evaluation" in caplog.text

    # Assert - check for legacy log format
    assert "Steering via rule" in caplog.text
    assert "test_legacy_log_session" in caplog.text


@pytest.mark.asyncio
@pytest.mark.integration
async def test_unified_steering_emits_only_structured_log_when_legacy_disabled(
    app_config_legacy_log_disabled: AppConfig, caplog
):
    """
    Integration test to verify that when emit_legacy_steering_log=False,
    only the structured log is emitted (no legacy format).
    """
    import logging

    from src.core.domain.chat import ChatMessage, FunctionCall, ToolCall
    from src.core.interfaces.response_processor_interface import ProcessedResponse

    # Arrange
    config = app_config_legacy_log_disabled
    builder = ApplicationBuilder().add_default_stages()
    app = await builder.build(config)
    await asyncio.sleep(0.1)
    service_provider = app.state.service_provider

    reactor_middleware = service_provider.get_required_service(
        ToolCallReactorMiddleware
    )

    # Create a tool call that triggers inline python steering
    tool_call = ToolCall(
        id="call_structured_only_test",
        function=FunctionCall(
            name="shell", arguments='{"command": "python -c \\"print(1)\\"" }'
        ),
        type="function",
    )

    message = ChatMessage(role="assistant", tool_calls=[tool_call])
    context = {"session_id": "test_structured_log_session"}

    # Act - Process the message to trigger steering handler
    with caplog.at_level(logging.INFO):
        result = await reactor_middleware.process(
            response=message, session_id="test_structured_log_session", context=context
        )

    # Assert - Verify tool call was processed (result should be ProcessedResponse)
    assert isinstance(result, ProcessedResponse)

    # Assert - check for structured log
    assert "Unified steering evaluation" in caplog.text

    # Assert - legacy log should NOT be present
    assert "Steering via rule" not in caplog.text
