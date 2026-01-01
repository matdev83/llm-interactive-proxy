from unittest.mock import AsyncMock, Mock, patch

import pytest
from src.core.domain.chat import ChatRequest
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.planning_phase_manager_interface import IPlanningPhaseManager
from src.core.interfaces.resilience_interface import IResilienceCoordinator
from src.core.interfaces.stream_session_id_resolver_interface import (
    IStreamSessionIdResolver,
)
from src.core.interfaces.usage_tracking_interface import IUsageTrackingService
from src.core.interfaces.usage_tracking_wrapper_interface import IUsageTrackingWrapper
from src.core.services.backend_completion_flow.usage_accounting_orchestrator import (
    UsageAccountingOrchestrator,
)


class TestUsageAccountingOrchestrator:
    @pytest.fixture
    def usage_tracking_service(self):
        return Mock(spec=IUsageTrackingService)

    @pytest.fixture
    def usage_tracking_wrapper(self):
        return Mock(spec=IUsageTrackingWrapper)

    @pytest.fixture
    def stream_session_id_resolver(self):
        return Mock(spec=IStreamSessionIdResolver)

    @pytest.fixture
    def planning_phase_manager(self):
        return Mock(spec=IPlanningPhaseManager)

    @pytest.fixture
    def resilience_coordinator(self):
        return Mock(spec=IResilienceCoordinator)

    @pytest.fixture
    def orchestrator(
        self,
        usage_tracking_service,
        usage_tracking_wrapper,
        stream_session_id_resolver,
        planning_phase_manager,
        resilience_coordinator,
    ):
        return UsageAccountingOrchestrator(
            usage_tracking_service=usage_tracking_service,
            usage_tracking_wrapper=usage_tracking_wrapper,
            stream_session_id_resolver=stream_session_id_resolver,
            planning_phase_manager=planning_phase_manager,
            resilience_coordinator=resilience_coordinator,
        )

    @pytest.mark.asyncio
    async def test_calculate_and_record_usage(
        self, orchestrator, usage_tracking_service
    ):
        # Arrange
        usage_tracking_service.record_request = AsyncMock(
            side_effect=["rec_ctp", "rec_ptb"]
        )

        request = Mock(spec=ChatRequest)
        domain_request = Mock(spec=ChatRequest)

        # We need to patch calculate_outbound_tokens because it's imported inside the method usually
        # But if we move logic, it might be imported at top level or dependency injected?
        # The original code imported it inside. I'll patch it.
        with patch(
            "src.core.services.backend_completion_flow.usage_accounting_orchestrator.calculate_outbound_tokens"
        ) as mock_calc:
            mock_calc.return_value = 100

            # Act
            outbound, ctp, ptb = await orchestrator.calculate_and_record_usage(
                domain_request=domain_request,
                request=request,
                backend_type="openai",
                effective_model="gpt-4",
                session=None,
                session_id_for_backend="sess_1",
            )

            # Assert
            assert outbound == 100
            assert ctp == "rec_ctp"
            assert ptb == "rec_ptb"
            assert usage_tracking_service.record_request.call_count == 2

    @pytest.mark.asyncio
    async def test_wrap_response_for_usage_non_streaming(
        self, orchestrator, usage_tracking_service
    ):
        # Arrange
        from src.core.domain.usage_summary import UsageSummary

        response = ResponseEnvelope(
            content="foo", usage=UsageSummary.from_dict({"completion_tokens": 50})
        )
        usage_tracking_service.record_response = AsyncMock()

        # Act
        result = await orchestrator.wrap_response_for_usage(
            result=response,
            outbound_tokens=100,
            ctp_record_id="rec_ctp",
            ptb_record_id="rec_ptb",
            start_time=1000.0,
        )

        # Assert
        assert result == response
        assert result.metadata["outbound_tokens"] == 100
        assert usage_tracking_service.record_response.call_count == 2

    @pytest.mark.asyncio
    async def test_wrap_response_for_usage_streaming(
        self, orchestrator, usage_tracking_wrapper
    ):
        # Arrange
        stream = Mock()
        response = StreamingResponseEnvelope(content=stream)
        usage_tracking_wrapper.wrap_stream_for_usage.return_value = "wrapped_stream"

        # Act
        result = await orchestrator.wrap_response_for_usage(
            result=response,
            outbound_tokens=100,
            ctp_record_id="rec_ctp",
            ptb_record_id="rec_ptb",
            start_time=1000.0,
        )

        # Assert
        assert result.content == "wrapped_stream"
        assert result.metadata["outbound_tokens"] == 100
        usage_tracking_wrapper.wrap_stream_for_usage.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_streaming_response_success(
        self,
        orchestrator,
        resilience_coordinator,
        planning_phase_manager,
        stream_session_id_resolver,
    ):
        # Arrange
        response = StreamingResponseEnvelope(content=Mock())
        stream_session_id_resolver.resolve_stream_session_id.return_value = "sess_1"
        context = None

        # Act
        result = await orchestrator.handle_streaming_response(
            result=response,
            backend_type="openai",
            effective_model="gpt-4",
            context=context,
            request=Mock(),
            session_id_for_backend="sess_1",
        )

        # Assert
        assert isinstance(result, StreamingResponseEnvelope)
        resilience_coordinator.record_success.assert_called_with("openai", "gpt-4")
        # Session ID injection wrapper is applied?
        # The wrapper is internal to the method, hard to test without consuming stream.
        # But we can check side effects.

    @pytest.mark.asyncio
    async def test_handle_non_streaming_response_success(
        self, orchestrator, resilience_coordinator, planning_phase_manager
    ):
        # Arrange
        response = ResponseEnvelope(content="foo")
        planning_phase_manager.update_counters = AsyncMock()

        # Act
        result = await orchestrator.handle_non_streaming_response(
            result=response,
            backend_type="openai",
            effective_model="gpt-4",
            session_id_for_backend="sess_1",
        )

        # Assert
        assert result == response
        resilience_coordinator.record_success.assert_called_with("openai", "gpt-4")
        planning_phase_manager.update_counters.assert_called_with("sess_1", response)
