"""Unit tests for EndOfSessionService.

Tests cover:
- Config gating (disabled, emit_events=False)
- Atomic claim dedupe (concurrent signals)
- In-memory cache dedupe
- Event emission with correct payload
- Dispatch timeout behavior (stop waiting, don't cancel handlers)
- Termination category and error classification
- Missing session_id handling
- Restart safety (DB-backed dedupe)
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.config.models.end_of_session import EndOfSessionConfig
from src.core.database.repositories.usage_repository import SessionMetricsRepository
from src.core.domain.events.end_of_session_events import (
    EndOfSessionErrorClassification,
    EndOfSessionSignal,
    EndOfSessionSignalType,
    EndOfSessionTerminationCategory,
    RemoteBackendConnectionEndOfSessionEvent,
)
from src.core.interfaces.event_bus_interface import IEventBus
from src.core.services.end_of_session_service import EndOfSessionService


@pytest.fixture
def mock_event_bus() -> IEventBus:
    """Create a mock event bus."""
    mock = MagicMock(spec=IEventBus)
    mock.publish = AsyncMock()
    mock.publish_nowait = AsyncMock()
    return mock


@pytest.fixture
def mock_session_repository() -> SessionMetricsRepository:
    """Create a mock session metrics repository."""
    mock = MagicMock(spec=SessionMetricsRepository)
    mock.claim_eos_emission = AsyncMock(return_value=True)
    mock.has_ended = AsyncMock(return_value=False)
    return mock


@pytest.fixture
def default_config() -> EndOfSessionConfig:
    """Create default EoS configuration."""
    return EndOfSessionConfig(
        enabled=True,
        emit_events=True,
        detect_stream_signals=True,
        detect_tool_completion=True,
        dispatch_timeout_seconds=5.0,
    )


@pytest.fixture
def service(
    mock_event_bus: IEventBus,
    default_config: EndOfSessionConfig,
    mock_session_repository: SessionMetricsRepository,
) -> EndOfSessionService:
    """Create EndOfSessionService instance for testing."""
    return EndOfSessionService(
        event_bus=mock_event_bus,
        config=default_config,
        session_repository=mock_session_repository,
    )


@pytest.fixture
def sample_signal() -> EndOfSessionSignal:
    """Create a sample EoS signal."""
    return EndOfSessionSignal(
        session_id="test-session-123",
        signal_type=EndOfSessionSignalType.DONE_SENTINEL,
        termination_category=EndOfSessionTerminationCategory.NORMAL,
        observed_at=datetime.now(timezone.utc),
        reason="Stream completed",
        protocol="openai",
        backend="openai",
    )


class TestConfigGating:
    """Test configuration gating behavior."""

    @pytest.mark.asyncio
    async def test_disabled_config_skips_emission(
        self,
        mock_event_bus: IEventBus,
        mock_session_repository: SessionMetricsRepository,
        sample_signal: EndOfSessionSignal,
    ):
        """Test that disabled config prevents emission."""
        config = EndOfSessionConfig(enabled=False, emit_events=True)
        service = EndOfSessionService(
            event_bus=mock_event_bus,
            config=config,
            session_repository=mock_session_repository,
        )

        await service.record_signal(sample_signal)

        mock_session_repository.claim_eos_emission.assert_not_awaited()
        mock_event_bus.publish.assert_not_awaited()
        mock_event_bus.publish_nowait.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_emit_events_false_skips_emission(
        self,
        mock_event_bus: IEventBus,
        mock_session_repository: SessionMetricsRepository,
        sample_signal: EndOfSessionSignal,
    ):
        """Test that emit_events=False prevents emission."""
        config = EndOfSessionConfig(enabled=True, emit_events=False)
        service = EndOfSessionService(
            event_bus=mock_event_bus,
            config=config,
            session_repository=mock_session_repository,
        )

        await service.record_signal(sample_signal)

        mock_session_repository.claim_eos_emission.assert_not_awaited()
        mock_event_bus.publish.assert_not_awaited()
        mock_event_bus.publish_nowait.assert_not_awaited()


class TestMissingSessionId:
    """Test handling of missing session_id."""

    @pytest.mark.asyncio
    async def test_missing_session_id_skips_emission(
        self,
        service: EndOfSessionService,
        mock_event_bus: IEventBus,
        mock_session_repository: SessionMetricsRepository,
    ):
        """Test that missing session_id prevents emission."""
        signal = EndOfSessionSignal(
            session_id="",
            signal_type=EndOfSessionSignalType.DONE_SENTINEL,
            termination_category=EndOfSessionTerminationCategory.NORMAL,
            observed_at=datetime.now(timezone.utc),
        )

        await service.record_signal(signal)

        mock_session_repository.claim_eos_emission.assert_not_awaited()
        mock_event_bus.publish.assert_not_awaited()


class TestInMemoryDedupe:
    """Test in-memory cache dedupe behavior."""

    @pytest.mark.asyncio
    async def test_in_memory_cache_prevents_duplicate_emission(
        self,
        service: EndOfSessionService,
        mock_event_bus: IEventBus,
        mock_session_repository: SessionMetricsRepository,
        sample_signal: EndOfSessionSignal,
    ):
        """Test that in-memory cache prevents duplicate emissions."""
        # First emission succeeds
        mock_session_repository.claim_eos_emission.return_value = True
        await service.record_signal(sample_signal)

        # Verify first emission occurred
        assert mock_session_repository.claim_eos_emission.await_count == 1

        # Second emission should be skipped due to cache
        await service.record_signal(sample_signal)

        # Should not attempt another claim
        assert mock_session_repository.claim_eos_emission.await_count == 1

    def test_has_ended_checks_cache(
        self, service: EndOfSessionService, sample_signal: EndOfSessionSignal
    ):
        """Test that has_ended checks in-memory cache."""
        assert not service.has_ended(sample_signal.session_id)

        # Mark as ended
        service._mark_ended(sample_signal.session_id)

        assert service.has_ended(sample_signal.session_id)


class TestCacheEviction:
    """Test in-memory cache eviction behavior."""

    @pytest.mark.asyncio
    async def test_cache_evicts_oldest_item(
        self,
        service: EndOfSessionService,
        mock_session_repository: SessionMetricsRepository,
    ):
        """Test that cache evicts oldest item when limit exceeded."""
        # Monkey-patch MAX_CACHE_SIZE for this test
        import src.core.services.end_of_session_service as service_module

        original_max_size = service_module.MAX_CACHE_SIZE
        service_module.MAX_CACHE_SIZE = 2

        try:
            # Add 3 items
            service._mark_ended("session-1")
            service._mark_ended("session-2")
            service._mark_ended("session-3")

            # Verify size is capped at 2
            assert len(service._ended_sessions) == 2

            # Verify eviction: session-1 should be gone (oldest)
            assert not service.has_ended("session-1")
            assert service.has_ended("session-2")
            assert service.has_ended("session-3")

            # Access session-2 to make it most recently used
            service._mark_ended("session-2")

            # Add session-4
            service._mark_ended("session-4")

            # Verify eviction: session-3 should be gone (oldest, since session-2 was refreshed)
            assert not service.has_ended("session-3")
            assert service.has_ended("session-2")
            assert service.has_ended("session-4")

        finally:
            service_module.MAX_CACHE_SIZE = original_max_size


class TestAtomicClaimDedupe:
    """Test atomic database claim dedupe behavior."""

    @pytest.mark.asyncio
    async def test_atomic_claim_failure_skips_emission(
        self,
        service: EndOfSessionService,
        mock_event_bus: IEventBus,
        mock_session_repository: SessionMetricsRepository,
        sample_signal: EndOfSessionSignal,
    ):
        """Test that failed atomic claim prevents emission."""
        mock_session_repository.claim_eos_emission.return_value = False

        await service.record_signal(sample_signal)

        # Should attempt claim but not emit event
        mock_session_repository.claim_eos_emission.assert_awaited_once()
        mock_event_bus.publish.assert_not_awaited()
        mock_event_bus.publish_nowait.assert_not_awaited()

        # Cache should be updated
        assert service.has_ended(sample_signal.session_id)

    @pytest.mark.asyncio
    async def test_concurrent_signals_only_one_emission(
        self,
        mock_event_bus: IEventBus,
        mock_session_repository: SessionMetricsRepository,
        default_config: EndOfSessionConfig,
    ):
        """Test that concurrent signals for same session produce only one emission."""
        session_id = "concurrent-session-123"

        # First call succeeds, subsequent calls fail
        call_count = 0

        async def claim_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return call_count == 1  # Only first call succeeds

        mock_session_repository.claim_eos_emission.side_effect = claim_side_effect

        service = EndOfSessionService(
            event_bus=mock_event_bus,
            config=default_config,
            session_repository=mock_session_repository,
        )

        # Create multiple signals for same session
        signals = [
            EndOfSessionSignal(
                session_id=session_id,
                signal_type=EndOfSessionSignalType.DONE_SENTINEL,
                termination_category=EndOfSessionTerminationCategory.NORMAL,
                observed_at=datetime.now(timezone.utc),
                reason=f"Signal {i}",
            )
            for i in range(5)
        ]

        # Process all signals concurrently
        await asyncio.gather(*[service.record_signal(signal) for signal in signals])
        
        # Only one emission should occur
        assert mock_event_bus.publish.await_count == 1
        
        # All claims should have been attempted (but cache may prevent some)
        # At least one claim should have been attempted
        assert mock_session_repository.claim_eos_emission.await_count >= 1
        # Due to in-memory cache, subsequent signals may be skipped before DB claim
        # This is expected behavior - cache prevents duplicate DB calls

        # Cache should reflect session ended
        assert service.has_ended(session_id)

    @pytest.mark.asyncio
    async def test_terminal_state_persistence_after_claim(
        self,
        service: EndOfSessionService,
        mock_event_bus: IEventBus,
        mock_session_repository: SessionMetricsRepository,
        sample_signal: EndOfSessionSignal,
    ):
        """Test that terminal state is persisted after successful claim."""
        mock_session_repository.claim_eos_emission.return_value = True

        await service.record_signal(sample_signal)

        # Verify claim was called with correct parameters
        mock_session_repository.claim_eos_emission.assert_awaited_once()
        call_kwargs = mock_session_repository.claim_eos_emission.call_args.kwargs
        assert call_kwargs["session_id"] == sample_signal.session_id
        assert call_kwargs["signal_type"] == sample_signal.signal_type.value
        assert call_kwargs["reason"] == sample_signal.reason
        assert call_kwargs["emitted_at"] is not None

        # Verify cache reflects terminal state
        assert service.has_ended(sample_signal.session_id)

        # Verify event was emitted
        mock_event_bus.publish.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_restart_safety_db_backed_dedupe(
        self,
        mock_event_bus: IEventBus,
        mock_session_repository: SessionMetricsRepository,
        default_config: EndOfSessionConfig,
    ):
        """Test that DB-backed dedupe works after restart (simulated by new service instance)."""
        session_id = "restart-session-123"

        # Simulate session already ended in DB (has_ended returns True)
        mock_session_repository.has_ended = AsyncMock(return_value=True)
        mock_session_repository.claim_eos_emission.return_value = False

        # Create new service instance (simulating restart)
        service = EndOfSessionService(
            event_bus=mock_event_bus,
            config=default_config,
            session_repository=mock_session_repository,
        )

        signal = EndOfSessionSignal(
            session_id=session_id,
            signal_type=EndOfSessionSignalType.DONE_SENTINEL,
            termination_category=EndOfSessionTerminationCategory.NORMAL,
            observed_at=datetime.now(timezone.utc),
        )

        # Try to emit - should be skipped
        await service.record_signal(signal)

        # Should attempt claim but fail (already claimed)
        mock_session_repository.claim_eos_emission.assert_awaited_once()

        # Should not emit event
        mock_event_bus.publish.assert_not_awaited()

        # Cache should be updated after failed claim
        assert service.has_ended(session_id)


class TestEventEmission:
    """Test event emission behavior."""

    @pytest.mark.asyncio
    async def test_event_emission_with_correct_payload(
        self,
        service: EndOfSessionService,
        mock_event_bus: IEventBus,
        mock_session_repository: SessionMetricsRepository,
        sample_signal: EndOfSessionSignal,
    ):
        """Test that event is emitted with correct payload."""
        mock_session_repository.claim_eos_emission.return_value = True

        await service.record_signal(sample_signal)

        # Verify event was published
        mock_event_bus.publish.assert_awaited_once()
        call_args = mock_event_bus.publish.call_args
        assert call_args is not None

        event = call_args[0][0]
        assert isinstance(event, RemoteBackendConnectionEndOfSessionEvent)
        assert event.session_id == sample_signal.session_id
        assert event.signal_type == sample_signal.signal_type
        assert event.termination_category == sample_signal.termination_category
        assert event.reason == sample_signal.reason
        assert event.protocol == sample_signal.protocol
        assert event.backend == sample_signal.backend

    @pytest.mark.asyncio
    async def test_error_classification_defaults_to_unknown(
        self,
        service: EndOfSessionService,
        mock_event_bus: IEventBus,
        mock_session_repository: SessionMetricsRepository,
    ):
        """Test that missing error classification defaults to unknown_error."""
        signal = EndOfSessionSignal(
            session_id="test-session-123",
            signal_type=EndOfSessionSignalType.ERROR_TERMINATION,
            termination_category=EndOfSessionTerminationCategory.ERROR,
            observed_at=datetime.now(timezone.utc),
            error_classification=None,  # Missing classification
        )
        mock_session_repository.claim_eos_emission.return_value = True

        await service.record_signal(signal)

        call_args = mock_event_bus.publish.call_args
        assert call_args is not None
        event = call_args[0][0]
        assert (
            event.error_classification == EndOfSessionErrorClassification.UNKNOWN_ERROR
        )

    @pytest.mark.asyncio
    async def test_error_classification_preserved_when_present(
        self,
        service: EndOfSessionService,
        mock_event_bus: IEventBus,
        mock_session_repository: SessionMetricsRepository,
    ):
        """Test that error classification is preserved when present."""
        signal = EndOfSessionSignal(
            session_id="test-session-123",
            signal_type=EndOfSessionSignalType.ERROR_TERMINATION,
            termination_category=EndOfSessionTerminationCategory.ERROR,
            observed_at=datetime.now(timezone.utc),
            error_classification=EndOfSessionErrorClassification.TRANSPORT_ERROR,
        )
        mock_session_repository.claim_eos_emission.return_value = True

        await service.record_signal(signal)

        call_args = mock_event_bus.publish.call_args
        assert call_args is not None
        event = call_args[0][0]
        assert (
            event.error_classification
            == EndOfSessionErrorClassification.TRANSPORT_ERROR
        )


class TestDispatchTimeout:
    """Test dispatch timeout behavior."""

    @pytest.mark.asyncio
    async def test_zero_timeout_uses_publish_nowait(
        self,
        mock_event_bus: IEventBus,
        mock_session_repository: SessionMetricsRepository,
        sample_signal: EndOfSessionSignal,
    ):
        """Test that zero timeout uses publish_nowait."""
        config = EndOfSessionConfig(
            enabled=True,
            emit_events=True,
            dispatch_timeout_seconds=0.0,
        )
        service = EndOfSessionService(
            event_bus=mock_event_bus,
            config=config,
            session_repository=mock_session_repository,
        )
        mock_session_repository.claim_eos_emission.return_value = True

        await service.record_signal(sample_signal)

        mock_event_bus.publish_nowait.assert_awaited_once()
        mock_event_bus.publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_timeout_stops_waiting_without_canceling(
        self,
        mock_event_bus: IEventBus,
        mock_session_repository: SessionMetricsRepository,
        sample_signal: EndOfSessionSignal,
    ):
        """Test that timeout stops waiting without canceling handlers."""
        config = EndOfSessionConfig(
            enabled=True,
            emit_events=True,
            dispatch_timeout_seconds=0.1,
        )
        service = EndOfSessionService(
            event_bus=mock_event_bus,
            config=config,
            session_repository=mock_session_repository,
        )
        mock_session_repository.claim_eos_emission.return_value = True

        # Make publish hang indefinitely
        async def slow_publish(*args, **kwargs):
            await asyncio.sleep(1.0)

        mock_event_bus.publish = AsyncMock(side_effect=slow_publish)

        await service.record_signal(sample_signal)

        # Should have attempted publish (shield prevents cancellation)
        mock_event_bus.publish.assert_awaited_once()


    @pytest.mark.asyncio
    async def test_timeout_logs_warning_but_continues(
        self,
        mock_event_bus: IEventBus,
        mock_session_repository: SessionMetricsRepository,
        sample_signal: EndOfSessionSignal,
        caplog,
    ):
        """Test that timeout logs warning but doesn't raise exception."""
        import logging

        config = EndOfSessionConfig(
            enabled=True,
            emit_events=True,
            dispatch_timeout_seconds=0.01,  # Very short timeout
        )
        service = EndOfSessionService(
            event_bus=mock_event_bus,
            config=config,
            session_repository=mock_session_repository,
        )
        mock_session_repository.claim_eos_emission.return_value = True

        # Make publish hang longer than timeout
        async def slow_publish(*args, **kwargs):
            await asyncio.sleep(0.1)

        mock_event_bus.publish = AsyncMock(side_effect=slow_publish)

        with caplog.at_level(logging.WARNING):
            await service.record_signal(sample_signal)

        # Should log timeout warning
        assert (
            "timeout" in caplog.text.lower()
            or "continuing without waiting" in caplog.text.lower()
        )

        # Should not raise exception
        assert mock_event_bus.publish.await_count == 1


class TestFailOpen:
    """Test fail-open error handling."""

    @pytest.mark.asyncio
    async def test_repository_error_logged_but_not_raised(
        self,
        service: EndOfSessionService,
        mock_event_bus: IEventBus,
        mock_session_repository: SessionMetricsRepository,
        sample_signal: EndOfSessionSignal,
    ):
        """Test that repository errors are logged but not raised."""
        mock_session_repository.claim_eos_emission.side_effect = Exception("DB error")

        # Should not raise
        await service.record_signal(sample_signal)

        # Should not emit event
        mock_event_bus.publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_event_bus_error_logged_but_not_raised(
        self,
        service: EndOfSessionService,
        mock_event_bus: IEventBus,
        mock_session_repository: SessionMetricsRepository,
        sample_signal: EndOfSessionSignal,
    ):
        """Test that event bus errors are logged but not raised."""
        mock_session_repository.claim_eos_emission.return_value = True
        mock_event_bus.publish.side_effect = Exception("Event bus error")

        # Should not raise
        await service.record_signal(sample_signal)

        # Should have attempted emission
        mock_event_bus.publish.assert_awaited_once()
