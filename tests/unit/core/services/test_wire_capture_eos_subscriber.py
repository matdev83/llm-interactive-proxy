"""Unit tests for Wire Capture EoS subscriber."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.domain.events.end_of_session_events import (
    EndOfSessionErrorClassification,
    EndOfSessionSignalType,
    EndOfSessionTerminationCategory,
    RemoteBackendConnectionEndOfSessionEvent,
)
from src.core.interfaces.event_bus_interface import IEventBus
from src.core.interfaces.wire_capture_interface import IWireCapture
from src.core.services.wire_capture_eos_subscriber import WireCaptureEosSubscriber


@pytest.fixture
def mock_event_bus() -> IEventBus:
    """Create a mock event bus."""
    bus = MagicMock(spec=IEventBus)
    bus.subscribe = MagicMock()
    return bus


@pytest.fixture
def mock_wire_capture() -> IWireCapture:
    """Create a mock wire capture service."""
    capture = AsyncMock(spec=IWireCapture)
    capture.enabled = MagicMock(return_value=True)
    capture.capture_stream_completion = AsyncMock()
    return capture


@pytest.fixture
def subscriber(
    mock_event_bus: IEventBus, mock_wire_capture: IWireCapture
) -> WireCaptureEosSubscriber:
    """Create a WireCaptureEosSubscriber instance."""
    return WireCaptureEosSubscriber(
        event_bus=mock_event_bus, wire_capture=mock_wire_capture
    )


@pytest.mark.asyncio
async def test_subscriber_subscribes_on_start(
    subscriber: WireCaptureEosSubscriber, mock_event_bus: IEventBus
) -> None:
    """Test that subscriber subscribes to EoS events on start."""
    await subscriber.start()

    mock_event_bus.subscribe.assert_called_once()
    call_args = mock_event_bus.subscribe.call_args
    assert call_args[0][0] == RemoteBackendConnectionEndOfSessionEvent
    assert call_args[0][1] == subscriber._handle_eos_event


@pytest.mark.asyncio
async def test_handle_eos_event_records_eos_metadata(
    subscriber: WireCaptureEosSubscriber, mock_wire_capture: IWireCapture
) -> None:
    """Test that handler records EoS metadata in wire capture."""
    event = RemoteBackendConnectionEndOfSessionEvent(
        session_id="test-session-123",
        signal_type=EndOfSessionSignalType.DONE_SENTINEL,
        termination_category=EndOfSessionTerminationCategory.NORMAL,
        backend="openai:gpt-4",
    )

    await subscriber._handle_eos_event(event)

    mock_wire_capture.capture_stream_completion.assert_called_once()
    call_args = mock_wire_capture.capture_stream_completion.call_args
    assert call_args[1]["session_id"] == "test-session-123"
    assert call_args[1]["backend"] == "openai"
    assert call_args[1]["model"] == "gpt-4"


@pytest.mark.asyncio
async def test_handle_eos_event_skips_when_capture_disabled(
    subscriber: WireCaptureEosSubscriber, mock_wire_capture: IWireCapture
) -> None:
    """Test that handler skips recording when wire capture is disabled."""
    event = RemoteBackendConnectionEndOfSessionEvent(
        session_id="test-session-123",
        signal_type=EndOfSessionSignalType.DONE_SENTINEL,
        termination_category=EndOfSessionTerminationCategory.NORMAL,
    )

    mock_wire_capture.enabled.return_value = False

    await subscriber._handle_eos_event(event)

    mock_wire_capture.capture_stream_completion.assert_not_called()


@pytest.mark.asyncio
async def test_handle_eos_event_handles_service_failure_gracefully(
    subscriber: WireCaptureEosSubscriber, mock_wire_capture: IWireCapture
) -> None:
    """Test that handler handles service failures gracefully."""
    event = RemoteBackendConnectionEndOfSessionEvent(
        session_id="test-session-123",
        signal_type=EndOfSessionSignalType.DONE_SENTINEL,
        termination_category=EndOfSessionTerminationCategory.NORMAL,
    )

    mock_wire_capture.capture_stream_completion.side_effect = Exception("Capture error")

    # Should not raise exception (fail-open behavior)
    await subscriber._handle_eos_event(event)

    mock_wire_capture.capture_stream_completion.assert_called_once()


@pytest.mark.asyncio
async def test_handle_eos_event_records_eos_metadata_with_error(
    subscriber: WireCaptureEosSubscriber, mock_wire_capture: IWireCapture
) -> None:
    """Test that handler records EoS metadata including error fields."""
    event = RemoteBackendConnectionEndOfSessionEvent(
        session_id="test-session-123",
        signal_type=EndOfSessionSignalType.ERROR_TERMINATION,
        termination_category=EndOfSessionTerminationCategory.ERROR,
        reason="Connection timeout",
        error_classification=EndOfSessionErrorClassification.TRANSPORT_ERROR,
        error_status_code=504,
        backend="openai:gpt-4",
    )

    await subscriber._handle_eos_event(event)

    mock_wire_capture.capture_stream_completion.assert_called_once()
    call_args = mock_wire_capture.capture_stream_completion.call_args
    eos_metadata = call_args[1]["eos_metadata"]
    assert eos_metadata["eos"] is True
    assert eos_metadata["eos_signal"] == "error_termination"
    assert eos_metadata["eos_reason"] == "Connection timeout"
    assert eos_metadata["eos_termination_category"] == "error"
    assert eos_metadata["eos_error_classification"] == "transport_error"
    assert eos_metadata["eos_error_status_code"] == 504


@pytest.mark.asyncio
async def test_subscriber_unsubscribes_on_stop(
    subscriber: WireCaptureEosSubscriber, mock_event_bus: IEventBus
) -> None:
    """Test that subscriber unsubscribes from EoS events on stop."""
    await subscriber.start()
    await subscriber.stop()

    mock_event_bus.unsubscribe.assert_called_once()
    call_args = mock_event_bus.unsubscribe.call_args
    assert call_args[0][0] == RemoteBackendConnectionEndOfSessionEvent
    assert call_args[0][1] == subscriber._handle_eos_event
