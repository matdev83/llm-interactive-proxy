"""Integration tests for test execution reminder handler registration."""

from datetime import datetime

import pytest
from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection
from src.core.di.services import register_core_services
from src.core.interfaces.tool_call_reactor_interface import (
    ToolCallContext,
)
from src.core.services.tool_call_reactor_service import ToolCallReactorService


@pytest.mark.asyncio
async def test_handler_registration_when_enabled():
    """Test that handler is registered when feature is enabled."""
    # Create config with feature enabled using model_copy
    config = AppConfig().model_copy(update={"test_execution_reminder_enabled": True})

    # Create service collection and register services
    services = ServiceCollection()
    register_core_services(services, config)

    # Build service provider
    provider = services.build_service_provider()

    # Get reactor service
    reactor = provider.get_required_service(ToolCallReactorService)

    # Verify handler is registered
    handlers = reactor.get_registered_handlers()
    assert (
        "test_execution_reminder_handler" in handlers
    ), "TestExecutionReminderHandler should be registered when enabled"


@pytest.mark.asyncio
async def test_handler_not_registered_when_disabled():
    """Test that handler is not registered when feature is disabled."""
    # Create config with feature disabled (default)
    config = AppConfig().model_copy(update={"test_execution_reminder_enabled": False})

    # Create service collection and register services
    services = ServiceCollection()
    register_core_services(services, config)

    # Build service provider
    provider = services.build_service_provider()

    # Get reactor service
    reactor = provider.get_required_service(ToolCallReactorService)

    # Verify handler is not registered
    handlers = reactor.get_registered_handlers()
    assert (
        "test_execution_reminder_handler" not in handlers
    ), "TestExecutionReminderHandler should not be registered when disabled"


@pytest.mark.asyncio
async def test_handler_priority_is_correct():
    """Test that handler has correct priority (90)."""
    # Create config with feature enabled
    config = AppConfig().model_copy(update={"test_execution_reminder_enabled": True})

    # Create service collection and register services
    services = ServiceCollection()
    register_core_services(services, config)

    # Build service provider
    provider = services.build_service_provider()

    # Get reactor service
    reactor = provider.get_required_service(ToolCallReactorService)

    # Get the handler
    handler = reactor._handlers.get("test_execution_reminder_handler")
    assert handler is not None, "Handler should be registered"
    assert handler.priority == 90, "Handler priority should be 90"


@pytest.mark.asyncio
async def test_handler_does_not_interfere_with_other_handlers():
    """Test that handler registration doesn't interfere with other handlers."""
    # Create config with feature enabled
    config = AppConfig().model_copy(update={"test_execution_reminder_enabled": True})

    # Create service collection and register services
    services = ServiceCollection()
    register_core_services(services, config)

    # Build service provider
    provider = services.build_service_provider()

    # Get reactor service
    reactor = provider.get_required_service(ToolCallReactorService)

    # Verify handler is registered
    handlers = reactor.get_registered_handlers()
    assert (
        "test_execution_reminder_handler" in handlers
    ), "TestExecutionReminderHandler should be registered"

    # Note: dangerous_command_handler is registered by default when enabled in config
    # We're just verifying our handler doesn't break the registration system


@pytest.mark.asyncio
async def test_custom_message_configuration():
    """Test that custom message is passed to handler."""
    # Create config with custom message
    config = AppConfig().model_copy(
        update={
            "test_execution_reminder_enabled": True,
            "test_execution_reminder_message": "Custom test reminder message",
        }
    )

    # Create service collection and register services
    services = ServiceCollection()
    register_core_services(services, config)

    # Build service provider
    provider = services.build_service_provider()

    # Get reactor service
    reactor = provider.get_required_service(ToolCallReactorService)

    # Get the handler
    handler = reactor._handlers.get("test_execution_reminder_handler")
    assert handler is not None, "Handler should be registered"
    assert (
        handler._message == "Custom test reminder message"
    ), "Handler should use custom message from config"


# End-to-end flow tests


