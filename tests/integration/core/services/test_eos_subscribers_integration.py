"""Integration tests for EoS subscribers.

These tests verify that all EoS subscribers are properly registered, receive events,
and handle them correctly in an integrated environment.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from freezegun import freeze_time
from src.core.database.models.usage import SessionMetricsTable
from src.core.database.repositories.usage_repository import SessionMetricsRepository
from src.core.domain.events.end_of_session_events import (
    EndOfSessionSignalType,
    EndOfSessionTerminationCategory,
    RemoteBackendConnectionEndOfSessionEvent,
)
from src.core.interfaces.memory_service_interface import IMemoryService
from src.core.interfaces.wire_capture_interface import IWireCapture
from src.core.memory.eos_subscriber import ProxyMemEosSubscriber
from src.core.services.event_bus import EventBus
from src.core.services.usage_tracking_eos_subscriber import UsageTrackingEosSubscriber
from src.core.services.wire_capture_eos_subscriber import WireCaptureEosSubscriber
from src.services.test_execution_reminder.eos_subscriber import (
    TestExecutionReminderEosSubscriber,
)
from src.services.test_execution_reminder.test_execution_reminder_handler import (
    TestExecutionReminderHandler,
)
from tests.utils.fake_clock import FakeClockContext


@pytest.fixture
def event_bus() -> EventBus:
    """Create a real EventBus instance."""
    return EventBus()


@pytest.fixture
def mock_memory_service() -> IMemoryService:
    """Create a mock memory service."""
    service = AsyncMock(spec=IMemoryService)
    service.mark_session_complete = AsyncMock(return_value=True)
    return service


@pytest.fixture
def mock_session_repo() -> SessionMetricsRepository:
    """Create a mock session metrics repository."""
    repo = AsyncMock(spec=SessionMetricsRepository)
    repo.get_by_id = AsyncMock(return_value=None)
    repo.update = AsyncMock()
    repo.create = AsyncMock()
    return repo


@pytest.fixture
def mock_wire_capture() -> IWireCapture:
    """Create a mock wire capture service."""
    capture = AsyncMock(spec=IWireCapture)
    capture.enabled = MagicMock(return_value=True)
    capture.capture_stream_completion = AsyncMock()
    return capture


@pytest.fixture
def mock_reminder_handler() -> TestExecutionReminderHandler:
    """Create a mock reminder handler."""
    handler = MagicMock(spec=TestExecutionReminderHandler)
    handler._get_session_state = MagicMock(return_value=None)
    return handler


@pytest.fixture
async def proxymem_subscriber(
    event_bus: EventBus, mock_memory_service: IMemoryService
) -> ProxyMemEosSubscriber:
    """Create and start ProxyMemEosSubscriber."""
    subscriber = ProxyMemEosSubscriber(
        event_bus=event_bus, memory_service=mock_memory_service
    )
    await subscriber.start()
    return subscriber


@pytest.fixture
async def usage_subscriber(
    event_bus: EventBus, mock_session_repo: SessionMetricsRepository
) -> UsageTrackingEosSubscriber:
    """Create and start UsageTrackingEosSubscriber."""
    subscriber = UsageTrackingEosSubscriber(
        event_bus=event_bus, session_repository=mock_session_repo
    )
    await subscriber.start()
    return subscriber


@pytest.fixture
async def wire_capture_subscriber(
    event_bus: EventBus, mock_wire_capture: IWireCapture
) -> WireCaptureEosSubscriber:
    """Create and start WireCaptureEosSubscriber."""
    subscriber = WireCaptureEosSubscriber(
        event_bus=event_bus, wire_capture=mock_wire_capture
    )
    await subscriber.start()
    return subscriber


@pytest.fixture
async def reminder_subscriber(
    event_bus: EventBus, mock_reminder_handler: TestExecutionReminderHandler
) -> TestExecutionReminderEosSubscriber:
    """Create and start TestExecutionReminderEosSubscriber."""
    subscriber = TestExecutionReminderEosSubscriber(
        event_bus=event_bus, reminder_handler=mock_reminder_handler
    )
    await subscriber.start()
    return subscriber


@pytest.mark.asyncio
async def test_all_subscribers_receive_eos_event(
    event_bus: EventBus,
    proxymem_subscriber: ProxyMemEosSubscriber,
    usage_subscriber: UsageTrackingEosSubscriber,
    wire_capture_subscriber: WireCaptureEosSubscriber,
    reminder_subscriber: TestExecutionReminderEosSubscriber,
    mock_memory_service: IMemoryService,
    mock_session_repo: SessionMetricsRepository,
    mock_wire_capture: IWireCapture,
    mock_reminder_handler: TestExecutionReminderHandler,
) -> None:
    """Test that all subscribers receive and process EoS events."""
    event = RemoteBackendConnectionEndOfSessionEvent(
        session_id="test-session-123",
        signal_type=EndOfSessionSignalType.DONE_SENTINEL,
        termination_category=EndOfSessionTerminationCategory.NORMAL,
        backend="openai:gpt-4",
        reason="Stream completed",
    )

    # Publish event
    await event_bus.publish(event)

    # Give subscribers time to process (they run concurrently)
    async with FakeClockContext() as clock:
        sleep_task = asyncio.create_task(asyncio.sleep(0.01))
        clock.advance(0.01)  # Reduced from 0.1 for performance
        await sleep_task

    # Verify ProxyMem subscriber was called
    mock_memory_service.mark_session_complete.assert_called_once_with(
        "test-session-123",
        backend_model="openai:gpt-4",
        termination_reason="Stream completed",
    )

    # Verify UsageTracking subscriber was called
    mock_session_repo.create.assert_called_once()
    call_args = mock_session_repo.create.call_args
    metrics: SessionMetricsTable = call_args[0][0]
    assert metrics.session_id == "test-session-123"
    assert metrics.is_completed is True
    assert metrics.eos_signal_type == "done_sentinel"

    # Verify WireCapture subscriber was called
    mock_wire_capture.capture_stream_completion.assert_called_once()

    # Verify Reminder subscriber was called
    mock_reminder_handler._get_session_state.assert_called_once_with("test-session-123")


@pytest.mark.asyncio
async def test_subscriber_failures_are_isolated(
    event_bus: EventBus,
    mock_memory_service: IMemoryService,
    mock_session_repo: SessionMetricsRepository,
    mock_wire_capture: IWireCapture,
    mock_reminder_handler: TestExecutionReminderHandler,
) -> None:
    """Test that one subscriber failure does not block other subscribers.

    Requirement 5.4: Failures in one subsystem finalizer should not prevent
    other finalizers from running.
    """
    # Create subscribers
    proxymem = ProxyMemEosSubscriber(
        event_bus=event_bus, memory_service=mock_memory_service
    )
    usage = UsageTrackingEosSubscriber(
        event_bus=event_bus, session_repository=mock_session_repo
    )
    wire_capture = WireCaptureEosSubscriber(
        event_bus=event_bus, wire_capture=mock_wire_capture
    )
    reminder = TestExecutionReminderEosSubscriber(
        event_bus=event_bus, reminder_handler=mock_reminder_handler
    )

    await proxymem.start()
    await usage.start()
    await wire_capture.start()
    await reminder.start()

    # Make one subscriber fail
    mock_memory_service.mark_session_complete.side_effect = Exception(
        "ProxyMem failure"
    )
    mock_memory_service.is_enabled_for_session.return_value = True

    event = RemoteBackendConnectionEndOfSessionEvent(
        session_id="test-session-failure",
        signal_type=EndOfSessionSignalType.DONE_SENTINEL,
        termination_category=EndOfSessionTerminationCategory.NORMAL,
        backend="openai:gpt-4",
    )

    # Publish event - should not raise exception even if one subscriber fails
    await event_bus.publish(event)

    # Give subscribers time to process
    async with FakeClockContext() as clock:
        sleep_task = asyncio.create_task(asyncio.sleep(0.01))
        clock.advance(0.01)  # Reduced from 0.1 for performance
        await sleep_task

    # Verify other subscribers still processed the event
    # UsageTracking should have been called
    assert mock_session_repo.create.called or mock_session_repo.update.called

    # WireCapture should have been called
    mock_wire_capture.capture_stream_completion.assert_called_once()

    # Reminder should have been called
    mock_reminder_handler._get_session_state.assert_called_once_with(
        "test-session-failure"
    )


@pytest.mark.asyncio
async def test_eos_emission_when_client_terminates_before_backend_response(
    event_bus: EventBus,
    mock_session_repo: SessionMetricsRepository,
    mock_wire_capture: IWireCapture,
) -> None:
    """Test that EoS is emitted even when client terminates before backend response.

    Requirement 5.5: EoS should be emitted even when client terminates before
    any backend response is received.
    """

    from src.core.config.models.end_of_session import EndOfSessionConfig
    from src.core.domain.events.end_of_session_events import (
        EndOfSessionSignal,
        EndOfSessionSignalType,
        EndOfSessionTerminationCategory,
    )
    from src.core.services.end_of_session_service import EndOfSessionService

    eos_config = EndOfSessionConfig(
        enabled=True,
        emit_events=True,
        detect_stream_signals=True,
        detect_tool_completion=True,
        dispatch_timeout_seconds=5.0,
    )

    eos_service = EndOfSessionService(
        event_bus=event_bus,
        config=eos_config,
        session_repository=mock_session_repo,
    )

    # Create usage tracking subscriber
    usage = UsageTrackingEosSubscriber(
        event_bus=event_bus, session_repository=mock_session_repo
    )
    await usage.start()

    # Create wire capture subscriber
    wire_capture = WireCaptureEosSubscriber(
        event_bus=event_bus, wire_capture=mock_wire_capture
    )
    await wire_capture.start()

    events_received: list = []

    async def event_handler(event) -> None:
        events_received.append(event)

    event_bus.subscribe(RemoteBackendConnectionEndOfSessionEvent, event_handler)

    # Simulate client termination before backend response
    # No backend field since no backend response was received
    with freeze_time("2024-01-01 12:00:00"):
        signal = EndOfSessionSignal(
            session_id="early-termination-session",
            signal_type=EndOfSessionSignalType.CLIENT_TERMINATION,
            termination_category=EndOfSessionTerminationCategory.NORMAL,
            observed_at=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            reason="client_disconnected",
            backend=None,  # No backend response yet
        )

        await eos_service.record_signal(signal)

    # Give time for event processing
    async with FakeClockContext() as clock:
        sleep_task = asyncio.create_task(asyncio.sleep(0.1))
        clock.advance(0.1)
        await sleep_task

    # Verify EoS event was emitted
    assert len(events_received) == 1
    event = events_received[0]
    assert event.session_id == "early-termination-session"
    assert event.signal_type == EndOfSessionSignalType.CLIENT_TERMINATION
    assert event.termination_category == EndOfSessionTerminationCategory.NORMAL
    assert event.reason == "client_disconnected"
    assert event.backend is None  # No backend response

    # Verify usage tracking subscriber processed the event
    assert mock_session_repo.create.called or mock_session_repo.update.called

    # Verify wire capture subscriber processed the event
    mock_wire_capture.capture_stream_completion.assert_called_once()


@pytest.mark.asyncio
async def test_multiple_subscriber_failures_isolated(
    event_bus: EventBus,
    mock_memory_service: IMemoryService,
    mock_session_repo: SessionMetricsRepository,
    mock_wire_capture: IWireCapture,
    mock_reminder_handler: TestExecutionReminderHandler,
) -> None:
    """Test that multiple subscriber failures don't block remaining subscribers."""
    # Create subscribers
    proxymem_subscriber = ProxyMemEosSubscriber(
        event_bus=event_bus, memory_service=mock_memory_service
    )
    usage_subscriber = UsageTrackingEosSubscriber(
        event_bus=event_bus, session_repository=mock_session_repo
    )
    wire_capture_subscriber = WireCaptureEosSubscriber(
        event_bus=event_bus, wire_capture=mock_wire_capture
    )
    reminder_subscriber = TestExecutionReminderEosSubscriber(
        event_bus=event_bus, reminder_handler=mock_reminder_handler
    )

    await proxymem_subscriber.start()
    await usage_subscriber.start()
    await wire_capture_subscriber.start()
    await reminder_subscriber.start()

    # Make two subscribers fail
    mock_memory_service.mark_session_complete.side_effect = Exception("Memory error")
    mock_wire_capture.capture_stream_completion.side_effect = Exception("Capture error")

    event = RemoteBackendConnectionEndOfSessionEvent(
        session_id="test-session-456",
        signal_type=EndOfSessionSignalType.DONE_SENTINEL,
        termination_category=EndOfSessionTerminationCategory.NORMAL,
    )

    # Publish event - should not raise exception
    await event_bus.publish(event)

    # Give subscribers time to process
    async with FakeClockContext() as clock:
        sleep_task = asyncio.create_task(asyncio.sleep(0.01))
        clock.advance(0.01)  # Reduced from 0.1 for performance
        await sleep_task

    # Verify remaining subscribers were still called
    mock_session_repo.create.assert_called_once()
    mock_reminder_handler._get_session_state.assert_called_once()


