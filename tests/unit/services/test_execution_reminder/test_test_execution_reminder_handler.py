"""Unit tests for TestExecutionReminderHandler."""

from __future__ import annotations

import pytest
from src.core.interfaces.tool_call_reactor_interface import (
    ToolCallContext,
)
from src.services.test_execution_reminder.test_execution_reminder_handler import (
    DEFAULT_STEERING_MESSAGE,
    TestExecutionReminderHandler,
)


class TestTestExecutionReminderHandlerBasics:
    """Test basic handler properties and initialization."""

    def test_handler_name(self) -> None:
        """Test that handler has correct name."""
        handler = TestExecutionReminderHandler()
        assert handler.name == "test_execution_reminder_handler"

    def test_handler_priority(self) -> None:
        """Test that handler has correct priority."""
        handler = TestExecutionReminderHandler()
        assert handler.priority == 90

    def test_handler_initialization_enabled(self) -> None:
        """Test handler initialization when enabled."""
        handler = TestExecutionReminderHandler(enabled=True)
        assert handler._enabled is True
        assert handler._message == DEFAULT_STEERING_MESSAGE
        assert handler._state_ttl_seconds == 1800
        assert handler._max_sessions == 1024
        assert len(handler._session_state) == 0

    def test_handler_initialization_disabled(self) -> None:
        """Test handler initialization when disabled."""
        handler = TestExecutionReminderHandler(enabled=False)
        assert handler._enabled is False

    def test_handler_custom_message(self) -> None:
        """Test handler with custom steering message."""
        custom_message = "Custom test reminder message"
        handler = TestExecutionReminderHandler(message=custom_message)
        assert handler._message == custom_message

    def test_handler_custom_ttl(self) -> None:
        """Test handler with custom TTL."""
        handler = TestExecutionReminderHandler(state_ttl_seconds=3600)
        assert handler._state_ttl_seconds == 3600

    def test_handler_custom_max_sessions(self) -> None:
        """Test handler with custom max sessions."""
        handler = TestExecutionReminderHandler(max_sessions=512)
        assert handler._max_sessions == 512

    def test_handler_minimum_ttl(self) -> None:
        """Test that TTL has minimum value of 1."""
        handler = TestExecutionReminderHandler(state_ttl_seconds=0)
        assert handler._state_ttl_seconds == 1

    def test_handler_minimum_max_sessions(self) -> None:
        """Test that max_sessions has minimum value of 1."""
        handler = TestExecutionReminderHandler(max_sessions=0)
        assert handler._max_sessions == 1


class TestTestExecutionReminderHandlerDisabled:
    """Test handler behavior when disabled."""

    @pytest.mark.asyncio
    async def test_can_handle_returns_false_when_disabled(self) -> None:
        """Test that can_handle returns False when handler is disabled."""
        handler = TestExecutionReminderHandler(enabled=False)
        context = ToolCallContext(
            session_id="test-session",
            backend_name="test-backend",
            model_name="test-model",
            full_response={},
            tool_name="write_file",
            tool_arguments={"path": "test.py", "content": "print('hello')"},
        )
        result = await handler.can_handle(context)
        assert result is False

    @pytest.mark.asyncio
    async def test_handle_returns_no_swallow_when_disabled(self) -> None:
        """Test that handle returns no swallow when handler is disabled."""
        handler = TestExecutionReminderHandler(enabled=False)
        context = ToolCallContext(
            session_id="test-session",
            backend_name="test-backend",
            model_name="test-model",
            full_response={},
            tool_name="task_complete",
            tool_arguments={},
        )
        result = await handler.handle(context)
        assert result.should_swallow is False