@pytest.mark.asyncio
async def test_end_to_end_modify_test_complete_flow():
    """Test complete flow: modify file -> run test -> complete task."""
    # Create config with feature enabled
    config = AppConfig().model_copy(update={"test_execution_reminder_enabled": True})

    # Create service collection and register services
    services = ServiceCollection()
    register_core_services(services, config)

    # Build service provider
    provider = services.build_service_provider()

    # Get reactor service
    reactor = provider.get_required_service(ToolCallReactorService)

    session_id = "test-session-e2e"

    # Step 1: Modify a file (should mark session dirty)
    modify_context = ToolCallContext(
        session_id=session_id,
        backend_name="test-backend",
        model_name="test-model",
        full_response={},
        tool_name="write_file",
        tool_arguments={"path": "test.py", "content": "print('hello')"},
        timestamp=datetime.now(),
    )

    result = await reactor.process_tool_call(modify_context)
    assert result is None, "File modification should not be swallowed"

    # Step 2: Try to complete without running tests (should be swallowed)
    complete_context_dirty = ToolCallContext(
        session_id=session_id,
        backend_name="test-backend",
        model_name="test-model",
        full_response={"content": "Task is complete and ready for review"},
        tool_name="task_complete",
        tool_arguments={},
        timestamp=datetime.now(),
    )

    result = await reactor.process_tool_call(complete_context_dirty)
    assert result is not None, "Completion in dirty state should be swallowed"
    assert result.should_swallow is True
    assert "test" in result.replacement_response.lower()

    # Step 3: Run tests (should mark session clean)
    test_context = ToolCallContext(
        session_id=session_id,
        backend_name="test-backend",
        model_name="test-model",
        full_response={},
        tool_name="bash",
        tool_arguments={"command": "pytest tests/"},
        timestamp=datetime.now(),
    )

    result = await reactor.process_tool_call(test_context)
    assert result is None, "Test execution should not be swallowed"

    # Step 4: Try to complete after running tests (should succeed)
    complete_context_clean = ToolCallContext(
        session_id=session_id,
        backend_name="test-backend",
        model_name="test-model",
        full_response={"content": "Task is complete and ready for review"},
        tool_name="task_complete",
        tool_arguments={},
        timestamp=datetime.now(),
    )

    result = await reactor.process_tool_call(complete_context_clean)
    assert result is None, "Completion in clean state should not be swallowed"


@pytest.mark.asyncio
async def test_end_to_end_modify_complete_without_test():
    """Test flow: modify file -> complete (should be blocked)."""
    # Create config with feature enabled
    config = AppConfig().model_copy(update={"test_execution_reminder_enabled": True})

    # Create service collection and register services
    services = ServiceCollection()
    register_core_services(services, config)

    # Build service provider
    provider = services.build_service_provider()

    # Get reactor service
    reactor = provider.get_required_service(ToolCallReactorService)

    session_id = "test-session-no-test"

    # Step 1: Modify a file
    modify_context = ToolCallContext(
        session_id=session_id,
        backend_name="test-backend",
        model_name="test-model",
        full_response={},
        tool_name="str_replace",
        tool_arguments={"path": "test.py", "old": "foo", "new": "bar"},
        timestamp=datetime.now(),
    )

    result = await reactor.process_tool_call(modify_context)
    assert result is None

    # Step 2: Try to complete without running tests
    complete_context = ToolCallContext(
        session_id=session_id,
        backend_name="test-backend",
        model_name="test-model",
        full_response={"content": "Implementation is finished"},
        tool_name="done",
        tool_arguments={},
        timestamp=datetime.now(),
    )

    result = await reactor.process_tool_call(complete_context)
    assert result is not None
    assert result.should_swallow is True
    assert "test" in result.replacement_response.lower()


@pytest.mark.asyncio
async def test_end_to_end_complete_without_modification():
    """Test flow: complete without any modification (should succeed)."""
    # Create config with feature enabled
    config = AppConfig().model_copy(update={"test_execution_reminder_enabled": True})

    # Create service collection and register services
    services = ServiceCollection()
    register_core_services(services, config)

    # Build service provider
    provider = services.build_service_provider()

    # Get reactor service
    reactor = provider.get_required_service(ToolCallReactorService)

    session_id = "test-session-no-mod"

    # Try to complete without any modifications
    complete_context = ToolCallContext(
        session_id=session_id,
        backend_name="test-backend",
        model_name="test-model",
        full_response={"content": "Task complete"},
        tool_name="task_complete",
        tool_arguments={},
        timestamp=datetime.now(),
    )

    result = await reactor.process_tool_call(complete_context)
    assert result is None, "Completion in clean state should not be swallowed"


# Multi-session tests


