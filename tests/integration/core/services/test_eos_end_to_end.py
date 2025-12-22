"""End-to-end integration tests for End-of-Session event emission.

These tests verify complete EoS emission flows including:
- Streaming and non-streaming EoS emission with persistence
- Error-driven EoS emission for backend/transport failures
- Multiple listeners receiving events
- DB persistence of EoS completion state
- Event payload correctness end-to-end
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.config.models.end_of_session import EndOfSessionConfig
from src.core.database.models.usage import SessionMetricsTable
from src.core.database.repositories.usage_repository import SessionMetricsRepository
from src.core.domain.events.end_of_session_events import (
    EndOfSessionErrorClassification,
    EndOfSessionSignal,
    EndOfSessionSignalType,
    EndOfSessionTerminationCategory,
    RemoteBackendConnectionEndOfSessionEvent,
)
from src.core.domain.streaming.streaming_content import StreamingContent
from src.core.interfaces.memory_service_interface import IMemoryService
from src.core.interfaces.wire_capture_interface import IWireCapture
from src.core.memory.eos_subscriber import ProxyMemEosSubscriber
from src.core.services.end_of_session_service import EndOfSessionService
from src.core.services.event_bus import EventBus
from src.core.services.streaming.end_of_session_stream_processor import (
    EndOfSessionStreamProcessor,
)
from src.core.services.usage_tracking_eos_subscriber import UsageTrackingEosSubscriber
from src.core.services.wire_capture_eos_subscriber import WireCaptureEosSubscriber
from src.services.test_execution_reminder.eos_subscriber import (
    TestExecutionReminderEosSubscriber,
)
from src.services.test_execution_reminder.test_execution_reminder_handler import (
    TestExecutionReminderHandler,
)


@pytest.fixture
def event_bus() -> EventBus:
    """Create a real EventBus instance."""
    return EventBus()


@pytest.fixture
def mock_session_repo() -> SessionMetricsRepository:
    """Create a mock session metrics repository."""
    repo = AsyncMock(spec=SessionMetricsRepository)
    repo.claim_eos_emission = AsyncMock(return_value=True)
    repo.has_ended = AsyncMock(return_value=False)
    repo.get_by_id = AsyncMock(return_value=None)
    repo.create = AsyncMock()
    repo.update = AsyncMock()
    return repo


@pytest.fixture
def mock_memory_service() -> IMemoryService:
    """Create a mock memory service."""
    service = AsyncMock(spec=IMemoryService)
    service.mark_session_complete = AsyncMock(return_value=True)
    return service


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
def eos_config() -> EndOfSessionConfig:
    """Create EoS configuration."""
    return EndOfSessionConfig(
        enabled=True,
        emit_events=True,
        detect_stream_signals=True,
        detect_tool_completion=True,
        dispatch_timeout_seconds=5.0,
    )


@pytest.fixture
def eos_service(
    event_bus: EventBus,
    eos_config: EndOfSessionConfig,
    mock_session_repo: SessionMetricsRepository,
) -> EndOfSessionService:
    """Create EndOfSessionService instance."""
    return EndOfSessionService(
        event_bus=event_bus,
        config=eos_config,
        session_repository=mock_session_repo,
    )


@pytest.fixture
def stream_processor(
    eos_service: EndOfSessionService, eos_config: EndOfSessionConfig
) -> EndOfSessionStreamProcessor:
    """Create EndOfSessionStreamProcessor instance."""
    return EndOfSessionStreamProcessor(
        end_of_session_service=eos_service,
        config=eos_config,
    )


@pytest.fixture
async def all_subscribers(
    event_bus: EventBus,
    mock_memory_service: IMemoryService,
    mock_session_repo: SessionMetricsRepository,
    mock_wire_capture: IWireCapture,
    mock_reminder_handler: TestExecutionReminderHandler,
) -> tuple[
    ProxyMemEosSubscriber,
    UsageTrackingEosSubscriber,
    WireCaptureEosSubscriber,
    TestExecutionReminderEosSubscriber,
]:
    """Create and start all EoS subscribers."""
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

    return proxymem, usage, wire_capture, reminder


@pytest.mark.asyncio
async def test_streaming_eos_emission_with_persistence(
    stream_processor: EndOfSessionStreamProcessor,
    eos_service: EndOfSessionService,
    mock_session_repo: SessionMetricsRepository,
    event_bus: EventBus,
    all_subscribers: tuple,
) -> None:
    """Test that streaming EoS emission persists completion state."""
    session_id = "streaming-session-123"
    events_received: list[RemoteBackendConnectionEndOfSessionEvent] = []

    # Capture events
    async def event_handler(event: RemoteBackendConnectionEndOfSessionEvent) -> None:
        events_received.append(event)

    event_bus.subscribe(RemoteBackendConnectionEndOfSessionEvent, event_handler)

    # Process streaming content with completion marker
    content = StreamingContent(
        content="test content",
        metadata={
            "session_id": session_id,
            "protocol": "openai",
            "backend_name": "openai",
        },
        is_done=True,
    )

    result = await stream_processor.process(content)

    # Give time for event processing
    await asyncio.sleep(0.1)

    # Verify event was emitted
    assert len(events_received) == 1
    event = events_received[0]
    assert event.session_id == session_id
    assert event.signal_type == EndOfSessionSignalType.DONE_SENTINEL
    assert event.termination_category == EndOfSessionTerminationCategory.NORMAL

    # Verify persistence was attempted
    mock_session_repo.claim_eos_emission.assert_awaited_once()
    call_kwargs = mock_session_repo.claim_eos_emission.call_args.kwargs
    assert call_kwargs["session_id"] == session_id
    assert call_kwargs["signal_type"] == "done_sentinel"

    # Verify content unchanged
    assert result == content


@pytest.mark.asyncio
async def test_non_streaming_eos_emission_with_persistence(
    eos_service: EndOfSessionService,
    mock_session_repo: SessionMetricsRepository,
    event_bus: EventBus,
    all_subscribers: tuple,
) -> None:
    """Test that non-streaming EoS emission persists completion state."""
    session_id = "non-streaming-session-456"
    events_received: list[RemoteBackendConnectionEndOfSessionEvent] = []

    # Capture events
    async def event_handler(event: RemoteBackendConnectionEndOfSessionEvent) -> None:
        events_received.append(event)

    event_bus.subscribe(RemoteBackendConnectionEndOfSessionEvent, event_handler)

    # Create signal for non-streaming completion
    signal = EndOfSessionSignal(
        session_id=session_id,
        signal_type=EndOfSessionSignalType.FINISH_REASON,
        termination_category=EndOfSessionTerminationCategory.NORMAL,
        observed_at=datetime.now(timezone.utc),
        reason="finish_reason: stop",
        protocol="openai",
        backend="openai",
    )

    await eos_service.record_signal(signal)

    # Give time for event processing
    await asyncio.sleep(0.1)

    # Verify event was emitted
    assert len(events_received) == 1
    event = events_received[0]
    assert event.session_id == session_id
    assert event.signal_type == EndOfSessionSignalType.FINISH_REASON

    # Verify persistence was attempted
    mock_session_repo.claim_eos_emission.assert_awaited_once()


@pytest.mark.asyncio
async def test_error_driven_eos_emission(
    eos_service: EndOfSessionService,
    mock_session_repo: SessionMetricsRepository,
    event_bus: EventBus,
    all_subscribers: tuple,
) -> None:
    """Test that error-driven EoS emission works for backend/transport failures."""
    session_id = "error-session-789"
    events_received: list[RemoteBackendConnectionEndOfSessionEvent] = []

    # Capture events
    async def event_handler(event: RemoteBackendConnectionEndOfSessionEvent) -> None:
        events_received.append(event)

    event_bus.subscribe(RemoteBackendConnectionEndOfSessionEvent, event_handler)

    # Create error termination signal
    signal = EndOfSessionSignal(
        session_id=session_id,
        signal_type=EndOfSessionSignalType.ERROR_TERMINATION,
        termination_category=EndOfSessionTerminationCategory.ERROR,
        observed_at=datetime.now(timezone.utc),
        reason="Connection timeout",
        error_classification=EndOfSessionErrorClassification.TRANSPORT_ERROR,
        error_status_code=504,
        backend="openai",
    )

    await eos_service.record_signal(signal)

    # Give time for event processing
    await asyncio.sleep(0.1)

    # Verify event was emitted with error classification
    assert len(events_received) == 1
    event = events_received[0]
    assert event.session_id == session_id
    assert event.termination_category == EndOfSessionTerminationCategory.ERROR
    assert event.error_classification == EndOfSessionErrorClassification.TRANSPORT_ERROR
    assert event.error_status_code == 504

    # Verify persistence was attempted
    mock_session_repo.claim_eos_emission.assert_awaited_once()


@pytest.mark.asyncio
async def test_multiple_listeners_receive_events(
    eos_service: EndOfSessionService,
    event_bus: EventBus,
    mock_memory_service: IMemoryService,
    mock_session_repo: SessionMetricsRepository,
    mock_wire_capture: IWireCapture,
    mock_reminder_handler: TestExecutionReminderHandler,
) -> None:
    """Test that multiple listeners receive the same event."""
    session_id = "multi-listener-session-999"

    # Create and start subscribers
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

    # Create signal
    signal = EndOfSessionSignal(
        session_id=session_id,
        signal_type=EndOfSessionSignalType.DONE_SENTINEL,
        termination_category=EndOfSessionTerminationCategory.NORMAL,
        observed_at=datetime.now(timezone.utc),
        backend="openai:gpt-4",
    )

    await eos_service.record_signal(signal)

    # Give time for event processing
    await asyncio.sleep(0.1)

    # Verify all subscribers received the event
    mock_memory_service.mark_session_complete.assert_called_once_with(
        session_id, backend_model="openai:gpt-4"
    )
    mock_session_repo.create.assert_called_once()
    mock_wire_capture.capture_stream_completion.assert_called_once()
    mock_reminder_handler._get_session_state.assert_called_once_with(session_id)


@pytest.mark.asyncio
async def test_db_persistence_eos_completion_state(
    eos_service: EndOfSessionService,
    mock_session_repo: SessionMetricsRepository,
    event_bus: EventBus,
) -> None:
    """Test that EoS completion state is persisted in database."""
    session_id = "persistence-session-111"

    # Create signal
    signal = EndOfSessionSignal(
        session_id=session_id,
        signal_type=EndOfSessionSignalType.RESPONSE_COMPLETED,
        termination_category=EndOfSessionTerminationCategory.NORMAL,
        observed_at=datetime.now(timezone.utc),
        reason="Response completed",
        protocol="anthropic",
        backend="anthropic",
    )

    await eos_service.record_signal(signal)

    # Verify claim was called with correct parameters
    mock_session_repo.claim_eos_emission.assert_awaited_once()
    call_kwargs = mock_session_repo.claim_eos_emission.call_args.kwargs
    assert call_kwargs["session_id"] == session_id
    assert call_kwargs["signal_type"] == "response_completed"
    assert call_kwargs["reason"] == "Response completed"
    assert call_kwargs["emitted_at"] is not None


@pytest.mark.asyncio
async def test_event_payload_correctness_end_to_end(
    stream_processor: EndOfSessionStreamProcessor,
    eos_service: EndOfSessionService,
    event_bus: EventBus,
) -> None:
    """Test that event payload is correct end-to-end."""
    session_id = "payload-session-222"
    events_received: list[RemoteBackendConnectionEndOfSessionEvent] = []

    # Capture events
    async def event_handler(event: RemoteBackendConnectionEndOfSessionEvent) -> None:
        events_received.append(event)

    event_bus.subscribe(RemoteBackendConnectionEndOfSessionEvent, event_handler)

    # Process content with full metadata
    content = StreamingContent(
        content="test",
        metadata={
            "session_id": session_id,
            "protocol": "openai",
            "backend_name": "openai",
            "request_id": "req-123",
            "finish_reason": "stop",
        },
        is_done=False,  # Use finish_reason instead
    )

    await stream_processor.process(content)

    # Give time for event processing
    await asyncio.sleep(0.1)

    # Verify event payload correctness
    assert len(events_received) == 1
    event = events_received[0]
    assert event.session_id == session_id
    assert event.signal_type == EndOfSessionSignalType.FINISH_REASON
    assert event.protocol == "openai"
    assert event.backend == "openai"
    assert event.request_id == "req-123"
    assert "stop" in (event.reason or "")


@pytest.mark.asyncio
async def test_error_classification_defaults_to_unknown(
    eos_service: EndOfSessionService,
    event_bus: EventBus,
) -> None:
    """Test that missing error classification defaults to unknown_error."""
    session_id = "error-default-session-333"
    events_received: list[RemoteBackendConnectionEndOfSessionEvent] = []

    # Capture events
    async def event_handler(event: RemoteBackendConnectionEndOfSessionEvent) -> None:
        events_received.append(event)

    event_bus.subscribe(RemoteBackendConnectionEndOfSessionEvent, event_handler)

    # Create error signal without classification
    signal = EndOfSessionSignal(
        session_id=session_id,
        signal_type=EndOfSessionSignalType.ERROR_TERMINATION,
        termination_category=EndOfSessionTerminationCategory.ERROR,
        observed_at=datetime.now(timezone.utc),
        reason="Unknown error",
        error_classification=None,  # Missing classification
    )

    await eos_service.record_signal(signal)

    # Give time for event processing
    await asyncio.sleep(0.1)

    # Verify default classification
    assert len(events_received) == 1
    event = events_received[0]
    assert event.error_classification == EndOfSessionErrorClassification.UNKNOWN_ERROR


@pytest.mark.asyncio
async def test_client_termination_reason_flows_to_subscribers(
    eos_service: EndOfSessionService,
    mock_session_repo: SessionMetricsRepository,
    event_bus: EventBus,
    all_subscribers: tuple,
    mock_wire_capture: IWireCapture,
) -> None:
    """Test that client termination reason flows through to usage tracking and wire capture.

    Requirement 5.1, 5.2: Usage tracking and wire capture should finalize with
    client termination reason on End-of-Session.
    """
    session_id = "client-termination-session-456"
    events_received: list[RemoteBackendConnectionEndOfSessionEvent] = []

    # Capture events
    async def event_handler(event: RemoteBackendConnectionEndOfSessionEvent) -> None:
        events_received.append(event)

    event_bus.subscribe(RemoteBackendConnectionEndOfSessionEvent, event_handler)

    # Create client termination signal
    signal = EndOfSessionSignal(
        session_id=session_id,
        signal_type=EndOfSessionSignalType.CLIENT_TERMINATION,
        termination_category=EndOfSessionTerminationCategory.NORMAL,
        observed_at=datetime.now(timezone.utc),
        reason="client_disconnected",
        backend="openai:gpt-4",
    )

    await eos_service.record_signal(signal)

    # Give time for event processing
    await asyncio.sleep(0.1)

    # Verify event was emitted with client termination reason
    assert len(events_received) == 1
    event = events_received[0]
    assert event.session_id == session_id
    assert event.signal_type == EndOfSessionSignalType.CLIENT_TERMINATION
    assert event.termination_category == EndOfSessionTerminationCategory.NORMAL
    assert event.reason == "client_disconnected"

    # Verify usage tracking subscriber recorded the reason
    # Check if update was called (for existing metrics) or create was called (for new metrics)
    update_called = mock_session_repo.update.called
    create_called = mock_session_repo.create.called
    assert (
        update_called or create_called
    ), "Session metrics should be updated or created"

    if update_called:
        # Verify update call includes termination reason
        update_call_args = mock_session_repo.update.call_args
        metrics: SessionMetricsTable = update_call_args[0][0]
        assert metrics.eos_reason == "client_disconnected"
        assert metrics.eos_signal_type == "client_termination"
    elif create_called:
        # Verify create call includes termination reason
        create_call_args = mock_session_repo.create.call_args
        metrics: SessionMetricsTable = create_call_args[0][0]
        assert metrics.eos_reason == "client_disconnected"
        assert metrics.eos_signal_type == "client_termination"

    # Verify wire capture subscriber recorded the reason
    mock_wire_capture.capture_stream_completion.assert_called_once()
    capture_call_args = mock_wire_capture.capture_stream_completion.call_args
    eos_metadata = capture_call_args.kwargs.get("eos_metadata", {})
    assert eos_metadata.get("eos_reason") == "client_disconnected"
    assert eos_metadata.get("eos_signal") == "client_termination"
    assert eos_metadata.get("eos_termination_category") == "normal"