class TestTestExecutionReminderHandlerFileModification:
    """Test handler behavior for file modification detection."""

    @pytest.mark.asyncio
    async def test_file_modification_marks_dirty(self) -> None:
        """Test that file modification tool marks session as dirty."""
        handler = TestExecutionReminderHandler(enabled=True)
        context = ToolCallContext(
            session_id="test-session",
            backend_name="test-backend",
            model_name="test-model",
            full_response={},
            tool_name="write_file",
            tool_arguments={"path": "test.py", "content": "print('hello')"},
        )

        # File modification should not be handled (returns False)
        result = await handler.can_handle(context)
        assert result is False

        # But session should be marked as dirty
        state = handler._session_state.get("test-session")
        assert state is not None
        assert state.is_dirty is True
        assert state.modification_count == 1

    @pytest.mark.asyncio
    async def test_multiple_file_modifications_increment_count(self) -> None:
        """Test that multiple file modifications increment the count."""
        handler = TestExecutionReminderHandler(enabled=True)
        context = ToolCallContext(
            session_id="test-session",
            backend_name="test-backend",
            model_name="test-model",
            full_response={},
            tool_name="write_file",
            tool_arguments={"path": "test.py", "content": "print('hello')"},
        )

        # First modification
        await handler.can_handle(context)
        state = handler._session_state.get("test-session")
        assert state is not None
        assert state.modification_count == 1

        # Second modification
        await handler.can_handle(context)
        state = handler._session_state.get("test-session")
        assert state is not None
        assert state.modification_count == 2


class TestTestExecutionReminderHandlerTestExecution:
    """Test handler behavior for test execution detection."""

    @pytest.mark.asyncio
    async def test_test_execution_marks_clean(self) -> None:
        """Test that test execution marks session as clean."""
        handler = TestExecutionReminderHandler(enabled=True)

        # First mark as dirty
        dirty_context = ToolCallContext(
            session_id="test-session",
            backend_name="test-backend",
            model_name="test-model",
            full_response={},
            tool_name="write_file",
            tool_arguments={"path": "test.py", "content": "print('hello')"},
        )
        await handler.can_handle(dirty_context)

        # Verify dirty
        state = handler._session_state.get("test-session")
        assert state is not None
        assert state.is_dirty is True

        # Now run tests
        test_context = ToolCallContext(
            session_id="test-session",
            backend_name="test-backend",
            model_name="test-model",
            full_response={},
            tool_name="bash",
            tool_arguments={"command": "pytest tests/"},
        )
        result = await handler.can_handle(test_context)
        assert result is False  # Test execution should not be handled

        # Verify clean
        state = handler._session_state.get("test-session")
        assert state is not None
        assert state.is_dirty is False
        assert state.modification_count == 0


class TestTestExecutionReminderHandlerCompletionSignal:
    """Test handler behavior for completion signal detection."""

    @pytest.mark.asyncio
    async def test_completion_in_clean_state_not_handled(self) -> None:
        """Test that completion signal in clean state is not handled."""
        handler = TestExecutionReminderHandler(enabled=True)
        context = ToolCallContext(
            session_id="test-session",
            backend_name="test-backend",
            model_name="test-model",
            full_response={"content": "The task is complete"},
            tool_name="some_tool",
            tool_arguments={},
        )

        result = await handler.can_handle(context)
        assert result is False

    @pytest.mark.asyncio
    async def test_completion_in_dirty_state_is_handled(self) -> None:
        """Test that completion signal in dirty state is handled."""
        handler = TestExecutionReminderHandler(enabled=True)

        # First mark as dirty
        dirty_context = ToolCallContext(
            session_id="test-session",
            backend_name="test-backend",
            model_name="test-model",
            full_response={},
            tool_name="write_file",
            tool_arguments={"path": "test.py", "content": "print('hello')"},
        )
        await handler.can_handle(dirty_context)

        # Now try to complete using a completion tool name
        completion_context = ToolCallContext(
            session_id="test-session",
            backend_name="test-backend",
            model_name="test-model",
            full_response={},
            tool_name="attempt_completion",
            tool_arguments={},
        )

        result = await handler.can_handle(completion_context)
        assert result is True

    @pytest.mark.asyncio
    async def test_handle_returns_steering_message(self) -> None:
        """Test that handle returns steering message for dirty completion."""
        handler = TestExecutionReminderHandler(enabled=True)

        # First mark as dirty
        dirty_context = ToolCallContext(
            session_id="test-session",
            backend_name="test-backend",
            model_name="test-model",
            full_response={},
            tool_name="write_file",
            tool_arguments={"path": "test.py", "content": "print('hello')"},
        )
        await handler.can_handle(dirty_context)

        # Now try to complete using a completion tool name
        completion_context = ToolCallContext(
            session_id="test-session",
            backend_name="test-backend",
            model_name="test-model",
            full_response={},
            tool_name="attempt_completion",
            tool_arguments={},
        )

        result = await handler.handle(completion_context)
        assert result.should_swallow is True
        assert result.replacement_response == DEFAULT_STEERING_MESSAGE
        assert result.metadata is not None
        assert result.metadata["handler"] == "test_execution_reminder_handler"
        assert result.metadata["source"] == "test_execution_reminder"