@pytest.mark.asyncio
async def test_multi_session_isolation():
    """Test that multiple sessions maintain independent state."""
    # Create config with feature enabled
    config = AppConfig().model_copy(update={"test_execution_reminder_enabled": True})

    # Create service collection and register services
    services = ServiceCollection()
    register_core_services(services, config)

    # Build service provider
    provider = services.build_service_provider()

    # Get reactor service
    reactor = provider.get_required_service(ToolCallReactorService)

    session1 = "session-1"
    session2 = "session-2"

    # Session 1: Modify file
    modify_context_1 = ToolCallContext(
        session_id=session1,
        backend_name="test-backend",
        model_name="test-model",
        full_response={},
        tool_name="write_file",
        tool_arguments={"path": "test1.py", "content": "code1"},
        timestamp=datetime.now(),
    )

    await reactor.process_tool_call(modify_context_1)

    # Session 2: Don't modify anything

    # Session 1: Try to complete (should be blocked)
    complete_context_1 = ToolCallContext(
        session_id=session1,
        backend_name="test-backend",
        model_name="test-model",
        full_response={"content": "Task complete"},
        tool_name="task_complete",
        tool_arguments={},
        timestamp=datetime.now(),
    )

    result1 = await reactor.process_tool_call(complete_context_1)
    assert result1 is not None, "Session 1 should be blocked (dirty)"
    assert result1.should_swallow is True

    # Session 2: Try to complete (should succeed)
    complete_context_2 = ToolCallContext(
        session_id=session2,
        backend_name="test-backend",
        model_name="test-model",
        full_response={"content": "Task complete"},
        tool_name="task_complete",
        tool_arguments={},
        timestamp=datetime.now(),
    )

    result2 = await reactor.process_tool_call(complete_context_2)
    assert result2 is None, "Session 2 should not be blocked (clean)"


@pytest.mark.asyncio
async def test_multi_session_concurrent_operations():
    """Test concurrent operations across multiple sessions."""
    # Create config with feature enabled
    config = AppConfig().model_copy(update={"test_execution_reminder_enabled": True})

    # Create service collection and register services
    services = ServiceCollection()
    register_core_services(services, config)

    # Build service provider
    provider = services.build_service_provider()

    # Get reactor service
    reactor = provider.get_required_service(ToolCallReactorService)

    # Create 3 sessions with different states
    sessions = ["session-a", "session-b", "session-c"]

    # Session A: Modify and test (clean)
    await reactor.process_tool_call(
        ToolCallContext(
            session_id=sessions[0],
            backend_name="test-backend",
            model_name="test-model",
            full_response={},
            tool_name="write_file",
            tool_arguments={"path": "a.py", "content": "a"},
            timestamp=datetime.now(),
        )
    )
    await reactor.process_tool_call(
        ToolCallContext(
            session_id=sessions[0],
            backend_name="test-backend",
            model_name="test-model",
            full_response={},
            tool_name="bash",
            tool_arguments={"command": "pytest"},
            timestamp=datetime.now(),
        )
    )

    # Session B: Modify only (dirty)
    await reactor.process_tool_call(
        ToolCallContext(
            session_id=sessions[1],
            backend_name="test-backend",
            model_name="test-model",
            full_response={},
            tool_name="str_replace",
            tool_arguments={"path": "b.py", "old": "x", "new": "y"},
            timestamp=datetime.now(),
        )
    )

    # Session C: No modifications (clean)

    # Try to complete all sessions
    results = []
    for session_id in sessions:
        result = await reactor.process_tool_call(
            ToolCallContext(
                session_id=session_id,
                backend_name="test-backend",
                model_name="test-model",
                full_response={"content": "Task complete"},
                tool_name="task_complete",
                tool_arguments={},
                timestamp=datetime.now(),
            )
        )
        results.append(result)

    # Verify results
    assert results[0] is None, "Session A should succeed (clean after test)"
    assert results[1] is not None, "Session B should be blocked (dirty)"
    assert results[1].should_swallow is True
    assert results[2] is None, "Session C should succeed (never modified)"


# Configuration precedence tests


@pytest.mark.asyncio
async def test_configuration_with_default_message():
    """Test that default message is used when no custom message provided."""
    # Create config without custom message
    config = AppConfig().model_copy(update={"test_execution_reminder_enabled": True})

    # Create service collection and register services
    services = ServiceCollection()
    register_core_services(services, config)

    # Build service provider
    provider = services.build_service_provider()

    # Get reactor service
    reactor = provider.get_required_service(ToolCallReactorService)

    # Get the handler
    handler = reactor._handlers.get("test_execution_reminder_handler")
    assert handler is not None

    # Verify default message is used
    assert "code changes" in handler._message.lower()
    assert "test" in handler._message.lower()


@pytest.mark.asyncio
async def test_configuration_with_custom_message_in_response():
    """Test that custom message appears in steering response."""
    custom_msg = "CUSTOM: Please run your tests before finishing!"

    # Create config with custom message
    config = AppConfig().model_copy(
        update={
            "test_execution_reminder_enabled": True,
            "test_execution_reminder_message": custom_msg,
        }
    )

    # Create service collection and register services
    services = ServiceCollection()
    register_core_services(services, config)

    # Build service provider
    provider = services.build_service_provider()

    # Get reactor service
    reactor = provider.get_required_service(ToolCallReactorService)

    session_id = "test-custom-msg"

    # Modify file
    await reactor.process_tool_call(
        ToolCallContext(
            session_id=session_id,
            backend_name="test-backend",
            model_name="test-model",
            full_response={},
            tool_name="write_file",
            tool_arguments={"path": "test.py", "content": "code"},
            timestamp=datetime.now(),
        )
    )

    # Try to complete
    result = await reactor.process_tool_call(
        ToolCallContext(
            session_id=session_id,
            backend_name="test-backend",
            model_name="test-model",
            full_response={"content": "Done"},
            tool_name="task_complete",
            tool_arguments={},
            timestamp=datetime.now(),
        )
    )

    assert result is not None
    assert result.should_swallow is True
    assert result.replacement_response == custom_msg


