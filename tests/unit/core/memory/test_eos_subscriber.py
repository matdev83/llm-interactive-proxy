"""Unit tests for ProxyMem EoS subscriber."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.domain.events.end_of_session_events import (
    EndOfSessionSignalType,
    EndOfSessionTerminationCategory,
    RemoteBackendConnectionEndOfSessionEvent,
)
from src.core.interfaces.event_bus_interface import IEventBus
from src.core.interfaces.memory_service_interface import IMemoryService
from src.core.memory.eos_subscriber import ProxyMemEosSubscriber


@pytest.fixture
def mock_event_bus() -> IEventBus:
    """Create a mock event bus."""
    bus = MagicMock(spec=IEventBus)
    bus.subscribe = MagicMock()
    return bus


@pytest.fixture
def mock_memory_service() -> IMemoryService:
    """Create a mock memory service."""
    service = AsyncMock(spec=IMemoryService)
    service.mark_session_complete = AsyncMock(return_value=True)
    service.is_enabled_for_session = AsyncMock(return_value=True)
    return service


@pytest.fixture
def subscriber(
    mock_event_bus: IEventBus, mock_memory_service: IMemoryService
) -> ProxyMemEosSubscriber:
    """Create a ProxyMemEosSubscriber instance."""
    return ProxyMemEosSubscriber(
        event_bus=mock_event_bus, memory_service=mock_memory_service
    )


@pytest.mark.asyncio
async def test_subscriber_subscribes_on_start(
    subscriber: ProxyMemEosSubscriber, mock_event_bus: IEventBus
) -> None:
    """Test that subscriber subscribes to EoS events on start."""
    await subscriber.start()

    mock_event_bus.subscribe.assert_called_once()
    call_args = mock_event_bus.subscribe.call_args
    assert call_args[0][0] == RemoteBackendConnectionEndOfSessionEvent
    assert call_args[0][1] == subscriber._handle_eos_event


@pytest.mark.asyncio
async def test_handle_eos_event_calls_mark_session_complete(
    subscriber: ProxyMemEosSubscriber, mock_memory_service: IMemoryService
) -> None:
    """Test that handler calls mark_session_complete with correct parameters."""
    event = RemoteBackendConnectionEndOfSessionEvent(
        session_id="test-session-123",
        signal_type=EndOfSessionSignalType.DONE_SENTINEL,
        termination_category=EndOfSessionTerminationCategory.NORMAL,
        backend="openai:gpt-4",
    )

    await subscriber._handle_eos_event(event)

    mock_memory_service.mark_session_complete.assert_called_once_with(
        "test-session-123",
        backend_model="openai:gpt-4",
        termination_reason=None,
    )


@pytest.mark.asyncio
async def test_handle_eos_event_idempotent_on_repeated_calls(
    subscriber: ProxyMemEosSubscriber, mock_memory_service: IMemoryService
) -> None:
    """Test that handler is idempotent (mark_session_complete handles dedupe)."""
    event = RemoteBackendConnectionEndOfSessionEvent(
        session_id="test-session-123",
        signal_type=EndOfSessionSignalType.DONE_SENTINEL,
        termination_category=EndOfSessionTerminationCategory.NORMAL,
    )

    # First call
    await subscriber._handle_eos_event(event)
    # Second call (should still call mark_session_complete, but it will return False)
    mock_memory_service.mark_session_complete.return_value = False
    await subscriber._handle_eos_event(event)

    assert mock_memory_service.mark_session_complete.call_count == 2


@pytest.mark.asyncio
async def test_handle_eos_event_without_backend_model(
    subscriber: ProxyMemEosSubscriber, mock_memory_service: IMemoryService
) -> None:
    """Test that handler works when backend model is not provided."""
    event = RemoteBackendConnectionEndOfSessionEvent(
        session_id="test-session-123",
        signal_type=EndOfSessionSignalType.DONE_SENTINEL,
        termination_category=EndOfSessionTerminationCategory.NORMAL,
        backend=None,
    )

    await subscriber._handle_eos_event(event)

    mock_memory_service.mark_session_complete.assert_called_once_with(
        "test-session-123",
        backend_model=None,
        termination_reason=None,
    )


@pytest.mark.asyncio
async def test_handle_eos_event_extracts_backend_model_from_backend_field(
    subscriber: ProxyMemEosSubscriber, mock_memory_service: IMemoryService
) -> None:
    """Test that handler extracts backend:model from backend field."""
    event = RemoteBackendConnectionEndOfSessionEvent(
        session_id="test-session-123",
        signal_type=EndOfSessionSignalType.DONE_SENTINEL,
        termination_category=EndOfSessionTerminationCategory.NORMAL,
        backend="anthropic:claude-3-opus",
    )

    await subscriber._handle_eos_event(event)

    mock_memory_service.mark_session_complete.assert_called_once_with(
        "test-session-123",
        backend_model="anthropic:claude-3-opus",
        termination_reason=None,
    )


@pytest.mark.asyncio
async def test_handle_eos_event_handles_service_failure_gracefully(
    subscriber: ProxyMemEosSubscriber, mock_memory_service: IMemoryService
) -> None:
    """Test that handler handles service failures gracefully."""
    event = RemoteBackendConnectionEndOfSessionEvent(
        session_id="test-session-123",
        signal_type=EndOfSessionSignalType.DONE_SENTINEL,
        termination_category=EndOfSessionTerminationCategory.NORMAL,
    )

    mock_memory_service.mark_session_complete.side_effect = Exception("Service error")

    # Should not raise exception (fail-open behavior)
    await subscriber._handle_eos_event(event)

    mock_memory_service.mark_session_complete.assert_called_once()


@pytest.mark.asyncio
async def test_handle_eos_event_skips_when_memory_not_enabled(
    subscriber: ProxyMemEosSubscriber, mock_memory_service: IMemoryService
) -> None:
    """Test that handler skips when memory is not enabled for session."""
    event = RemoteBackendConnectionEndOfSessionEvent(
        session_id="test-session-123",
        signal_type=EndOfSessionSignalType.DONE_SENTINEL,
        termination_category=EndOfSessionTerminationCategory.NORMAL,
    )

    mock_memory_service.is_enabled_for_session.return_value = False

    await subscriber._handle_eos_event(event)

    # Should check if enabled but not call mark_session_complete
    mock_memory_service.is_enabled_for_session.assert_called_once_with(
        "test-session-123"
    )
    mock_memory_service.mark_session_complete.assert_not_called()


@pytest.mark.asyncio
async def test_subscriber_unsubscribes_on_stop(
    subscriber: ProxyMemEosSubscriber, mock_event_bus: IEventBus
) -> None:
    """Test that subscriber unsubscribes from EoS events on stop."""
    await subscriber.start()
    await subscriber.stop()

    mock_event_bus.unsubscribe.assert_called_once()
    call_args = mock_event_bus.unsubscribe.call_args
    assert call_args[0][0] == RemoteBackendConnectionEndOfSessionEvent
    assert call_args[0][1] == subscriber._handle_eos_event


@pytest.mark.asyncio
async def test_handle_eos_event_passes_termination_reason(
    subscriber: ProxyMemEosSubscriber, mock_memory_service: IMemoryService
) -> None:
    """Test that handler passes termination reason from event to mark_session_complete."""
    event = RemoteBackendConnectionEndOfSessionEvent(
        session_id="test-session-123",
        signal_type=EndOfSessionSignalType.CLIENT_TERMINATION,
        termination_category=EndOfSessionTerminationCategory.NORMAL,
        backend="openai:gpt-4",
        reason="client_disconnected",
    )

    await subscriber._handle_eos_event(event)

    mock_memory_service.mark_session_complete.assert_called_once_with(
        "test-session-123",
        backend_model="openai:gpt-4",
        termination_reason="client_disconnected",
    )