class TestTestExecutionReminderHandlerSessionIsolation:
    """Test session isolation."""

    @pytest.mark.asyncio
    async def test_sessions_are_isolated(self) -> None:
        """Test that different sessions maintain independent state."""
        handler = TestExecutionReminderHandler(enabled=True)

        # Mark session 1 as dirty
        context1 = ToolCallContext(
            session_id="session-1",
            backend_name="test-backend",
            model_name="test-model",
            full_response={},
            tool_name="write_file",
            tool_arguments={"path": "test.py", "content": "print('hello')"},
        )
        await handler.can_handle(context1)

        # Session 2 should be clean
        context2 = ToolCallContext(
            session_id="session-2",
            backend_name="test-backend",
            model_name="test-model",
            full_response={"content": "The task is complete"},
            tool_name="some_tool",
            tool_arguments={},
        )
        result = await handler.can_handle(context2)
        assert result is False  # Session 2 is clean, so completion is not handled

        # Session 1 should still be dirty
        state1 = handler._session_state.get("session-1")
        assert state1 is not None
        assert state1.is_dirty is True


class TestTestExecutionReminderHandlerCommandExtraction:
    """Test command extraction from tool calls."""

    def test_extract_command_from_bash_tool(self) -> None:
        """Test extracting command from bash tool."""
        handler = TestExecutionReminderHandler(enabled=True)
        command = handler._extract_command("bash", {"command": "pytest tests/"})
        assert command == "pytest tests/"

    def test_extract_command_from_shell_tool(self) -> None:
        """Test extracting command from shell tool."""
        handler = TestExecutionReminderHandler(enabled=True)
        command = handler._extract_command("shell", {"command": "npm test"})
        assert command == "npm test"

    def test_extract_command_with_cmd_key(self) -> None:
        """Test extracting command with 'cmd' key."""
        handler = TestExecutionReminderHandler(enabled=True)
        command = handler._extract_command("execute", {"cmd": "cargo test"})
        assert command == "cargo test"

    def test_extract_command_with_script_key(self) -> None:
        """Test extracting command with 'script' key."""
        handler = TestExecutionReminderHandler(enabled=True)
        command = handler._extract_command("bash", {"script": "go test ./..."})
        assert command == "go test ./..."

    def test_extract_command_returns_none_for_non_shell_tool(self) -> None:
        """Test that command extraction returns None for non-shell tools."""
        handler = TestExecutionReminderHandler(enabled=True)
        command = handler._extract_command("write_file", {"path": "test.py"})
        assert command is None

    def test_extract_command_returns_none_for_missing_command(self) -> None:
        """Test that command extraction returns None when command is missing."""
        handler = TestExecutionReminderHandler(enabled=True)
        command = handler._extract_command("bash", {"other_arg": "value"})
        assert command is None

    def test_extract_command_strips_whitespace(self) -> None:
        """Test that command extraction strips whitespace."""
        handler = TestExecutionReminderHandler(enabled=True)
        command = handler._extract_command("bash", {"command": "  pytest  "})
        assert command == "pytest"

    def test_extract_command_handles_case_insensitive_tool_names(self) -> None:
        """Test that command extraction handles case-insensitive tool names."""
        handler = TestExecutionReminderHandler(enabled=True)
        command = handler._extract_command("BASH", {"command": "pytest"})
        assert command == "pytest"

    def test_extract_command_handles_underscores_in_tool_names(self) -> None:
        """Test that command extraction handles underscores in tool names."""
        handler = TestExecutionReminderHandler(enabled=True)
        command = handler._extract_command("run_command", {"command": "pytest"})
        assert command == "pytest"