# Handler interference tests


@pytest.mark.asyncio
async def test_handler_order_with_multiple_handlers():
    """Test that handler is called in correct priority order."""
    # Create config with feature enabled
    config = AppConfig().model_copy(update={"test_execution_reminder_enabled": True})

    # Create service collection and register services
    services = ServiceCollection()
    register_core_services(services, config)

    # Build service provider
    provider = services.build_service_provider()

    # Get reactor service
    reactor = provider.get_required_service(ToolCallReactorService)

    # Get all handlers
    handlers = reactor.get_registered_handlers()

    # Verify our handler is registered
    assert "test_execution_reminder_handler" in handlers

    # Get handler priorities
    handler_priorities = []
    for handler_name in handlers:
        handler = reactor._handlers.get(handler_name)
        if handler:
            handler_priorities.append((handler_name, handler.priority))

    # Sort by priority (descending)
    handler_priorities.sort(key=lambda x: x[1], reverse=True)

    # Find our handler's position
    our_handler_pos = next(
        i
        for i, (name, _) in enumerate(handler_priorities)
        if name == "test_execution_reminder_handler"
    )

    # Verify priority is 90
    assert handler_priorities[our_handler_pos][1] == 90


@pytest.mark.asyncio
async def test_handler_does_not_swallow_non_completion_tools():
    """Test that handler only swallows completion signals, not other tools."""
    # Create config with feature enabled
    config = AppConfig().model_copy(update={"test_execution_reminder_enabled": True})

    # Create service collection and register services
    services = ServiceCollection()
    register_core_services(services, config)

    # Build service provider
    provider = services.build_service_provider()

    # Get reactor service
    reactor = provider.get_required_service(ToolCallReactorService)

    session_id = "test-no-swallow"

    # Modify file to make session dirty
    await reactor.process_tool_call(
        ToolCallContext(
            session_id=session_id,
            backend_name="test-backend",
            model_name="test-model",
            full_response={},
            tool_name="write_file",
            tool_arguments={"path": "test.py", "content": "code"},
            timestamp=datetime.now(),
        )
    )

    # Try various non-completion tools (should all pass through)
    non_completion_tools = [
        ("read_file", {"path": "test.py"}),
        ("list_directory", {"path": "."}),
        ("bash", {"command": "ls"}),
        ("search", {"query": "test"}),
    ]

    for tool_name, tool_args in non_completion_tools:
        result = await reactor.process_tool_call(
            ToolCallContext(
                session_id=session_id,
                backend_name="test-backend",
                model_name="test-model",
                full_response={},
                tool_name=tool_name,
                tool_arguments=tool_args,
                timestamp=datetime.now(),
            )
        )
        assert result is None, f"Tool {tool_name} should not be swallowed"


# Tests with attempt_completion tool (Cline/Roo-Code)


@pytest.mark.asyncio
async def test_attempt_completion_tool_in_dirty_state():
    """Test that attempt_completion tool is detected and blocked in dirty state."""
    # Create config with feature enabled
    config = AppConfig().model_copy(update={"test_execution_reminder_enabled": True})

    # Create service collection and register services
    services = ServiceCollection()
    register_core_services(services, config)

    # Build service provider
    provider = services.build_service_provider()

    # Get reactor service
    reactor = provider.get_required_service(ToolCallReactorService)

    session_id = "test-attempt-completion-dirty"

    # Modify file to make session dirty
    await reactor.process_tool_call(
        ToolCallContext(
            session_id=session_id,
            backend_name="test-backend",
            model_name="test-model",
            full_response={},
            tool_name="write_file",
            tool_arguments={"path": "test.py", "content": "code"},
            timestamp=datetime.now(),
        )
    )

    # Try to complete with attempt_completion tool (should be blocked)
    result = await reactor.process_tool_call(
        ToolCallContext(
            session_id=session_id,
            backend_name="test-backend",
            model_name="test-model",
            full_response={},
            tool_name="attempt_completion",
            tool_arguments={"result": "Task completed successfully"},
            timestamp=datetime.now(),
        )
    )

    assert result is not None, "attempt_completion should be blocked in dirty state"
    assert result.should_swallow is True
    assert "test" in result.replacement_response.lower()