@pytest.mark.asyncio
async def test_subscriber_failure_logs_correlation_identifier(
    event_bus: EventBus,
    mock_memory_service: IMemoryService,
    caplog,
) -> None:
    """Test that subscriber failures are logged with correlation identifiers."""
    import logging

    subscriber = ProxyMemEosSubscriber(
        event_bus=event_bus, memory_service=mock_memory_service
    )
    await subscriber.start()

    # Make subscriber fail
    mock_memory_service.mark_session_complete.side_effect = Exception("Memory error")

    session_id = "correlation-test-123"
    event = RemoteBackendConnectionEndOfSessionEvent(
        session_id=session_id,
        signal_type=EndOfSessionSignalType.DONE_SENTINEL,
        termination_category=EndOfSessionTerminationCategory.NORMAL,
    )

    with caplog.at_level(logging.ERROR):
        await event_bus.publish(event)

        # Give subscriber time to process
        async with FakeClockContext() as clock:
            sleep_task = asyncio.create_task(asyncio.sleep(0.1))
            clock.advance(0.1)
            await sleep_task

    # Verify error was logged with session_id correlation
    assert session_id in caplog.text or "session_id" in caplog.text.lower()


@pytest.mark.asyncio
async def test_subscriber_payload_preserved_on_failure(
    event_bus: EventBus,
    mock_memory_service: IMemoryService,
    mock_session_repo: SessionMetricsRepository,
) -> None:
    """Test that event payload is preserved for all listeners despite failures."""
    # Create subscribers
    proxymem_subscriber = ProxyMemEosSubscriber(
        event_bus=event_bus, memory_service=mock_memory_service
    )
    usage_subscriber = UsageTrackingEosSubscriber(
        event_bus=event_bus, session_repository=mock_session_repo
    )

    await proxymem_subscriber.start()
    await usage_subscriber.start()

    # Make one subscriber fail
    mock_memory_service.mark_session_complete.side_effect = Exception("Memory error")

    # Create event with specific payload
    event = RemoteBackendConnectionEndOfSessionEvent(
        session_id="payload-test-123",
        signal_type=EndOfSessionSignalType.FINISH_REASON,
        termination_category=EndOfSessionTerminationCategory.NORMAL,
        reason="Test reason",
        backend="test-backend",
        protocol="test-protocol",
    )

    await event_bus.publish(event)

    # Give subscribers time to process
    async with FakeClockContext() as clock:
        sleep_task = asyncio.create_task(asyncio.sleep(0.01))
        clock.advance(0.01)  # Reduced from 0.1 for performance
        await sleep_task

    # Verify usage subscriber received correct payload despite other failure
    mock_session_repo.create.assert_called_once()
    call_args = mock_session_repo.create.call_args
    metrics: SessionMetricsTable = call_args[0][0]
    assert metrics.session_id == "payload-test-123"
    assert metrics.eos_signal_type == "finish_reason"
    assert metrics.eos_reason == "Test reason"


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_subscriber_non_blocking_under_load(
    event_bus: EventBus,
    mock_memory_service: IMemoryService,
    mock_session_repo: SessionMetricsRepository,
) -> None:
    """Test that subscriber failures don't block event processing under load."""
    # Create subscribers
    proxymem_subscriber = ProxyMemEosSubscriber(
        event_bus=event_bus, memory_service=mock_memory_service
    )
    usage_subscriber = UsageTrackingEosSubscriber(
        event_bus=event_bus, session_repository=mock_session_repo
    )

    await proxymem_subscriber.start()
    await usage_subscriber.start()

    # Make one subscriber fail intermittently
    call_count = 0

    def failing_side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count % 2 == 0:  # Fail every other call
            raise Exception("Intermittent error")

    mock_memory_service.mark_session_complete.side_effect = failing_side_effect

    # Publish multiple events
    events = [
        RemoteBackendConnectionEndOfSessionEvent(
            session_id=f"load-test-{i}",
            signal_type=EndOfSessionSignalType.DONE_SENTINEL,
            termination_category=EndOfSessionTerminationCategory.NORMAL,
        )
        for i in range(10)
    ]

    # Publish all events concurrently
    import asyncio

    await asyncio.gather(*[event_bus.publish(event) for event in events])

    # Give subscribers time to process
    async with FakeClockContext() as clock:
        sleep_task = asyncio.create_task(asyncio.sleep(0.01))
        clock.advance(0.01)  # Reduced from 0.2 for performance
        await sleep_task

    # Verify all events were processed (usage subscriber should have been called for all)
    assert mock_session_repo.create.call_count == 10
