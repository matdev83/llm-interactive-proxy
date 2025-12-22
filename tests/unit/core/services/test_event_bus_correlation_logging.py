"""Unit tests for EventBus correlation-aware error logging.

This module tests that EventBus includes correlation identifiers (session_id)
in error logs for RemoteBackendConnectionEndOfSessionEvent and that listener
failures are properly isolated.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from src.core.domain.events.end_of_session_events import (
    EndOfSessionSignalType,
    EndOfSessionTerminationCategory,
    RemoteBackendConnectionEndOfSessionEvent,
)
from src.core.services.event_bus import EventBus


class TestEventBusCorrelationLogging:
    """Tests for correlation-aware error logging in EventBus."""

    @pytest.fixture
    def event_bus(self) -> EventBus:
        """Create a fresh event bus for each test."""
        return EventBus()

    @pytest.fixture
    def eos_event(self) -> RemoteBackendConnectionEndOfSessionEvent:
        """Create a test EoS event with session_id."""
        return RemoteBackendConnectionEndOfSessionEvent(
            session_id="test-session-123",
            signal_type=EndOfSessionSignalType.DONE_SENTINEL,
            termination_category=EndOfSessionTerminationCategory.NORMAL,
            timestamp=datetime.now(timezone.utc),
        )

    @pytest.mark.asyncio
    async def test_eos_event_error_logging_includes_session_id(
        self, event_bus: EventBus, eos_event: RemoteBackendConnectionEndOfSessionEvent
    ) -> None:
        """Test that error logging for EoS events includes session_id."""
        error_raised = ValueError("Test error")

        async def failing_handler(event: RemoteBackendConnectionEndOfSessionEvent) -> None:
            raise error_raised

        event_bus.subscribe(RemoteBackendConnectionEndOfSessionEvent, failing_handler)

        # Capture log messages
        with patch("src.core.services.event_bus.logger") as mock_logger:
            await event_bus.publish(eos_event)

            # Verify exception was logged
            mock_logger.exception.assert_called_once()

            # Get the call arguments
            call_args = mock_logger.exception.call_args

            # Verify the log message includes session_id
            log_message = call_args[0][0]
            assert "test-session-123" in log_message or "session_id" in str(call_args)

            # Verify extra context includes session_id if using structured logging
            if call_args.kwargs.get("extra"):
                extra = call_args.kwargs["extra"]
                # Check if session_id is in extra dict or in the message
                assert "test-session-123" in str(extra) or "test-session-123" in log_message

    @pytest.mark.asyncio
    async def test_listener_failures_are_isolated(
        self, event_bus: EventBus, eos_event: RemoteBackendConnectionEndOfSessionEvent
    ) -> None:
        """Test that one listener failure doesn't block other listeners."""
        successful_calls: list[str] = []
        failed_calls: list[str] = []

        async def failing_handler(event: RemoteBackendConnectionEndOfSessionEvent) -> None:
            failed_calls.append(event.session_id)
            raise ValueError("Handler failed")

        async def successful_handler(event: RemoteBackendConnectionEndOfSessionEvent) -> None:
            successful_calls.append(event.session_id)

        # Subscribe both handlers
        event_bus.subscribe(RemoteBackendConnectionEndOfSessionEvent, failing_handler)
        event_bus.subscribe(RemoteBackendConnectionEndOfSessionEvent, successful_handler)

        # Publish event - both handlers should be called
        await event_bus.publish(eos_event)

        # Verify both handlers were called
        assert len(failed_calls) == 1
        assert len(successful_calls) == 1
        assert failed_calls[0] == "test-session-123"
        assert successful_calls[0] == "test-session-123"

    @pytest.mark.asyncio
    async def test_original_payload_preserved_for_all_listeners(
        self, event_bus: EventBus, eos_event: RemoteBackendConnectionEndOfSessionEvent
    ) -> None:
        """Test that the original event payload is preserved for all listeners."""
        received_events: list[RemoteBackendConnectionEndOfSessionEvent] = []

        async def handler1(event: RemoteBackendConnectionEndOfSessionEvent) -> None:
            received_events.append(event)

        async def handler2(event: RemoteBackendConnectionEndOfSessionEvent) -> None:
            received_events.append(event)

        async def failing_handler(event: RemoteBackendConnectionEndOfSessionEvent) -> None:
            received_events.append(event)
            raise ValueError("Handler failed")

        # Subscribe multiple handlers including one that fails
        event_bus.subscribe(RemoteBackendConnectionEndOfSessionEvent, handler1)
        event_bus.subscribe(RemoteBackendConnectionEndOfSessionEvent, handler2)
        event_bus.subscribe(RemoteBackendConnectionEndOfSessionEvent, failing_handler)

        # Publish event
        await event_bus.publish(eos_event)

        # Verify all handlers received the same event object (or equal copy)
        assert len(received_events) == 3
        # All should have the same session_id
        assert all(event.session_id == "test-session-123" for event in received_events)
        # All should be the same event instance (same object identity)
        assert received_events[0] is received_events[1]
        assert received_events[1] is received_events[2]

    @pytest.mark.asyncio
    async def test_non_eos_event_error_logging_works_normally(
        self, event_bus: EventBus
    ) -> None:
        """Test that non-EoS events still log errors normally."""
        from dataclasses import dataclass

        @dataclass
        class TestEvent:
            message: str

        error_raised = ValueError("Test error")

        async def failing_handler(event: TestEvent) -> None:
            raise error_raised

        event_bus.subscribe(TestEvent, failing_handler)

        test_event = TestEvent(message="test")

        # Capture log messages
        with patch("src.core.services.event_bus.logger") as mock_logger:
            await event_bus.publish(test_event)

            # Verify exception was logged
            mock_logger.exception.assert_called_once()

            # Verify the log message doesn't break for non-EoS events
            call_args = mock_logger.exception.call_args
            assert call_args is not None

    @pytest.mark.asyncio
    async def test_multiple_failing_listeners_all_logged(
        self, event_bus: EventBus, eos_event: RemoteBackendConnectionEndOfSessionEvent
    ) -> None:
        """Test that multiple failing listeners all get their errors logged."""
        async def failing_handler1(event: RemoteBackendConnectionEndOfSessionEvent) -> None:
            raise ValueError("Handler 1 failed")

        async def failing_handler2(event: RemoteBackendConnectionEndOfSessionEvent) -> None:
            raise RuntimeError("Handler 2 failed")

        event_bus.subscribe(RemoteBackendConnectionEndOfSessionEvent, failing_handler1)
        event_bus.subscribe(RemoteBackendConnectionEndOfSessionEvent, failing_handler2)

        # Capture log messages
        with patch("src.core.services.event_bus.logger") as mock_logger:
            await event_bus.publish(eos_event)

            # Verify both exceptions were logged
            assert mock_logger.exception.call_count == 2

            # Verify both log messages include session_id
            for call in mock_logger.exception.call_args_list:
                log_message = call[0][0]
                assert "test-session-123" in log_message or "session_id" in str(call)