@pytest.mark.asyncio
async def test_attempt_completion_tool_in_clean_state():
    """Test that attempt_completion tool is allowed in clean state."""
    # Create config with feature enabled
    config = AppConfig().model_copy(update={"test_execution_reminder_enabled": True})

    # Create service collection and register services
    services = ServiceCollection()
    register_core_services(services, config)

    # Build service provider
    provider = services.build_service_provider()

    # Get reactor service
    reactor = provider.get_required_service(ToolCallReactorService)

    session_id = "test-attempt-completion-clean"

    # Modify file
    await reactor.process_tool_call(
        ToolCallContext(
            session_id=session_id,
            backend_name="test-backend",
            model_name="test-model",
            full_response={},
            tool_name="write_file",
            tool_arguments={"path": "test.py", "content": "code"},
            timestamp=datetime.now(),
        )
    )

    # Run tests to make session clean
    await reactor.process_tool_call(
        ToolCallContext(
            session_id=session_id,
            backend_name="test-backend",
            model_name="test-model",
            full_response={},
            tool_name="bash",
            tool_arguments={"command": "pytest"},
            timestamp=datetime.now(),
        )
    )

    # Try to complete with attempt_completion tool (should succeed)
    result = await reactor.process_tool_call(
        ToolCallContext(
            session_id=session_id,
            backend_name="test-backend",
            model_name="test-model",
            full_response={},
            tool_name="attempt_completion",
            tool_arguments={"result": "Task completed successfully"},
            timestamp=datetime.now(),
        )
    )

    assert result is None, "attempt_completion should be allowed in clean state"


@pytest.mark.asyncio
async def test_attempt_completion_without_modification():
    """Test that attempt_completion is allowed when no modifications were made."""
    # Create config with feature enabled
    config = AppConfig().model_copy(update={"test_execution_reminder_enabled": True})

    # Create service collection and register services
    services = ServiceCollection()
    register_core_services(services, config)

    # Build service provider
    provider = services.build_service_provider()

    # Get reactor service
    reactor = provider.get_required_service(ToolCallReactorService)

    session_id = "test-attempt-completion-no-mod"

    # Try to complete without any modifications (should succeed)
    result = await reactor.process_tool_call(
        ToolCallContext(
            session_id=session_id,
            backend_name="test-backend",
            model_name="test-model",
            full_response={},
            tool_name="attempt_completion",
            tool_arguments={"result": "Task completed successfully"},
            timestamp=datetime.now(),
        )
    )

    assert result is None, "attempt_completion should be allowed without modifications"


# Tests with finish_reason in responses


@pytest.mark.asyncio
async def test_finish_reason_stop_in_dirty_state():
    """Test that finish_reason='stop' is NOT blocked (legacy behavior removed per Requirement 7.6).

    Note: finish_reason detection was moved to EoS events. Tool calls with finish_reason
    are no longer blocked directly. Reminders are now logged when EoS events occur for
    dirty sessions via TestExecutionReminderEosSubscriber.
    """
    # Create config with feature enabled
    config = AppConfig().model_copy(update={"test_execution_reminder_enabled": True})

    # Create service collection and register services
    services = ServiceCollection()
    register_core_services(services, config)

    # Build service provider
    provider = services.build_service_provider()

    # Get reactor service
    reactor = provider.get_required_service(ToolCallReactorService)

    session_id = "test-finish-reason-stop-dirty"

    # Modify file to make session dirty
    await reactor.process_tool_call(
        ToolCallContext(
            session_id=session_id,
            backend_name="test-backend",
            model_name="test-model",
            full_response={},
            tool_name="write_file",
            tool_arguments={"path": "test.py", "content": "code"},
            timestamp=datetime.now(),
        )
    )

    # Try to complete with finish_reason='stop' (should NOT be blocked - legacy behavior removed)
    result = await reactor.process_tool_call(
        ToolCallContext(
            session_id=session_id,
            backend_name="test-backend",
            model_name="test-model",
            full_response={"finish_reason": "stop", "content": "Task completed"},
            tool_name="some_tool",
            tool_arguments={},
            timestamp=datetime.now(),
        )
    )

    # finish_reason detection moved to EoS events, so tool calls are not blocked
    assert (
        result is None or result.should_swallow is False
    ), "finish_reason='stop' should NOT be blocked - detection moved to EoS events"


