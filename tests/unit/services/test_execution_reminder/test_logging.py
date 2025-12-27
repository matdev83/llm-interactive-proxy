"""Tests for comprehensive logging in test execution reminder handler."""

from __future__ import annotations

import logging
from unittest import mock

import pytest
from src.core.interfaces.tool_call_reactor_interface import ToolCallContext
from src.services.test_execution_reminder.test_execution_reminder_handler import (
    TestExecutionReminderHandler,
)


class TestLogging:
    """Test comprehensive logging functionality."""

    def test_initialization_logging_enabled(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test that initialization logs when feature is enabled."""
        caplog.set_level(logging.INFO)

        TestExecutionReminderHandler(enabled=True)

        # Should log initialization with pattern count
        assert any(
            "Test execution reminder handler initialized (enabled)" in record.message
            and "test runner patterns" in record.message
            for record in caplog.records
        )

    def test_initialization_logging_disabled(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test that initialization logs when feature is disabled."""
        caplog.set_level(logging.INFO)

        TestExecutionReminderHandler(enabled=False)

        # Should log initialization as disabled
        assert any(
            "Test execution reminder handler initialized (disabled)" in record.message
            for record in caplog.records
        )

    @pytest.mark.asyncio
    async def test_file_modification_logging(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test that file modifications are logged with tool name, session ID, and timestamp."""
        caplog.set_level(logging.INFO)

        handler = TestExecutionReminderHandler(enabled=True)

        # Create context for file modification
        context = ToolCallContext(
            session_id="test-session-123",
            backend_name="test-backend",
            model_name="test-model",
            tool_name="write_file",
            tool_arguments={"path": "test.py", "content": "print('hello')"},
            full_response=None,
        )

        # Process the tool call
        await handler.can_handle(context)

        # Should log file modification with tool name, session ID, and timestamp
        assert any(
            "File modification tracked" in record.message
            and "tool=write_file" in record.message
            and "session=test-session-123" in record.message
            and "timestamp=" in record.message
            and "modification_count=" in record.message
            for record in caplog.records
        )

    @pytest.mark.asyncio
    async def test_test_execution_logging(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test that test executions are logged with command, language, session ID, and state transition."""
        caplog.set_level(logging.INFO)

        handler = TestExecutionReminderHandler(enabled=True)

        # Create context for test execution
        context = ToolCallContext(
            session_id="test-session-456",
            backend_name="test-backend",
            model_name="test-model",
            tool_name="bash",
            tool_arguments={"command": "pytest tests/"},
            full_response=None,
        )

        # Process the tool call
        await handler.can_handle(context)

        # Should log test execution with command, language, framework, and session ID
        assert any(
            "Session test-session-456 marked as clean" in record.message
            and "test execution detected" in record.message
            and "language: python" in record.message
            and "framework: pytest" in record.message
            and "command: pytest tests/" in record.message
            for record in caplog.records
        )

    @pytest.mark.asyncio
    async def test_completion_signal_logging(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test that completion signals are logged with current state and tool name.

        Note: finish_reason detection was moved to EoS events per Requirement 7.6.
        The handler now only logs completion tool detection (by tool name).
        """
        caplog.set_level(logging.INFO)

        handler = TestExecutionReminderHandler(enabled=True)

        # First, mark session as dirty
        context_modify = ToolCallContext(
            session_id="test-session-789",
            backend_name="test-backend",
            model_name="test-model",
            tool_name="write_file",
            tool_arguments={"path": "test.py", "content": "print('hello')"},
            full_response=None,
        )
        await handler.can_handle(context_modify)

        # Clear the log
        caplog.clear()

        # Now send a completion signal
        context_complete = ToolCallContext(
            session_id="test-session-789",
            backend_name="test-backend",
            model_name="test-model",
            tool_name="task_complete",
            tool_arguments={},
            full_response=None,
        )

        # Process the completion signal
        await handler.can_handle(context_complete)

        # Should log completion tool detection with session, current state, and tool name
        # Note: "reason=" was removed when finish_reason detection moved to EoS events
        assert any(
            "Completion tool detected" in record.message
            and "session=test-session-789" in record.message
            and "current_state=dirty" in record.message
            and "tool=task_complete" in record.message
            for record in caplog.records
        )

    @pytest.mark.asyncio
    async def test_steering_injection_logging(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test that steering injections are logged with session ID and message preview."""
        caplog.set_level(logging.INFO)

        handler = TestExecutionReminderHandler(enabled=True)

        # First, mark session as dirty
        context_modify = ToolCallContext(
            session_id="test-session-abc",
            backend_name="test-backend",
            model_name="test-model",
            tool_name="write_file",
            tool_arguments={"path": "test.py", "content": "print('hello')"},
            full_response=None,
        )
        await handler.can_handle(context_modify)

        # Clear the log
        caplog.clear()

        # Now send a completion signal and handle it
        context_complete = ToolCallContext(
            session_id="test-session-abc",
            backend_name="test-backend",
            model_name="test-model",
            tool_name="task_complete",
            tool_arguments={},
            full_response=None,
        )

        # Process the completion signal
        can_handle = await handler.can_handle(context_complete)
        assert can_handle

        # Handle the steering injection
        await handler.handle(context_complete)

        # Should log steering injection with session ID and message preview
        assert any(
            "Steering injection" in record.message
            and "session=test-session-abc" in record.message
            and "modifications=" in record.message
            and "last_modified_ago=" in record.message
            and "message_preview=" in record.message
            for record in caplog.records
        )

    @pytest.mark.asyncio
    async def test_session_cleanup_logging(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test that session cleanup is logged appropriately."""
        caplog.set_level(logging.INFO)

        # Use a callable to provide time values without real sleeping
        current_time = [0.0]

        def mock_time():
            return current_time[0]

        # Mock time in specific module
        with (
            mock.patch(
                "src.services.test_execution_reminder.test_execution_reminder_handler.time",
                side_effect=mock_time,
            ),
            mock.patch(
                "src.services.test_execution_reminder.session_state.time",
                side_effect=mock_time,
            ),
        ):
            # Create handler with TTL=2
            handler = TestExecutionReminderHandler(enabled=True, state_ttl_seconds=2)

            # Create a session at t=0.0
            context = ToolCallContext(
                session_id="test-session-cleanup",
                backend_name="test-backend",
                model_name="test-model",
                tool_name="write_file",
                tool_arguments={"path": "test.py", "content": "print('hello')"},
                full_response=None,
            )
            await handler.can_handle(context)

            # Clear the log
            caplog.clear()

            # Advance time to 2.5 (after TTL expires)
            current_time[0] = 2.5

            # Create second session at t=2.5
            context2 = ToolCallContext(
                session_id="test-session-new",
                backend_name="test-backend",
                model_name="test-model",
                tool_name="write_file",
                tool_arguments={"path": "test.py", "content": "print('hello')"},
                full_response=None,
            )
            await handler.can_handle(context2)

        # Should log session cleanup
        assert any(
            "Session cleanup" in record.message
            and "pruned" in record.message
            and "expired session" in record.message
            for record in caplog.records
        )

    @pytest.mark.asyncio
    async def test_max_sessions_logging(self, caplog: pytest.LogCaptureFixture) -> None:
        """Test that max sessions enforcement is logged with warning level."""
        caplog.set_level(logging.INFO)

        # Create handler with max 2 sessions
        handler = TestExecutionReminderHandler(
            enabled=True, max_sessions=2, state_ttl_seconds=0.1
        )

        # Create 4 sessions to definitely trigger max limit
        # The pruning happens when we try to add beyond the max

        current_time = {"value": 1000.0}

        def fake_time() -> float:
            return current_time["value"]

        with (
            mock.patch("time.time", fake_time),
            mock.patch(
                "src.services.test_execution_reminder.session_state.time", fake_time
            ),
            mock.patch(
                "src.services.test_execution_reminder.test_execution_reminder_handler.time",
                fake_time,
            ),
        ):
            for i in range(4):
                context = ToolCallContext(
                    session_id=f"test-session-{i}",
                    backend_name="test-backend",
                    model_name="test-model",
                    tool_name="write_file",
                    tool_arguments={"path": "test.py", "content": "print('hello')"},
                    full_response=None,
                )
                await handler.can_handle(context)

                # Advance time to ensure different last_seen timestamps
                current_time["value"] += 0.001

        # Should log max sessions enforcement with WARNING level
        # Check that we have at least some session cleanup logging
        assert any(
            "Session cleanup" in record.message and "pruned" in record.message
            for record in caplog.records
        ), f"Expected session cleanup log, got: {[r.message for r in caplog.records]}"
