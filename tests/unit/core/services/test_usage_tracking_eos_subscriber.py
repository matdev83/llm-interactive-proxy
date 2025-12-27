"""Unit tests for Usage Tracking EoS subscriber."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from freezegun import freeze_time
from src.core.database.models.usage import SessionMetricsTable
from src.core.database.repositories.usage_repository import SessionMetricsRepository
from src.core.domain.events.end_of_session_events import (
    EndOfSessionErrorClassification,
    EndOfSessionSignalType,
    EndOfSessionTerminationCategory,
    RemoteBackendConnectionEndOfSessionEvent,
)
from src.core.interfaces.event_bus_interface import IEventBus
from src.core.services.usage_tracking_eos_subscriber import UsageTrackingEosSubscriber


@pytest.fixture
def mock_event_bus() -> IEventBus:
    """Create a mock event bus."""
    bus = MagicMock(spec=IEventBus)
    bus.subscribe = MagicMock()
    return bus


@pytest.fixture
def mock_session_repo() -> SessionMetricsRepository:
    """Create a mock session metrics repository."""
    repo = AsyncMock(spec=SessionMetricsRepository)
    repo.get_by_id = AsyncMock(return_value=None)
    repo.update = AsyncMock()
    repo.create = AsyncMock()
    return repo


@pytest.fixture
def subscriber(
    mock_event_bus: IEventBus, mock_session_repo: SessionMetricsRepository
) -> UsageTrackingEosSubscriber:
    """Create a UsageTrackingEosSubscriber instance."""
    return UsageTrackingEosSubscriber(
        event_bus=mock_event_bus, session_repository=mock_session_repo
    )


@pytest.mark.asyncio
async def test_subscriber_subscribes_on_start(
    subscriber: UsageTrackingEosSubscriber, mock_event_bus: IEventBus
) -> None:
    """Test that subscriber subscribes to EoS events on start."""
    await subscriber.start()

    mock_event_bus.subscribe.assert_called_once()
    call_args = mock_event_bus.subscribe.call_args
    assert call_args[0][0] == RemoteBackendConnectionEndOfSessionEvent
    assert call_args[0][1] == subscriber._handle_eos_event


@pytest.mark.asyncio
async def test_handle_eos_event_updates_session_metrics(
    subscriber: UsageTrackingEosSubscriber, mock_session_repo: SessionMetricsRepository
) -> None:
    """Test that handler updates session metrics with EoS data."""
    event = RemoteBackendConnectionEndOfSessionEvent(
        session_id="test-session-123",
        signal_type=EndOfSessionSignalType.DONE_SENTINEL,
        termination_category=EndOfSessionTerminationCategory.NORMAL,
        reason="Stream completed",
    )

    await subscriber._handle_eos_event(event)

    # Should create new metrics since get_by_id returns None
    mock_session_repo.create.assert_called_once()
    call_args = mock_session_repo.create.call_args
    metrics: SessionMetricsTable = call_args[0][0]
    assert metrics.session_id == "test-session-123"
    assert metrics.is_completed is True
    assert metrics.eos_signal_type == "done_sentinel"
    assert metrics.eos_reason == "Stream completed"
    assert metrics.eos_emitted_at is not None


@pytest.mark.asyncio
@freeze_time("2024-01-01 12:00:00")
async def test_handle_eos_event_preserves_existing_metrics(
    subscriber: UsageTrackingEosSubscriber, mock_session_repo: SessionMetricsRepository
) -> None:
    """Test that handler preserves existing metrics when updating."""
    event = RemoteBackendConnectionEndOfSessionEvent(
        session_id="test-session-123",
        signal_type=EndOfSessionSignalType.DONE_SENTINEL,
        termination_category=EndOfSessionTerminationCategory.NORMAL,
        reason="Stream completed",
    )

    # Create existing metrics
    fixed_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    existing_metrics = SessionMetricsTable(
        session_id="test-session-123",
        start_time=fixed_time,
        last_activity=fixed_time,
        turn_count=5,
        total_tokens=1000,
        total_tool_calls=3,
        is_completed=False,
    )
    mock_session_repo.get_by_id.return_value = existing_metrics

    await subscriber._handle_eos_event(event)

    # Should update existing metrics, not create new ones
    mock_session_repo.update.assert_called_once()
    call_args = mock_session_repo.update.call_args
    updated_metrics: SessionMetricsTable = call_args[0][0]
    assert updated_metrics.session_id == "test-session-123"
    assert updated_metrics.is_completed is True
    assert updated_metrics.eos_signal_type == "done_sentinel"
    assert updated_metrics.eos_reason == "Stream completed"
    # Preserve existing fields
    assert updated_metrics.turn_count == 5
    assert updated_metrics.total_tokens == 1000
    assert updated_metrics.total_tool_calls == 3
    # Should not create new metrics
    mock_session_repo.create.assert_not_called()


@pytest.mark.asyncio
async def test_handle_eos_event_with_error_termination(
    subscriber: UsageTrackingEosSubscriber, mock_session_repo: SessionMetricsRepository
) -> None:
    """Test that handler records error termination correctly."""
    event = RemoteBackendConnectionEndOfSessionEvent(
        session_id="test-session-123",
        signal_type=EndOfSessionSignalType.ERROR_TERMINATION,
        termination_category=EndOfSessionTerminationCategory.ERROR,
        reason="Connection timeout",
        error_classification=EndOfSessionErrorClassification.TRANSPORT_ERROR,
        error_status_code=504,
    )

    await subscriber._handle_eos_event(event)

    # Should create new metrics since get_by_id returns None
    mock_session_repo.create.assert_called_once()
    call_args = mock_session_repo.create.call_args
    metrics: SessionMetricsTable = call_args[0][0]
    assert metrics.session_id == "test-session-123"
    assert metrics.is_completed is True
    assert metrics.eos_signal_type == "error_termination"
    assert metrics.eos_reason == "Connection timeout"
    assert metrics.eos_error_classification == "transport_error"
    assert metrics.eos_error_status_code == 504


@pytest.mark.asyncio
@freeze_time("2024-01-01 12:00:00")
async def test_handle_eos_event_with_error_termination_updates_existing(
    subscriber: UsageTrackingEosSubscriber, mock_session_repo: SessionMetricsRepository
) -> None:
    """Test that handler updates existing metrics with error fields."""
    event = RemoteBackendConnectionEndOfSessionEvent(
        session_id="test-session-123",
        signal_type=EndOfSessionSignalType.ERROR_TERMINATION,
        termination_category=EndOfSessionTerminationCategory.ERROR,
        reason="HTTP 500 error",
        error_classification=EndOfSessionErrorClassification.HTTP_ERROR,
        error_status_code=500,
    )

    # Create existing metrics
    fixed_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    existing_metrics = SessionMetricsTable(
        session_id="test-session-123",
        start_time=fixed_time,
        last_activity=fixed_time,
        turn_count=5,
        total_tokens=1000,
        total_tool_calls=3,
        is_completed=False,
    )
    mock_session_repo.get_by_id.return_value = existing_metrics

    await subscriber._handle_eos_event(event)

    # Should update existing metrics
    mock_session_repo.update.assert_called_once()
    call_args = mock_session_repo.update.call_args
    updated_metrics: SessionMetricsTable = call_args[0][0]
    assert updated_metrics.eos_error_classification == "http_error"
    assert updated_metrics.eos_error_status_code == 500


@pytest.mark.asyncio
@freeze_time("2024-01-01 12:00:00")
async def test_handle_eos_event_clears_error_fields_for_normal_termination(
    subscriber: UsageTrackingEosSubscriber, mock_session_repo: SessionMetricsRepository
) -> None:
    """Test that handler clears error fields for normal terminations."""
    # First, create metrics with error fields
    fixed_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    existing_metrics = SessionMetricsTable(
        session_id="test-session-123",
        start_time=fixed_time,
        last_activity=fixed_time,
        turn_count=5,
        total_tokens=1000,
        total_tool_calls=3,
        is_completed=False,
        eos_error_classification="transport_error",
        eos_error_status_code=504,
    )
    mock_session_repo.get_by_id.return_value = existing_metrics

    # Now send a normal termination event
    event = RemoteBackendConnectionEndOfSessionEvent(
        session_id="test-session-123",
        signal_type=EndOfSessionSignalType.DONE_SENTINEL,
        termination_category=EndOfSessionTerminationCategory.NORMAL,
        reason="Stream completed",
    )

    await subscriber._handle_eos_event(event)

    # Should update and clear error fields
    mock_session_repo.update.assert_called_once()
    call_args = mock_session_repo.update.call_args
    updated_metrics: SessionMetricsTable = call_args[0][0]
    assert updated_metrics.eos_error_classification is None
    assert updated_metrics.eos_error_status_code is None


@pytest.mark.asyncio
async def test_subscriber_unsubscribes_on_stop(
    subscriber: UsageTrackingEosSubscriber, mock_event_bus: IEventBus
) -> None:
    """Test that subscriber unsubscribes from EoS events on stop."""
    await subscriber.start()
    await subscriber.stop()

    mock_event_bus.unsubscribe.assert_called_once()
    call_args = mock_event_bus.unsubscribe.call_args
    assert call_args[0][0] == RemoteBackendConnectionEndOfSessionEvent
    assert call_args[0][1] == subscriber._handle_eos_event


@pytest.mark.asyncio
async def test_handle_eos_event_handles_repository_failure_gracefully(
    subscriber: UsageTrackingEosSubscriber, mock_session_repo: SessionMetricsRepository
) -> None:
    """Test that handler handles repository failures gracefully."""
    event = RemoteBackendConnectionEndOfSessionEvent(
        session_id="test-session-123",
        signal_type=EndOfSessionSignalType.DONE_SENTINEL,
        termination_category=EndOfSessionTerminationCategory.NORMAL,
    )

    mock_session_repo.create.side_effect = Exception("Repository error")

    # Should not raise exception (fail-open behavior)
    await subscriber._handle_eos_event(event)

    mock_session_repo.create.assert_called_once()