@pytest.mark.asyncio
async def test_finish_reason_in_choices_array():
    """Test that finish_reason in choices array is NOT blocked (legacy behavior removed per Requirement 7.6).

    Note: finish_reason detection was moved to EoS events. Tool calls with finish_reason
    are no longer blocked directly. Reminders are now logged when EoS events occur for
    dirty sessions via TestExecutionReminderEosSubscriber.
    """
    # Create config with feature enabled
    config = AppConfig().model_copy(update={"test_execution_reminder_enabled": True})

    # Create service collection and register services
    services = ServiceCollection()
    register_core_services(services, config)

    # Build service provider
    provider = services.build_service_provider()

    # Get reactor service
    reactor = provider.get_required_service(ToolCallReactorService)

    session_id = "test-finish-reason-choices"

    # Modify file to make session dirty
    await reactor.process_tool_call(
        ToolCallContext(
            session_id=session_id,
            backend_name="test-backend",
            model_name="test-model",
            full_response={},
            tool_name="write_file",
            tool_arguments={"path": "test.py", "content": "code"},
            timestamp=datetime.now(),
        )
    )

    # Try to complete with finish_reason in choices array (OpenAI format)
    result = await reactor.process_tool_call(
        ToolCallContext(
            session_id=session_id,
            backend_name="test-backend",
            model_name="test-model",
            full_response={
                "choices": [{"finish_reason": "stop", "message": {"content": "Done"}}]
            },
            tool_name="some_tool",
            tool_arguments={},
            timestamp=datetime.now(),
        )
    )

    # finish_reason detection moved to EoS events, so tool calls are not blocked
    assert (
        result is None or result.should_swallow is False
    ), "finish_reason in choices array should NOT be blocked - detection moved to EoS events"


@pytest.mark.asyncio
async def test_finish_reason_in_metadata():
    """Test that finish_reason in metadata is NOT blocked (legacy behavior removed per Requirement 7.6).

    Note: finish_reason detection was moved to EoS events. Tool calls with finish_reason
    are no longer blocked directly. Reminders are now logged when EoS events occur for
    dirty sessions via TestExecutionReminderEosSubscriber.
    """
    # Create config with feature enabled
    config = AppConfig().model_copy(update={"test_execution_reminder_enabled": True})

    # Create service collection and register services
    services = ServiceCollection()
    register_core_services(services, config)

    # Build service provider
    provider = services.build_service_provider()

    # Get reactor service
    reactor = provider.get_required_service(ToolCallReactorService)

    session_id = "test-finish-reason-metadata"

    # Modify file to make session dirty
    await reactor.process_tool_call(
        ToolCallContext(
            session_id=session_id,
            backend_name="test-backend",
            model_name="test-model",
            full_response={},
            tool_name="write_file",
            tool_arguments={"path": "test.py", "content": "code"},
            timestamp=datetime.now(),
        )
    )

    # Try to complete with finish_reason in metadata
    result = await reactor.process_tool_call(
        ToolCallContext(
            session_id=session_id,
            backend_name="test-backend",
            model_name="test-model",
            full_response={"metadata": {"finish_reason": "end_turn"}},
            tool_name="some_tool",
            tool_arguments={},
            timestamp=datetime.now(),
        )
    )

    # finish_reason detection moved to EoS events, so tool calls are not blocked
    assert (
        result is None or result.should_swallow is False
    ), "finish_reason in metadata should NOT be blocked - detection moved to EoS events"


@pytest.mark.asyncio
async def test_finish_reason_tool_calls():
    """Test that finish_reason='tool_calls' is NOT blocked (legacy behavior removed per Requirement 7.6).

    Note: finish_reason detection was moved to EoS events. Tool calls with finish_reason
    are no longer blocked directly. Reminders are now logged when EoS events occur for
    dirty sessions via TestExecutionReminderEosSubscriber.
    """
    # Create config with feature enabled
    config = AppConfig().model_copy(update={"test_execution_reminder_enabled": True})

    # Create service collection and register services
    services = ServiceCollection()
    register_core_services(services, config)

    # Build service provider
    provider = services.build_service_provider()

    # Get reactor service
    reactor = provider.get_required_service(ToolCallReactorService)

    session_id = "test-finish-reason-tool-calls"

    # Modify file to make session dirty
    await reactor.process_tool_call(
        ToolCallContext(
            session_id=session_id,
            backend_name="test-backend",
            model_name="test-model",
            full_response={},
            tool_name="write_file",
            tool_arguments={"path": "test.py", "content": "code"},
            timestamp=datetime.now(),
        )
    )

    # Try to complete with finish_reason='tool_calls'
    result = await reactor.process_tool_call(
        ToolCallContext(
            session_id=session_id,
            backend_name="test-backend",
            model_name="test-model",
            full_response={"finish_reason": "tool_calls"},
            tool_name="some_tool",
            tool_arguments={},
            timestamp=datetime.now(),
        )
    )

    # finish_reason detection moved to EoS events, so tool calls are not blocked
    assert (
        result is None or result.should_swallow is False
    ), "finish_reason='tool_calls' should NOT be blocked - detection moved to EoS events"