class TestTestExecutionReminderHandlerErrorHandling:
    """Test error handling in handler."""

    @pytest.mark.asyncio
    async def test_can_handle_fails_open_on_error(self) -> None:
        """Test that can_handle fails open (returns False) on error."""
        handler = TestExecutionReminderHandler(enabled=True)

        # Create a context that will cause an error in processing
        # Use a mock that raises an exception
        context = ToolCallContext(
            session_id="test-session",
            backend_name="test-backend",
            model_name="test-model",
            full_response=None,
            tool_name=None,  # This might cause issues
            tool_arguments=None,  # This might cause issues
        )

        # Should not raise, should return False
        result = await handler.can_handle(context)
        assert result is False

    @pytest.mark.asyncio
    async def test_handle_fails_open_on_error(self) -> None:
        """Test that handle fails open (returns no swallow) on error."""
        handler = TestExecutionReminderHandler(enabled=True)

        # Create a context that will cause an error
        context = ToolCallContext(
            session_id="test-session",
            backend_name="test-backend",
            model_name="test-model",
            full_response=None,
            tool_name=None,
            tool_arguments=None,
        )

        # Should not raise, should return no swallow
        result = await handler.handle(context)
        assert result.should_swallow is False

    def test_mark_session_dirty_handles_errors(self) -> None:
        """Test that _mark_session_dirty handles errors gracefully."""
        handler = TestExecutionReminderHandler(enabled=True)

        # Should not raise even with invalid session ID
        handler._mark_session_dirty("", None)

    def test_mark_session_clean_handles_errors(self) -> None:
        """Test that _mark_session_clean handles errors gracefully."""
        handler = TestExecutionReminderHandler(enabled=True)

        # Should not raise even with invalid parameters
        handler._mark_session_clean("", "", None, None)

    def test_get_session_state_handles_errors(self) -> None:
        """Test that _get_session_state handles errors gracefully."""
        handler = TestExecutionReminderHandler(enabled=True)

        # Should not raise even with invalid session ID
        handler._get_session_state("")
        # Should return None or a valid state, not raise


class TestTestExecutionReminderHandlerStateTransitions:
    """Test state transition scenarios."""

    @pytest.mark.asyncio
    async def test_dirty_to_clean_to_dirty_cycle(self) -> None:
        """Test state transitions through a complete cycle."""
        handler = TestExecutionReminderHandler(enabled=True)

        # Start clean (implicit)
        state = handler._session_state.get("test-session")
        assert state is None  # No state yet

        # Modify file -> dirty
        dirty_context = ToolCallContext(
            session_id="test-session",
            backend_name="test-backend",
            model_name="test-model",
            full_response={},
            tool_name="write_file",
            tool_arguments={"path": "test.py", "content": "code"},
        )
        await handler.can_handle(dirty_context)
        state = handler._session_state.get("test-session")
        assert state is not None
        assert state.is_dirty is True

        # Run tests -> clean
        test_context = ToolCallContext(
            session_id="test-session",
            backend_name="test-backend",
            model_name="test-model",
            full_response={},
            tool_name="bash",
            tool_arguments={"command": "pytest"},
        )
        await handler.can_handle(test_context)
        state = handler._session_state.get("test-session")
        assert state is not None
        assert state.is_dirty is False

        # Modify file again -> dirty
        await handler.can_handle(dirty_context)
        state = handler._session_state.get("test-session")
        assert state is not None
        assert state.is_dirty is True

    @pytest.mark.asyncio
    async def test_multiple_test_runs_maintain_clean_state(self) -> None:
        """Test that running tests multiple times maintains clean state."""
        handler = TestExecutionReminderHandler(enabled=True)

        # Run tests first time
        test_context = ToolCallContext(
            session_id="test-session",
            backend_name="test-backend",
            model_name="test-model",
            full_response={},
            tool_name="bash",
            tool_arguments={"command": "pytest"},
        )
        await handler.can_handle(test_context)
        state = handler._session_state.get("test-session")
        assert state is not None
        assert state.is_dirty is False

        # Run tests second time
        await handler.can_handle(test_context)
        state = handler._session_state.get("test-session")
        assert state is not None
        assert state.is_dirty is False

        # Run tests third time
        await handler.can_handle(test_context)
        state = handler._session_state.get("test-session")
        assert state is not None
        assert state.is_dirty is False


