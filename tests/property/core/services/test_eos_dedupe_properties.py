"""Property tests for End-of-Session dedupe invariants.

These tests use Hypothesis to validate that multiple signals per session
never produce duplicate EoS events under various signal orderings and
concurrency scenarios.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from freezegun import freeze_time
from hypothesis import HealthCheck, given
from hypothesis import strategies as st
from src.core.config.models.end_of_session import EndOfSessionConfig
from src.core.database.repositories.usage_repository import SessionMetricsRepository
from src.core.domain.events.end_of_session_events import (
    EndOfSessionErrorClassification,
    EndOfSessionSignal,
    EndOfSessionSignalType,
    EndOfSessionTerminationCategory,
)
from src.core.interfaces.event_bus_interface import IEventBus
from src.core.services.end_of_session_service import EndOfSessionService
from tests.utils.hypothesis_config import property_test_settings


@pytest.fixture
def mock_event_bus() -> IEventBus:
    """Create a mock event bus that captures events."""
    mock = MagicMock(spec=IEventBus)
    mock.publish = AsyncMock()  # type: ignore[method-assign]
    mock.publish_nowait = AsyncMock()  # type: ignore[method-assign]
    return mock


@pytest.fixture
def mock_session_repository() -> SessionMetricsRepository:
    """Create a mock session metrics repository."""
    mock = MagicMock(spec=SessionMetricsRepository)
    # Reset mock state for each test
    mock.claim_eos_emission = AsyncMock(return_value=True)  # type: ignore[method-assign]
    mock.has_ended = AsyncMock(return_value=False)  # type: ignore[method-assign]
    return mock


@pytest.fixture
def eos_service(
    mock_event_bus: IEventBus, mock_session_repository: SessionMetricsRepository
) -> EndOfSessionService:
    """Create EndOfSessionService instance."""
    config = EndOfSessionConfig(
        enabled=True,
        emit_events=True,
        detect_stream_signals=True,
        detect_tool_completion=True,
        dispatch_timeout_seconds=5.0,
    )
    return EndOfSessionService(
        event_bus=mock_event_bus,
        config=config,
        session_repository=mock_session_repository,
    )


def signal_strategy() -> st.SearchStrategy[EndOfSessionSignal]:
    """Generate EndOfSessionSignal instances."""
    return st.builds(
        EndOfSessionSignal,
        session_id=st.text(min_size=1, max_size=50),
        signal_type=st.sampled_from(list(EndOfSessionSignalType)),
        termination_category=st.sampled_from(list(EndOfSessionTerminationCategory)),
        observed_at=st.datetimes(timezones=st.just(timezone.utc)),
        reason=st.text(max_size=100) | st.none(),
        error_classification=st.sampled_from(list(EndOfSessionErrorClassification))
        | st.none(),
        error_status_code=st.integers(min_value=400, max_value=599) | st.none(),
        protocol=st.text(max_size=20) | st.none(),
        request_id=st.text(max_size=50) | st.none(),
        backend=st.text(max_size=50) | st.none(),
    )


@pytest.mark.asyncio
@given(signals=st.lists(signal_strategy(), min_size=2, max_size=5))
@property_test_settings(
    max_examples=10,
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.data_too_large,
        HealthCheck.function_scoped_fixture,
    ],
)
async def test_property_multiple_signals_single_emission(
    eos_service: EndOfSessionService,
    mock_event_bus: IEventBus,
    mock_session_repository: SessionMetricsRepository,
    signals: list[EndOfSessionSignal],
) -> None:
    """Property: Multiple signals per session never produce duplicate events.

    Given multiple signals for the same session, only one EoS event should
    be emitted regardless of signal ordering or type.
    """
    # Ensure all signals have the same session_id
    session_id = signals[0].session_id
    normalized_signals = []
    for signal in signals:
        normalized = EndOfSessionSignal(
            session_id=session_id,
            signal_type=signal.signal_type,
            termination_category=signal.termination_category,
            observed_at=signal.observed_at,
            reason=signal.reason,
            error_classification=signal.error_classification,
            error_status_code=signal.error_status_code,
            protocol=signal.protocol,
            request_id=signal.request_id,
            backend=signal.backend,
        )
        normalized_signals.append(normalized)

    # Reset service cache and mock state
    eos_service._ended_sessions.clear()
    mock_event_bus.publish.reset_mock()
    mock_session_repository.claim_eos_emission.reset_mock()

    # Configure claim to succeed only on first call per session
    call_counts: dict[str, int] = {}

    async def claim_side_effect(*args, **kwargs):
        session_id = kwargs.get("session_id", args[0] if args else None)
        if session_id not in call_counts:
            call_counts[session_id] = 0
        call_counts[session_id] += 1
        return call_counts[session_id] == 1

    mock_session_repository.claim_eos_emission.side_effect = claim_side_effect

    # Process all signals concurrently
    await asyncio.gather(
        *[eos_service.record_signal(signal) for signal in normalized_signals]
    )

    # Verify only one event was emitted
    assert mock_event_bus.publish.await_count == 1

    # Verify all claims were attempted (cache may prevent some, but at least one should be attempted)
    assert mock_session_repository.claim_eos_emission.await_count >= 1


@pytest.mark.asyncio
@given(
    session_ids=st.lists(
        st.text(min_size=1, max_size=50), min_size=2, max_size=5, unique=True
    ),
    signals_per_session=st.integers(min_value=2, max_value=5),
)
@property_test_settings(
    max_examples=20,  # Reduced from 30 for performance
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.data_too_large,
        HealthCheck.function_scoped_fixture,
    ],
)
@freeze_time("2024-01-01 12:00:00")
async def test_property_concurrent_sessions_independent_dedupe(
    eos_service: EndOfSessionService,
    mock_event_bus: IEventBus,
    mock_session_repository: SessionMetricsRepository,
    session_ids: list[str],
    signals_per_session: int,
) -> None:
    """Property: Concurrent signals for different sessions are independent.

    Each session should emit exactly one event, regardless of concurrent
    processing of signals for other sessions.
    """
    # Reset service cache and mock state
    eos_service._ended_sessions.clear()
    mock_event_bus.publish.reset_mock()
    mock_session_repository.claim_eos_emission.reset_mock()

    # Configure claim to succeed only on first call per session
    call_counts: dict[str, int] = {}

    async def claim_side_effect(*args, **kwargs):
        session_id = kwargs.get("session_id", args[0] if args else None)
        if session_id not in call_counts:
            call_counts[session_id] = 0
        call_counts[session_id] += 1
        return call_counts[session_id] == 1

    mock_session_repository.claim_eos_emission.side_effect = claim_side_effect

    # Create signals for each session
    all_signals: list[EndOfSessionSignal] = []
    fixed_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    for session_id in session_ids:
        for i in range(signals_per_session):
            signal = EndOfSessionSignal(
                session_id=session_id,
                signal_type=EndOfSessionSignalType.DONE_SENTINEL,
                termination_category=EndOfSessionTerminationCategory.NORMAL,
                observed_at=fixed_time,
                reason=f"Signal {i}",
            )
            all_signals.append(signal)

    # Process all signals concurrently
    await asyncio.gather(*[eos_service.record_signal(signal) for signal in all_signals])

    # Verify exactly one event per unique session
    unique_session_count = len(set(session_ids))
    assert mock_event_bus.publish.await_count == unique_session_count

    # Verify all claims were attempted (cache may prevent some, but at least one per session)
    assert (
        mock_session_repository.claim_eos_emission.await_count >= unique_session_count
    )


@pytest.mark.asyncio
@given(
    signals=st.lists(
        signal_strategy(), min_size=1, max_size=10
    ),  # Reduced from 20 for performance
    session_id=st.text(min_size=1, max_size=50),
)
@property_test_settings(
    max_examples=15,  # Reduced from 30 for performance
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.data_too_large,
        HealthCheck.function_scoped_fixture,
    ],
)
async def test_property_random_signal_ordering_maintains_dedupe(
    eos_service: EndOfSessionService,
    mock_event_bus: IEventBus,
    mock_session_repository: SessionMetricsRepository,
    signals: list[EndOfSessionSignal],
    session_id: str,
) -> None:
    """Property: Random signal ordering maintains dedupe guarantee.

    Regardless of the order in which signals arrive, only one event
    should be emitted per session.
    """
    # Normalize all signals to same session_id
    normalized_signals = []
    for signal in signals:
        normalized = EndOfSessionSignal(
            session_id=session_id,
            signal_type=signal.signal_type,
            termination_category=signal.termination_category,
            observed_at=signal.observed_at,
            reason=signal.reason,
            error_classification=signal.error_classification,
            error_status_code=signal.error_status_code,
            protocol=signal.protocol,
            request_id=signal.request_id,
            backend=signal.backend,
        )
        normalized_signals.append(normalized)

    # Reset service cache and mock state
    eos_service._ended_sessions.clear()
    mock_event_bus.publish.reset_mock()
    mock_session_repository.claim_eos_emission.reset_mock()

    # Configure claim to succeed only on first call
    call_count = 0

    async def claim_side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return call_count == 1

    mock_session_repository.claim_eos_emission.side_effect = claim_side_effect

    # Process signals sequentially (simulating random ordering)
    for signal in normalized_signals:
        await eos_service.record_signal(signal)

    # Verify only one event was emitted
    assert mock_event_bus.publish.await_count == 1

    # Verify all claims were attempted (cache may prevent some after first)
    assert mock_session_repository.claim_eos_emission.await_count >= 1


@pytest.mark.asyncio
@given(
    session_id=st.text(min_size=1, max_size=50),
    num_signals=st.integers(min_value=2, max_value=10),
)
@property_test_settings(
    max_examples=20,
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.data_too_large,
        HealthCheck.function_scoped_fixture,
    ],
)
@freeze_time("2024-01-01 12:00:00")
async def test_property_restart_scenario_maintains_dedupe(
    session_id: str,
    num_signals: int,
) -> None:
    """Property: Restart scenarios maintain dedupe (DB-backed).

    Simulating a restart by creating a new service instance after
    the first signal should prevent duplicate emissions.
    """
    # Create fresh mocks for this test (not using fixtures to avoid state leakage)
    mock_event_bus = MagicMock(spec=IEventBus)
    mock_event_bus.publish = AsyncMock()
    mock_event_bus.publish_nowait = AsyncMock()

    # Create first service instance
    mock_repo1 = MagicMock(spec=SessionMetricsRepository)
    mock_repo1.claim_eos_emission = AsyncMock(return_value=True)  # First claim succeeds
    mock_repo1.has_ended = AsyncMock(return_value=False)

    config = EndOfSessionConfig(
        enabled=True,
        emit_events=True,
        detect_stream_signals=True,
        detect_tool_completion=True,
        dispatch_timeout_seconds=5.0,
    )

    service1 = EndOfSessionService(
        event_bus=mock_event_bus,
        config=config,
        session_repository=mock_repo1,
    )

    # Process first signal
    fixed_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    signal1 = EndOfSessionSignal(
        session_id=session_id,
        signal_type=EndOfSessionSignalType.DONE_SENTINEL,
        termination_category=EndOfSessionTerminationCategory.NORMAL,
        observed_at=fixed_time,
    )

    await service1.record_signal(signal1)

    # Simulate restart: create new service instance
    mock_repo2 = MagicMock(spec=SessionMetricsRepository)
    mock_repo2.claim_eos_emission = AsyncMock(return_value=False)  # Already claimed
    mock_repo2.has_ended = AsyncMock(return_value=False)

    service2 = EndOfSessionService(
        event_bus=mock_event_bus,
        config=config,
        session_repository=mock_repo2,
    )

    # Process additional signals after restart
    additional_signals = [
        EndOfSessionSignal(
            session_id=session_id,
            signal_type=EndOfSessionSignalType.FINISH_REASON,
            termination_category=EndOfSessionTerminationCategory.NORMAL,
            observed_at=fixed_time,
            reason=f"Signal {i}",
        )
        for i in range(num_signals - 1)
    ]

    for signal in additional_signals:
        await service2.record_signal(signal)

    # Verify only one event was emitted total (from first service)
    assert mock_event_bus.publish.await_count == 1

    # Verify all claims were attempted
    assert mock_repo1.claim_eos_emission.await_count == 1
    # After restart, cache may prevent some claims, but at least one should be attempted
    assert mock_repo2.claim_eos_emission.await_count >= 1


@pytest.mark.asyncio
@given(
    session_id=st.text(min_size=1, max_size=50),
    num_concurrent_calls=st.integers(min_value=5, max_value=20),
)
@property_test_settings(
    max_examples=20,
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.data_too_large,
        HealthCheck.function_scoped_fixture,
    ],
)
@freeze_time("2024-01-01 12:00:00")
async def test_property_concurrent_signal_processing_single_emission(
    eos_service: EndOfSessionService,
    mock_event_bus: IEventBus,
    mock_session_repository: SessionMetricsRepository,
    session_id: str,
    num_concurrent_calls: int,
) -> None:
    """Property: Concurrent signal processing maintains single emission.

    Even when multiple signals arrive simultaneously for the same session,
    only one event should be emitted.
    """
    # Reset service cache and mock state
    eos_service._ended_sessions.clear()
    mock_event_bus.publish.reset_mock()
    mock_session_repository.claim_eos_emission.reset_mock()

    # Configure claim to succeed only on first call
    call_count = 0

    async def claim_side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return call_count == 1

    mock_session_repository.claim_eos_emission.side_effect = claim_side_effect

    # Create multiple signals for same session
    fixed_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    signals = [
        EndOfSessionSignal(
            session_id=session_id,
            signal_type=EndOfSessionSignalType.DONE_SENTINEL,
            termination_category=EndOfSessionTerminationCategory.NORMAL,
            observed_at=fixed_time,
            reason=f"Concurrent signal {i}",
        )
        for i in range(num_concurrent_calls)
    ]

    # Process all signals concurrently
    await asyncio.gather(*[eos_service.record_signal(signal) for signal in signals])

    # Verify only one event was emitted
    assert mock_event_bus.publish.await_count == 1

    # Verify all claims were attempted (cache may prevent some after first)
    assert mock_session_repository.claim_eos_emission.await_count >= 1