@pytest.mark.asyncio
async def test_finish_reason_length():
    """Test that finish_reason='length' is NOT blocked (legacy behavior removed per Requirement 7.6).

    Note: finish_reason detection was moved to EoS events. Tool calls with finish_reason
    are no longer blocked directly. Reminders are now logged when EoS events occur for
    dirty sessions via TestExecutionReminderEosSubscriber.
    """
    # Create config with feature enabled
    config = AppConfig().model_copy(update={"test_execution_reminder_enabled": True})

    # Create service collection and register services
    services = ServiceCollection()
    register_core_services(services, config)

    # Build service provider
    provider = services.build_service_provider()

    # Get reactor service
    reactor = provider.get_required_service(ToolCallReactorService)

    session_id = "test-finish-reason-length"

    # Modify file to make session dirty
    await reactor.process_tool_call(
        ToolCallContext(
            session_id=session_id,
            backend_name="test-backend",
            model_name="test-model",
            full_response={},
            tool_name="write_file",
            tool_arguments={"path": "test.py", "content": "code"},
            timestamp=datetime.now(),
        )
    )

    # Try to complete with finish_reason='length'
    result = await reactor.process_tool_call(
        ToolCallContext(
            session_id=session_id,
            backend_name="test-backend",
            model_name="test-model",
            full_response={"finish_reason": "length"},
            tool_name="some_tool",
            tool_arguments={},
            timestamp=datetime.now(),
        )
    )

    # finish_reason detection moved to EoS events, so tool calls are not blocked
    assert (
        result is None or result.should_swallow is False
    ), "finish_reason='length' should NOT be blocked - detection moved to EoS events"


@pytest.mark.asyncio
async def test_finish_reason_in_clean_state():
    """Test that finish_reason is allowed in clean state."""
    # Create config with feature enabled
    config = AppConfig().model_copy(update={"test_execution_reminder_enabled": True})

    # Create service collection and register services
    services = ServiceCollection()
    register_core_services(services, config)

    # Build service provider
    provider = services.build_service_provider()

    # Get reactor service
    reactor = provider.get_required_service(ToolCallReactorService)

    session_id = "test-finish-reason-clean"

    # Modify file
    await reactor.process_tool_call(
        ToolCallContext(
            session_id=session_id,
            backend_name="test-backend",
            model_name="test-model",
            full_response={},
            tool_name="write_file",
            tool_arguments={"path": "test.py", "content": "code"},
            timestamp=datetime.now(),
        )
    )

    # Run tests to make session clean
    await reactor.process_tool_call(
        ToolCallContext(
            session_id=session_id,
            backend_name="test-backend",
            model_name="test-model",
            full_response={},
            tool_name="bash",
            tool_arguments={"command": "pytest"},
            timestamp=datetime.now(),
        )
    )

    # Try to complete with finish_reason='stop' (should succeed)
    result = await reactor.process_tool_call(
        ToolCallContext(
            session_id=session_id,
            backend_name="test-backend",
            model_name="test-model",
            full_response={"finish_reason": "stop"},
            tool_name="some_tool",
            tool_arguments={},
            timestamp=datetime.now(),
        )
    )

    assert result is None, "finish_reason should be allowed in clean state"


# End-to-end flow with real agent tool names


@pytest.mark.asyncio
async def test_real_agent_flow_cline_attempt_completion():
    """Test end-to-end flow with Cline's attempt_completion tool."""
    # Create config with feature enabled
    config = AppConfig().model_copy(update={"test_execution_reminder_enabled": True})

    # Create service collection and register services
    services = ServiceCollection()
    register_core_services(services, config)

    # Build service provider
    provider = services.build_service_provider()

    # Get reactor service
    reactor = provider.get_required_service(ToolCallReactorService)

    session_id = "test-cline-flow"

    # Step 1: Agent modifies a file
    await reactor.process_tool_call(
        ToolCallContext(
            session_id=session_id,
            backend_name="anthropic",
            model_name="claude-3-5-sonnet-20241022",
            full_response={},
            tool_name="write_to_file",
            tool_arguments={"path": "src/main.py", "content": "def main(): pass"},
            timestamp=datetime.now(),
        )
    )

    # Step 2: Agent tries to complete without tests (should be blocked)
    result = await reactor.process_tool_call(
        ToolCallContext(
            session_id=session_id,
            backend_name="anthropic",
            model_name="claude-3-5-sonnet-20241022",
            full_response={},
            tool_name="attempt_completion",
            tool_arguments={
                "result": "I've implemented the main function as requested."
            },
            timestamp=datetime.now(),
        )
    )

    assert result is not None, "Cline's attempt_completion should be blocked"
    assert result.should_swallow is True
    assert "test" in result.replacement_response.lower()

    # Step 3: Agent runs tests
    await reactor.process_tool_call(
        ToolCallContext(
            session_id=session_id,
            backend_name="anthropic",
            model_name="claude-3-5-sonnet-20241022",
            full_response={},
            tool_name="execute_command",
            tool_arguments={"command": "python -m pytest tests/"},
            timestamp=datetime.now(),
        )
    )

    # Step 4: Agent tries to complete again (should succeed)
    result = await reactor.process_tool_call(
        ToolCallContext(
            session_id=session_id,
            backend_name="anthropic",
            model_name="claude-3-5-sonnet-20241022",
            full_response={},
            tool_name="attempt_completion",
            tool_arguments={"result": "Implementation complete and tests passing."},
            timestamp=datetime.now(),
        )
    )

    assert result is None, "attempt_completion should succeed after tests"