class TestTestExecutionReminderHandlerCustomMessage:
    """Test custom steering message handling."""

    @pytest.mark.asyncio
    async def test_custom_message_is_used_in_steering(self) -> None:
        """Test that custom message is used in steering response."""
        custom_message = "Please run your tests before finishing!"
        handler = TestExecutionReminderHandler(enabled=True, message=custom_message)

        # Mark as dirty
        dirty_context = ToolCallContext(
            session_id="test-session",
            backend_name="test-backend",
            model_name="test-model",
            full_response={},
            tool_name="write_file",
            tool_arguments={"path": "test.py", "content": "code"},
        )
        await handler.can_handle(dirty_context)

        # Try to complete using a completion tool name
        completion_context = ToolCallContext(
            session_id="test-session",
            backend_name="test-backend",
            model_name="test-model",
            full_response={},
            tool_name="attempt_completion",
            tool_arguments={},
        )

        result = await handler.handle(completion_context)
        assert result.should_swallow is True
        assert result.replacement_response == custom_message


class TestTestExecutionReminderHandlerMetadata:
    """Test metadata in steering responses."""

    @pytest.mark.asyncio
    async def test_metadata_includes_modification_count(self) -> None:
        """Test that metadata includes modification count."""
        handler = TestExecutionReminderHandler(enabled=True)

        # Make multiple modifications
        dirty_context = ToolCallContext(
            session_id="test-session",
            backend_name="test-backend",
            model_name="test-model",
            full_response={},
            tool_name="write_file",
            tool_arguments={"path": "test.py", "content": "code"},
        )
        await handler.can_handle(dirty_context)
        await handler.can_handle(dirty_context)
        await handler.can_handle(dirty_context)

        # Try to complete using a completion tool name
        completion_context = ToolCallContext(
            session_id="test-session",
            backend_name="test-backend",
            model_name="test-model",
            full_response={},
            tool_name="attempt_completion",
            tool_arguments={},
        )

        result = await handler.handle(completion_context)
        assert result.metadata is not None
        assert result.metadata["modification_count"] == 3

    @pytest.mark.asyncio
    async def test_metadata_includes_tool_name(self) -> None:
        """Test that metadata includes tool name."""
        handler = TestExecutionReminderHandler(enabled=True)

        # Mark as dirty
        dirty_context = ToolCallContext(
            session_id="test-session",
            backend_name="test-backend",
            model_name="test-model",
            full_response={},
            tool_name="write_file",
            tool_arguments={"path": "test.py", "content": "code"},
        )
        await handler.can_handle(dirty_context)

        # Try to complete with specific tool
        completion_context = ToolCallContext(
            session_id="test-session",
            backend_name="test-backend",
            model_name="test-model",
            full_response={"content": "Task is complete"},
            tool_name="task_complete",
            tool_arguments={},
        )

        result = await handler.handle(completion_context)
        assert result.metadata is not None
        assert result.metadata["tool_name"] == "task_complete"


