"""Unit tests for ClientEndOfSessionService."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from freezegun import freeze_time
from src.core.domain.client_termination import (
    ClientEndOfSessionSignal,
    ClientTerminationReason,
)
from src.core.domain.events.end_of_session_events import (
    EndOfSessionSignal,
    EndOfSessionSignalType,
    EndOfSessionTerminationCategory,
)
from src.core.domain.session_key import SessionKey
from src.core.interfaces.client_termination_reason_mapper_interface import (
    IClientTerminationReasonMapper,
)
from src.core.interfaces.end_of_session_service_interface import (
    IEndOfSessionService,
)
from src.core.interfaces.session_cancellation_coordinator_interface import (
    ISessionCancellationCoordinator,
)
from src.core.interfaces.session_metrics_initializer_interface import (
    ISessionMetricsInitializer,
)
from src.core.services.client_end_of_session_service import (
    ClientEndOfSessionService,
)


@pytest.fixture
def mock_cancellation_coordinator() -> ISessionCancellationCoordinator:
    """Create a mock cancellation coordinator."""
    mock = MagicMock(spec=ISessionCancellationCoordinator)
    mock.is_cancelled = Mock(return_value=False)
    mock.cancel_session = Mock()
    return mock


@pytest.fixture
def mock_metrics_initializer() -> ISessionMetricsInitializer:
    """Create a mock metrics initializer."""
    mock = MagicMock(spec=ISessionMetricsInitializer)
    mock.ensure_session_metrics = AsyncMock()
    return mock


@pytest.fixture
def mock_eos_service() -> IEndOfSessionService:
    """Create a mock EoS service."""
    mock = MagicMock(spec=IEndOfSessionService)
    mock.record_signal = AsyncMock()
    return mock


@pytest.fixture
def mock_reason_mapper() -> IClientTerminationReasonMapper:
    """Create a mock reason mapper."""
    mock = MagicMock(spec=IClientTerminationReasonMapper)
    mock.map_reason = Mock(return_value=ClientTerminationReason.CLIENT_DISCONNECTED)
    mock.map_exception = Mock(return_value=ClientTerminationReason.CLIENT_DISCONNECTED)
    return mock


@pytest.fixture
def service(
    mock_cancellation_coordinator: ISessionCancellationCoordinator,
    mock_metrics_initializer: ISessionMetricsInitializer,
    mock_eos_service: IEndOfSessionService,
    mock_reason_mapper: IClientTerminationReasonMapper,
) -> ClientEndOfSessionService:
    """Create ClientEndOfSessionService instance for testing."""
    return ClientEndOfSessionService(
        cancellation_coordinator=mock_cancellation_coordinator,
        metrics_initializer=mock_metrics_initializer,
        eos_service=mock_eos_service,
        reason_mapper=mock_reason_mapper,
    )


@pytest.fixture
def http_session_key() -> SessionKey:
    """Create an HTTP session key."""
    return SessionKey(
        protocol="http", primary_id="trace-123", group_id="conversation-456"
    )


@pytest.fixture
def sample_signal(http_session_key: SessionKey) -> ClientEndOfSessionSignal:
    """Create a sample client termination signal."""
    with freeze_time("2024-01-01 12:00:00"):
        return ClientEndOfSessionSignal(
            session_key=http_session_key,
            observed_at=datetime.now(timezone.utc),
            reason=ClientTerminationReason.CLIENT_DISCONNECTED,
            details="Client disconnected",
        )


class TestReportClientTermination:
    """Test report_client_termination method."""

    @pytest.mark.asyncio
    async def test_reports_termination_and_cancels_session(
        self,
        service: ClientEndOfSessionService,
        mock_cancellation_coordinator: ISessionCancellationCoordinator,
        mock_eos_service: IEndOfSessionService,
        sample_signal: ClientEndOfSessionSignal,
    ) -> None:
        """Test that termination is reported and session is cancelled."""
        await service.report_client_termination(sample_signal)

        # Verify cancellation coordinator was called
        mock_cancellation_coordinator.cancel_session.assert_called_once_with(
            sample_signal.session_key, sample_signal.reason
        )

        # Verify EoS signal was emitted
        mock_eos_service.record_signal.assert_called_once()
        call_args = mock_eos_service.record_signal.call_args[0][0]
        assert isinstance(call_args, EndOfSessionSignal)
        assert call_args.session_id == sample_signal.session_key.primary_id
        assert call_args.signal_type == EndOfSessionSignalType.CLIENT_TERMINATION
        assert call_args.termination_category == EndOfSessionTerminationCategory.NORMAL
        assert call_args.reason == sample_signal.reason.value

    @pytest.mark.asyncio
    async def test_cancellation_before_metrics_init(
        self,
        service: ClientEndOfSessionService,
        mock_cancellation_coordinator: ISessionCancellationCoordinator,
        mock_metrics_initializer: ISessionMetricsInitializer,
        sample_signal: ClientEndOfSessionSignal,
    ) -> None:
        """Test that cancellation happens before metrics initialization."""
        call_order = []

        def track_cancel(
            session_key: SessionKey, reason: ClientTerminationReason
        ) -> None:
            call_order.append("cancel")

        async def track_metrics(
            session_key: SessionKey, *, observed_at: datetime
        ) -> None:
            call_order.append("metrics")

        mock_cancellation_coordinator.cancel_session.side_effect = track_cancel
        mock_metrics_initializer.ensure_session_metrics.side_effect = track_metrics

        await service.report_client_termination(sample_signal)

        # Verify cancellation happens before metrics init
        assert call_order == ["cancel", "metrics"]

    @pytest.mark.asyncio
    async def test_deduplicates_multiple_reports(
        self,
        service: ClientEndOfSessionService,
        mock_cancellation_coordinator: ISessionCancellationCoordinator,
        mock_eos_service: IEndOfSessionService,
        sample_signal: ClientEndOfSessionSignal,
    ) -> None:
        """Test that multiple reports for same session are deduplicated."""
        # First report: session not cancelled
        mock_cancellation_coordinator.is_cancelled.return_value = False

        await service.report_client_termination(sample_signal)

        # Second report: session already cancelled
        mock_cancellation_coordinator.is_cancelled.return_value = True

        await service.report_client_termination(sample_signal)

        # Verify cancellation was only called once
        assert mock_cancellation_coordinator.cancel_session.call_count == 1

        # Verify EoS was only emitted once
        assert mock_eos_service.record_signal.call_count == 1

    @pytest.mark.asyncio
    async def test_ensures_session_metrics_exist(
        self,
        service: ClientEndOfSessionService,
        mock_metrics_initializer: ISessionMetricsInitializer,
        sample_signal: ClientEndOfSessionSignal,
    ) -> None:
        """Test that session metrics are ensured before EoS emission."""
        await service.report_client_termination(sample_signal)

        mock_metrics_initializer.ensure_session_metrics.assert_called_once()
        call_kwargs = mock_metrics_initializer.ensure_session_metrics.call_args[1]
        assert call_kwargs["observed_at"] == sample_signal.observed_at

    @pytest.mark.asyncio
    async def test_continues_even_if_metrics_init_fails(
        self,
        service: ClientEndOfSessionService,
        mock_metrics_initializer: ISessionMetricsInitializer,
        mock_eos_service: IEndOfSessionService,
        sample_signal: ClientEndOfSessionSignal,
    ) -> None:
        """Test that EoS emission continues even if metrics init fails."""
        mock_metrics_initializer.ensure_session_metrics.side_effect = Exception(
            "DB unavailable"
        )

        await service.report_client_termination(sample_signal)

        # Verify EoS was still emitted
        mock_eos_service.record_signal.assert_called_once()

    @pytest.mark.asyncio
    async def test_continues_even_if_eos_emission_fails(
        self,
        service: ClientEndOfSessionService,
        mock_eos_service: IEndOfSessionService,
        mock_cancellation_coordinator: ISessionCancellationCoordinator,
        sample_signal: ClientEndOfSessionSignal,
    ) -> None:
        """Test that cancellation still happens even if EoS emission fails."""
        mock_eos_service.record_signal.side_effect = Exception(
            "EoS service unavailable"
        )

        await service.report_client_termination(sample_signal)

        # Verify cancellation was still initiated (fail-open behavior)
        mock_cancellation_coordinator.cancel_session.assert_called_once_with(
            sample_signal.session_key, sample_signal.reason
        )


class TestReportClientTerminationIfApplicable:
    """Test report_client_termination_if_applicable method."""

    @pytest.mark.asyncio
    async def test_detects_cancelled_error(
        self,
        service: ClientEndOfSessionService,
        mock_reason_mapper: IClientTerminationReasonMapper,
        mock_eos_service: IEndOfSessionService,
        http_session_key: SessionKey,
    ) -> None:
        """Test that CancelledError is detected and mapped."""
        mock_reason_mapper.map_exception.return_value = (
            ClientTerminationReason.CLIENT_CANCELLED
        )

        exception = asyncio.CancelledError()
        await service.report_client_termination_if_applicable(
            http_session_key, exception
        )

        # Verify reason mapper was called
        mock_reason_mapper.map_exception.assert_called_once_with(exception)

        # Verify EoS was emitted
        mock_eos_service.record_signal.assert_called_once()

    @pytest.mark.asyncio
    async def test_detects_generator_exit(
        self,
        service: ClientEndOfSessionService,
        mock_reason_mapper: IClientTerminationReasonMapper,
        mock_eos_service: IEndOfSessionService,
        http_session_key: SessionKey,
    ) -> None:
        """Test that GeneratorExit is detected and mapped."""
        mock_reason_mapper.map_exception.return_value = (
            ClientTerminationReason.CLIENT_DISCONNECTED
        )

        exception = GeneratorExit()
        await service.report_client_termination_if_applicable(
            http_session_key, exception
        )

        # Verify reason mapper was called
        mock_reason_mapper.map_exception.assert_called_once_with(exception)

        # Verify EoS was emitted
        mock_eos_service.record_signal.assert_called_once()

    @pytest.mark.asyncio
    async def test_ignores_non_termination_exceptions(
        self,
        service: ClientEndOfSessionService,
        mock_reason_mapper: IClientTerminationReasonMapper,
        mock_eos_service: IEndOfSessionService,
        http_session_key: SessionKey,
    ) -> None:
        """Test that non-termination exceptions are ignored."""
        mock_reason_mapper.map_exception.return_value = (
            ClientTerminationReason.UNKNOWN_CLIENT_TERMINATION
        )

        exception = ValueError("Not a termination exception")
        await service.report_client_termination_if_applicable(
            http_session_key, exception
        )

        # Verify reason mapper was called
        mock_reason_mapper.map_exception.assert_called_once_with(exception)

        # Verify EoS was NOT emitted (UNKNOWN_CLIENT_TERMINATION means not applicable)
        mock_eos_service.record_signal.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_none_exception(
        self,
        service: ClientEndOfSessionService,
        mock_eos_service: IEndOfSessionService,
        http_session_key: SessionKey,
    ) -> None:
        """Test that None exception is handled gracefully."""
        await service.report_client_termination_if_applicable(http_session_key, None)

        # Verify EoS was NOT emitted
        mock_eos_service.record_signal.assert_not_called()


class TestSessionIsolation:
    """Test session isolation."""

    @pytest.mark.asyncio
    @freeze_time("2024-01-01 12:00:00")
    async def test_different_sessions_dont_interfere(
        self,
        service: ClientEndOfSessionService,
        mock_cancellation_coordinator: ISessionCancellationCoordinator,
        mock_eos_service: IEndOfSessionService,
    ) -> None:
        """Test that different sessions don't interfere."""
        session1 = SessionKey(protocol="http", primary_id="trace-1", group_id="conv-1")
        session2 = SessionKey(protocol="http", primary_id="trace-2", group_id="conv-2")

        signal1 = ClientEndOfSessionSignal(
            session_key=session1,
            observed_at=datetime.now(timezone.utc),
            reason=ClientTerminationReason.CLIENT_DISCONNECTED,
        )
        signal2 = ClientEndOfSessionSignal(
            session_key=session2,
            observed_at=datetime.now(timezone.utc),
            reason=ClientTerminationReason.CLIENT_CANCELLED,
        )

        await service.report_client_termination(signal1)
        await service.report_client_termination(signal2)

        # Verify both sessions were cancelled
        assert mock_cancellation_coordinator.cancel_session.call_count == 2

        # Verify both EoS signals were emitted
        assert mock_eos_service.record_signal.call_count == 2

        # Verify correct session IDs in EoS signals
        eos_calls = [
            call[0][0].session_id
            for call in mock_eos_service.record_signal.call_args_list
        ]
        assert session1.primary_id in eos_calls
        assert session2.primary_id in eos_calls