@pytest.mark.asyncio
async def test_real_agent_flow_with_finish_reason():
    """Test end-to-end flow with streaming finish_reason."""
    # Create config with feature enabled
    config = AppConfig().model_copy(update={"test_execution_reminder_enabled": True})

    # Create service collection and register services
    services = ServiceCollection()
    register_core_services(services, config)

    # Build service provider
    provider = services.build_service_provider()

    # Get reactor service
    reactor = provider.get_required_service(ToolCallReactorService)

    session_id = "test-finish-reason-flow"

    # Step 1: Agent modifies a file
    await reactor.process_tool_call(
        ToolCallContext(
            session_id=session_id,
            backend_name="openai",
            model_name="gpt-4",
            full_response={},
            tool_name="write_file",
            tool_arguments={"path": "app.js", "content": "console.log('hello');"},
            timestamp=datetime.now(),
        )
    )

    # Step 2: Streaming response ends with finish_reason='stop' (should NOT be blocked - legacy behavior removed)
    # Note: finish_reason detection was moved to EoS events per Requirement 7.6.
    # Reminders are now logged when EoS events occur for dirty sessions.
    result = await reactor.process_tool_call(
        ToolCallContext(
            session_id=session_id,
            backend_name="openai",
            model_name="gpt-4",
            full_response={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": "Changes implemented successfully."},
                    }
                ]
            },
            tool_name="assistant_response",
            tool_arguments={},
            timestamp=datetime.now(),
        )
    )

    # finish_reason detection moved to EoS events, so tool calls are not blocked
    assert (
        result is None or result.should_swallow is False
    ), "finish_reason='stop' should NOT be blocked - detection moved to EoS events"

    # Step 3: Agent runs tests
    await reactor.process_tool_call(
        ToolCallContext(
            session_id=session_id,
            backend_name="openai",
            model_name="gpt-4",
            full_response={},
            tool_name="bash",
            tool_arguments={"command": "npm test"},
            timestamp=datetime.now(),
        )
    )

    # Step 4: Streaming response ends again (should succeed)
    result = await reactor.process_tool_call(
        ToolCallContext(
            session_id=session_id,
            backend_name="openai",
            model_name="gpt-4",
            full_response={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": "All tests passing."},
                    }
                ]
            },
            tool_name="assistant_response",
            tool_arguments={},
            timestamp=datetime.now(),
        )
    )

    assert result is None, "finish_reason should succeed after tests"


@pytest.mark.asyncio
async def test_combined_tool_and_finish_reason_detection():
    """Test that both tool name and finish_reason can trigger detection."""
    # Create config with feature enabled
    config = AppConfig().model_copy(update={"test_execution_reminder_enabled": True})

    # Create service collection and register services
    services = ServiceCollection()
    register_core_services(services, config)

    # Build service provider
    provider = services.build_service_provider()

    # Get reactor service
    reactor = provider.get_required_service(ToolCallReactorService)

    session_id = "test-combined-detection"

    # Modify file to make session dirty
    await reactor.process_tool_call(
        ToolCallContext(
            session_id=session_id,
            backend_name="test-backend",
            model_name="test-model",
            full_response={},
            tool_name="write_file",
            tool_arguments={"path": "test.py", "content": "code"},
            timestamp=datetime.now(),
        )
    )

    # Try to complete with both tool name and finish_reason (should be blocked)
    result = await reactor.process_tool_call(
        ToolCallContext(
            session_id=session_id,
            backend_name="test-backend",
            model_name="test-model",
            full_response={"finish_reason": "stop"},
            tool_name="attempt_completion",
            tool_arguments={"result": "Done"},
            timestamp=datetime.now(),
        )
    )

    assert result is not None, "Combined tool name and finish_reason should be blocked"
    assert result.should_swallow is True
