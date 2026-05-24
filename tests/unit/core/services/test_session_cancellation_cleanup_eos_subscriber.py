"""Unit tests for SessionCancellationCleanupEosSubscriber."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from src.core.domain.events.end_of_session_events import (
    EndOfSessionSignalType,
    EndOfSessionTerminationCategory,
    RemoteBackendConnectionEndOfSessionEvent,
)
from src.core.domain.session_key import SessionKey
from src.core.interfaces.event_bus_interface import IEventBus
from src.core.interfaces.session_cancellation_coordinator_interface import (
    ISessionCancellationCoordinator,
)
from src.core.services.session_cancellation_cleanup_eos_subscriber import (
    SessionCancellationCleanupEosSubscriber,
)


@pytest.fixture
def mock_event_bus() -> IEventBus:
    """Create a mock event bus."""
    bus = MagicMock(spec=IEventBus)
    bus.subscribe = MagicMock()
    bus.unsubscribe = MagicMock()
    return bus


@pytest.fixture
def mock_coordinator() -> ISessionCancellationCoordinator:
    """Create a mock cancellation coordinator."""
    coordinator = MagicMock(spec=ISessionCancellationCoordinator)
    coordinator.cleanup = MagicMock()
    return coordinator


@pytest.fixture
def subscriber(
    mock_event_bus: IEventBus, mock_coordinator: ISessionCancellationCoordinator
) -> SessionCancellationCleanupEosSubscriber:
    """Create a SessionCancellationCleanupEosSubscriber instance."""
    return SessionCancellationCleanupEosSubscriber(
        event_bus=mock_event_bus, coordinator=mock_coordinator
    )


@pytest.mark.asyncio
async def test_subscriber_subscribes_on_start(
    subscriber: SessionCancellationCleanupEosSubscriber, mock_event_bus: IEventBus
) -> None:
    """Test that subscriber subscribes to EoS events on start."""
    await subscriber.start()

    mock_event_bus.subscribe.assert_called_once()
    call_args = mock_event_bus.subscribe.call_args
    assert call_args[0][0] == RemoteBackendConnectionEndOfSessionEvent
    assert call_args[0][1] == subscriber._handle_eos_event


@pytest.mark.asyncio
async def test_subscriber_unsubscribes_on_stop(
    subscriber: SessionCancellationCleanupEosSubscriber,
    mock_event_bus: IEventBus,
) -> None:
    """Test that subscriber unsubscribes from EoS events on stop."""
    await subscriber.start()
    await subscriber.stop()

    mock_event_bus.unsubscribe.assert_called_once()
    call_args = mock_event_bus.unsubscribe.call_args
    assert call_args[0][0] == RemoteBackendConnectionEndOfSessionEvent
    assert call_args[0][1] == subscriber._handle_eos_event


@pytest.mark.asyncio
async def test_handle_eos_event_calls_cleanup_for_http_session(
    subscriber: SessionCancellationCleanupEosSubscriber,
    mock_coordinator: ISessionCancellationCoordinator,
) -> None:
    """Test that handle_eos_event calls cleanup for HTTP session."""
    event = RemoteBackendConnectionEndOfSessionEvent(
        session_id="trace-abc123",
        signal_type=EndOfSessionSignalType.DONE_SENTINEL,
        termination_category=EndOfSessionTerminationCategory.NORMAL,
    )

    await subscriber._handle_eos_event(event)

    mock_coordinator.cleanup.assert_called_once()
    call_args = mock_coordinator.cleanup.call_args[0]
    session_key = call_args[0]
    assert isinstance(session_key, SessionKey)
    assert session_key.protocol == "http"
    assert session_key.primary_id == "trace-abc123"
    assert session_key.group_id is None


@pytest.mark.asyncio
async def test_handle_eos_event_calls_cleanup_for_codebuff_session(
    subscriber: SessionCancellationCleanupEosSubscriber,
    mock_coordinator: ISessionCancellationCoordinator,
) -> None:
    """Test that handle_eos_event calls cleanup for Codebuff session."""
    event = RemoteBackendConnectionEndOfSessionEvent(
        session_id="codebuff:ws-connection-456",
        signal_type=EndOfSessionSignalType.CLIENT_TERMINATION,
        termination_category=EndOfSessionTerminationCategory.NORMAL,
    )

    await subscriber._handle_eos_event(event)

    mock_coordinator.cleanup.assert_called_once()
    call_args = mock_coordinator.cleanup.call_args[0]
    session_key = call_args[0]
    assert isinstance(session_key, SessionKey)
    assert session_key.protocol == "codebuff"
    assert session_key.primary_id == "codebuff:ws-connection-456"
    assert session_key.group_id is None


@pytest.mark.asyncio
async def test_handle_eos_event_handles_missing_session_id(
    subscriber: SessionCancellationCleanupEosSubscriber,
    mock_coordinator: ISessionCancellationCoordinator,
) -> None:
    """Test that handle_eos_event handles missing session_id gracefully."""
    # Create a mock event with empty session_id (bypassing validation)
    # This tests the defensive check in the subscriber
    event = MagicMock(spec=RemoteBackendConnectionEndOfSessionEvent)
    event.session_id = ""

    await subscriber._handle_eos_event(event)

    mock_coordinator.cleanup.assert_not_called()


@pytest.mark.asyncio
async def test_handle_eos_event_handles_cleanup_exception(
    subscriber: SessionCancellationCleanupEosSubscriber,
    mock_coordinator: ISessionCancellationCoordinator,
) -> None:
    """Test that handle_eos_event handles cleanup exceptions gracefully."""
    event = RemoteBackendConnectionEndOfSessionEvent(
        session_id="trace-123",
        signal_type=EndOfSessionSignalType.DONE_SENTINEL,
        termination_category=EndOfSessionTerminationCategory.NORMAL,
    )

    # Make cleanup raise an exception
    mock_coordinator.cleanup.side_effect = ValueError("Cleanup failed")

    # Should not raise
    await subscriber._handle_eos_event(event)

    mock_coordinator.cleanup.assert_called_once()


@pytest.mark.asyncio
async def test_handle_eos_event_handles_session_key_creation_error(
    subscriber: SessionCancellationCleanupEosSubscriber,
    mock_coordinator: ISessionCancellationCoordinator,
) -> None:
    """Test that handle_eos_event handles SessionKey creation errors gracefully."""
    event = RemoteBackendConnectionEndOfSessionEvent(
        session_id="trace-123",
        signal_type=EndOfSessionSignalType.DONE_SENTINEL,
        termination_category=EndOfSessionTerminationCategory.NORMAL,
    )

    # Mock SessionKey to raise on creation
    import src.core.services.session_cancellation_cleanup_eos_subscriber as module

    original_session_key = module.SessionKey

    def failing_session_key(*args, **kwargs):
        raise ValueError("Invalid session key")

    module.SessionKey = failing_session_key

    try:
        # Should not raise
        await subscriber._handle_eos_event(event)
    finally:
        module.SessionKey = original_session_key

    # Cleanup should not have been called due to error
    mock_coordinator.cleanup.assert_not_called()