class TestTestExecutionReminderHandlerCompletionDetection:
    """Test completion signal detection scenarios."""

    @pytest.mark.asyncio
    async def test_completion_tool_name_detected(self) -> None:
        """Test that completion tool names are detected."""
        handler = TestExecutionReminderHandler(enabled=True)

        # Mark as dirty
        dirty_context = ToolCallContext(
            session_id="test-session",
            backend_name="test-backend",
            model_name="test-model",
            full_response={},
            tool_name="write_file",
            tool_arguments={"path": "test.py", "content": "code"},
        )
        await handler.can_handle(dirty_context)

        # Use completion tool name
        completion_context = ToolCallContext(
            session_id="test-session",
            backend_name="test-backend",
            model_name="test-model",
            full_response={},
            tool_name="task_complete",
            tool_arguments={},
        )

        result = await handler.can_handle(completion_context)
        assert result is True

    @pytest.mark.asyncio
    async def test_completion_attempt_completion_tool(self) -> None:
        """Test that attempt_completion tool is detected."""
        handler = TestExecutionReminderHandler(enabled=True)

        # Mark as dirty
        dirty_context = ToolCallContext(
            session_id="test-session",
            backend_name="test-backend",
            model_name="test-model",
            full_response={},
            tool_name="write_file",
            tool_arguments={"path": "test.py", "content": "code"},
        )
        await handler.can_handle(dirty_context)

        # Use attempt_completion tool (used by Cline/Roo-Code)
        completion_context = ToolCallContext(
            session_id="test-session",
            backend_name="test-backend",
            model_name="test-model",
            full_response={},
            tool_name="attempt_completion",
            tool_arguments={},
        )

        result = await handler.can_handle(completion_context)
        assert result is True


class TestTestExecutionReminderHandlerNonCompletionScenarios:
    """Test scenarios that should not trigger completion detection."""

    @pytest.mark.asyncio
    async def test_non_completion_tool_not_handled(self) -> None:
        """Test that non-completion tools are not handled."""
        handler = TestExecutionReminderHandler(enabled=True)

        # Mark as dirty
        dirty_context = ToolCallContext(
            session_id="test-session",
            backend_name="test-backend",
            model_name="test-model",
            full_response={},
            tool_name="write_file",
            tool_arguments={"path": "test.py", "content": "code"},
        )
        await handler.can_handle(dirty_context)

        # Use non-completion tool
        non_completion_context = ToolCallContext(
            session_id="test-session",
            backend_name="test-backend",
            model_name="test-model",
            full_response={},
            tool_name="read_file",
            tool_arguments={"path": "test.py"},
        )

        result = await handler.can_handle(non_completion_context)
        assert result is False

    @pytest.mark.asyncio
    async def test_progress_update_not_detected_as_completion(self) -> None:
        """Test that progress updates are not detected as completion."""
        handler = TestExecutionReminderHandler(enabled=True)

        # Mark as dirty
        dirty_context = ToolCallContext(
            session_id="test-session",
            backend_name="test-backend",
            model_name="test-model",
            full_response={},
            tool_name="write_file",
            tool_arguments={"path": "test.py", "content": "code"},
        )
        await handler.can_handle(dirty_context)

        # Progress update (not completion)
        progress_context = ToolCallContext(
            session_id="test-session",
            backend_name="test-backend",
            model_name="test-model",
            full_response={"content": "I'm working on the implementation"},
            tool_name="some_tool",
            tool_arguments={},
        )

        result = await handler.can_handle(progress_context)
        assert result is False

    @pytest.mark.asyncio
    async def test_no_finish_reason_not_detected_as_completion(self) -> None:
        """Test that responses without finish_reason are not detected as completion."""
        handler = TestExecutionReminderHandler(enabled=True)

        # Mark as dirty
        dirty_context = ToolCallContext(
            session_id="test-session",
            backend_name="test-backend",
            model_name="test-model",
            full_response={},
            tool_name="write_file",
            tool_arguments={"path": "test.py", "content": "code"},
        )
        await handler.can_handle(dirty_context)

        # Response without finish_reason or completion tool
        non_completion_context = ToolCallContext(
            session_id="test-session",
            backend_name="test-backend",
            model_name="test-model",
            full_response={"content": "Some response"},
            tool_name="some_tool",
            tool_arguments={},
        )

        result = await handler.can_handle(non_completion_context)
        assert result is False
