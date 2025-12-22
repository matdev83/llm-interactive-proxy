"""Regression tests for streaming canonical usage wire capture.

These tests verify that canonical_usage is properly captured to wire capture
for streaming responses. This addresses a bug where capture_stream_completion
was called immediately after handle_streaming_response returned (before stream
consumption), resulting in canonical_usage always being None.

The fix moved capture_stream_completion inside the generator's finally block,
where canonical_usage is actually available after stream completion.

Bug details:
- Original code checked streaming_result.canonical_usage immediately after
  handle_streaming_response returned
- At that point, canonical_usage was always None because it's set in the
  generator's finally block (which runs when stream is consumed)
- Result: capture_stream_completion was never called with valid canonical_usage

These tests will FAIL if the bug is reintroduced.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.domain.request_context import ProcessingContext, RequestContext
from src.core.domain.responses import StreamingResponseEnvelope
from src.core.domain.usage_canonical_record import (
    CanonicalUsageRecord,
    UsageCompletionOutcome,
)
from src.core.domain.usage_summary import UsageSummary
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.backend_completion_flow.usage_accounting_orchestrator import (
    UsageAccountingOrchestrator,
)


class TestStreamingCanonicalUsageCaptureRegression:
    """Regression tests for streaming canonical usage capture.

    These tests verify that the canonical_usage wire capture bug is not
    reintroduced. The bug was that capture_stream_completion was called
    before stream consumption, when canonical_usage was still None.
    """

    @pytest.fixture
    def mock_wire_capture_orchestrator(self) -> MagicMock:
        """Create a mock wire capture orchestrator."""
        mock = MagicMock()
        mock.capture_stream_completion = AsyncMock()
        return mock

    @pytest.fixture
    def mock_usage_normalization_service(self) -> MagicMock:
        """Create a mock usage normalization service."""
        mock = MagicMock()
        # Return a real CanonicalUsageRecord so we can verify it's passed through
        mock.build_canonical_record = AsyncMock(
            return_value=CanonicalUsageRecord(
                provider_id="test-backend",
                model_id="test-model",
                request_id="test-request-id",
                protocol="openai",
                prompt_tokens=100,
                completion_tokens=50,
                total_tokens=150,
                completion_outcome=UsageCompletionOutcome.complete,
            )
        )
        return mock

    @pytest.fixture
    def orchestrator(
        self,
        mock_wire_capture_orchestrator: MagicMock,
        mock_usage_normalization_service: MagicMock,
    ) -> UsageAccountingOrchestrator:
        """Create orchestrator with mocked dependencies."""
        return UsageAccountingOrchestrator(
            usage_tracking_service=None,
            usage_tracking_wrapper=MagicMock(),
            stream_session_id_resolver=MagicMock(
                resolve_stream_session_id=MagicMock(return_value="test-session")
            ),
            planning_phase_manager=MagicMock(update_counters=AsyncMock()),
            resilience_coordinator=MagicMock(record_success=MagicMock()),
            backend_factory=None,
            backend_lifecycle_manager=None,
            usage_normalization_service=mock_usage_normalization_service,
            wire_capture_orchestrator=mock_wire_capture_orchestrator,
        )

    @pytest.fixture
    def request_context(self) -> RequestContext:
        """Create a test request context."""
        return RequestContext(
            headers={},
            cookies={},
            state=None,
            app_state=None,
            request_id="test-request-id",
            processing_context=ProcessingContext(),
            extensions={"protocol": "openai"},
        )

    @pytest.fixture
    def domain_request(self) -> CanonicalChatRequest:
        """Create a test domain request."""
        return CanonicalChatRequest(
            model="test-model",
            messages=[ChatMessage(role="user", content="test")],
        )

    @pytest.mark.asyncio
    async def test_capture_stream_completion_called_after_stream_consumed(
        self,
        orchestrator: UsageAccountingOrchestrator,
        mock_wire_capture_orchestrator: MagicMock,
        mock_usage_normalization_service: MagicMock,
        request_context: RequestContext,
        domain_request: CanonicalChatRequest,
    ) -> None:
        """Verify capture_stream_completion is called AFTER stream is consumed.

        This is the core regression test. The bug was that capture_stream_completion
        was called immediately after handle_streaming_response returned, before
        the stream was consumed. At that point, canonical_usage was None.

        The fix moved capture_stream_completion inside the generator's finally block,
        so it's called when the stream completes with the actual canonical_usage.
        """

        # Create a streaming response with some content
        async def mock_stream() -> AsyncIterator[ProcessedResponse]:
            yield ProcessedResponse(
                content=b"data: test\n\n",
                metadata={},
                usage=UsageSummary(prompt_tokens=100, completion_tokens=50),
            )

        envelope = StreamingResponseEnvelope(
            content=mock_stream(),
            headers={},
            status_code=200,
        )

        # Call handle_streaming_response - this returns immediately
        result = await orchestrator.handle_streaming_response(
            result=envelope,
            backend_type="test-backend",
            effective_model="test-model",
            context=request_context,
            request=domain_request,
            session_id_for_backend="test-session",
            key_name="TEST_API_KEY",
        )

        # IMPORTANT: At this point, capture_stream_completion should NOT have been called yet
        # The stream hasn't been consumed, so canonical_usage hasn't been built
        # (This was the bug - the old code tried to capture here)
        assert mock_wire_capture_orchestrator.capture_stream_completion.call_count == 0

        # Now consume the stream - this triggers the finally block
        chunks = []
        assert result.content is not None
        async for chunk in result.content:
            chunks.append(chunk)

        # NOW capture_stream_completion should have been called
        assert mock_wire_capture_orchestrator.capture_stream_completion.call_count == 1

    @pytest.mark.asyncio
    async def test_capture_stream_completion_receives_valid_canonical_usage(
        self,
        orchestrator: UsageAccountingOrchestrator,
        mock_wire_capture_orchestrator: MagicMock,
        mock_usage_normalization_service: MagicMock,
        request_context: RequestContext,
        domain_request: CanonicalChatRequest,
    ) -> None:
        """Verify capture_stream_completion receives non-None canonical_usage.

        The bug resulted in canonical_usage always being None when
        capture_stream_completion was called. This test verifies that
        the canonical_usage is properly passed through.
        """

        async def mock_stream() -> AsyncIterator[ProcessedResponse]:
            yield ProcessedResponse(
                content=b"data: test\n\n",
                metadata={},
                usage=UsageSummary(prompt_tokens=100, completion_tokens=50),
            )

        envelope = StreamingResponseEnvelope(
            content=mock_stream(),
            headers={},
            status_code=200,
        )

        result = await orchestrator.handle_streaming_response(
            result=envelope,
            backend_type="test-backend",
            effective_model="test-model",
            context=request_context,
            request=domain_request,
            session_id_for_backend="test-session",
            key_name="TEST_API_KEY",
        )

        # Consume the stream
        assert result.content is not None
        async for _ in result.content:
            pass

        # Verify capture_stream_completion was called with valid canonical_usage
        call_kwargs = mock_wire_capture_orchestrator.capture_stream_completion.call_args
        assert call_kwargs is not None

        # The canonical_usage parameter should NOT be None
        canonical_usage = call_kwargs.kwargs.get("canonical_usage")
        assert canonical_usage is not None, (
            "capture_stream_completion was called with canonical_usage=None. "
            "This indicates the streaming canonical usage capture bug has been reintroduced. "
            "The call must happen AFTER stream consumption, inside the generator's finally block."
        )

        # Verify it's actually a CanonicalUsageRecord with expected values
        assert isinstance(canonical_usage, CanonicalUsageRecord)
        assert canonical_usage.provider_id == "test-backend"
        assert canonical_usage.model_id == "test-model"
        assert canonical_usage.completion_outcome == UsageCompletionOutcome.complete

    @pytest.mark.asyncio
    async def test_capture_stream_completion_receives_correct_parameters(
        self,
        orchestrator: UsageAccountingOrchestrator,
        mock_wire_capture_orchestrator: MagicMock,
        mock_usage_normalization_service: MagicMock,
        request_context: RequestContext,
        domain_request: CanonicalChatRequest,
    ) -> None:
        """Verify capture_stream_completion receives all required parameters.

        This ensures the wire capture call has all the context needed for
        proper capture metadata.
        """

        async def mock_stream() -> AsyncIterator[ProcessedResponse]:
            yield ProcessedResponse(content=b"data: test\n\n", metadata={})

        envelope = StreamingResponseEnvelope(
            content=mock_stream(),
            headers={},
            status_code=200,
        )

        result = await orchestrator.handle_streaming_response(
            result=envelope,
            backend_type="my-backend",
            effective_model="my-model",
            context=request_context,
            request=domain_request,
            session_id_for_backend="my-session",
            key_name="MY_API_KEY",
        )

        # Consume the stream
        assert result.content is not None
        async for _ in result.content:
            pass

        # Verify all parameters are passed correctly
        mock_wire_capture_orchestrator.capture_stream_completion.assert_called_once()
        call_kwargs = (
            mock_wire_capture_orchestrator.capture_stream_completion.call_args.kwargs
        )

        assert call_kwargs["context"] is request_context
        assert call_kwargs["backend_type"] == "my-backend"
        assert call_kwargs["effective_model"] == "my-model"
        assert call_kwargs["key_name"] == "MY_API_KEY"
        assert call_kwargs["canonical_usage"] is not None

    @pytest.mark.asyncio
    async def test_canonical_usage_attached_to_envelope_after_stream_consumed(
        self,
        orchestrator: UsageAccountingOrchestrator,
        mock_wire_capture_orchestrator: MagicMock,
        mock_usage_normalization_service: MagicMock,
        request_context: RequestContext,
        domain_request: CanonicalChatRequest,
    ) -> None:
        """Verify canonical_usage is attached to envelope after stream consumption.

        The envelope's canonical_usage should be set when the stream completes,
        not when handle_streaming_response returns.
        """

        async def mock_stream() -> AsyncIterator[ProcessedResponse]:
            yield ProcessedResponse(content=b"data: test\n\n", metadata={})

        envelope = StreamingResponseEnvelope(
            content=mock_stream(),
            headers={},
            status_code=200,
        )

        result = await orchestrator.handle_streaming_response(
            result=envelope,
            backend_type="test-backend",
            effective_model="test-model",
            context=request_context,
            request=domain_request,
            session_id_for_backend="test-session",
            key_name="TEST_API_KEY",
        )

        # Before stream consumption, canonical_usage should be None
        assert result.canonical_usage is None

        # Consume the stream
        assert result.content is not None
        async for _ in result.content:
            pass

        # After stream consumption, canonical_usage should be set
        assert result.canonical_usage is not None
        assert isinstance(result.canonical_usage, CanonicalUsageRecord)

    @pytest.mark.asyncio
    async def test_capture_called_even_when_stream_has_error(
        self,
        orchestrator: UsageAccountingOrchestrator,
        mock_wire_capture_orchestrator: MagicMock,
        mock_usage_normalization_service: MagicMock,
        request_context: RequestContext,
        domain_request: CanonicalChatRequest,
    ) -> None:
        """Verify capture_stream_completion is called even when stream errors.

        The finally block should execute regardless of whether the stream
        completes successfully or with an error.
        """
        # Update mock to return incomplete outcome for error case
        mock_usage_normalization_service.build_canonical_record = AsyncMock(
            return_value=CanonicalUsageRecord(
                provider_id="test-backend",
                model_id="test-model",
                completion_outcome=UsageCompletionOutcome.incomplete,
            )
        )

        async def mock_stream_with_error() -> AsyncIterator[ProcessedResponse]:
            yield ProcessedResponse(content=b"data: partial\n\n", metadata={})
            raise ValueError("Simulated stream error")

        envelope = StreamingResponseEnvelope(
            content=mock_stream_with_error(),
            headers={},
            status_code=200,
        )

        result = await orchestrator.handle_streaming_response(
            result=envelope,
            backend_type="test-backend",
            effective_model="test-model",
            context=request_context,
            request=domain_request,
            session_id_for_backend="test-session",
            key_name="TEST_API_KEY",
        )

        # Consume the stream, expecting an error
        assert result.content is not None
        with pytest.raises(ValueError, match="Simulated stream error"):
            async for _ in result.content:
                pass

        # Even with an error, capture_stream_completion should be called
        assert mock_wire_capture_orchestrator.capture_stream_completion.call_count == 1

        # Verify canonical_usage was passed (even for error case)
        call_kwargs = (
            mock_wire_capture_orchestrator.capture_stream_completion.call_args.kwargs
        )
        assert call_kwargs["canonical_usage"] is not None


class TestStreamingCanonicalUsageServiceIntegration:
    """Integration-level regression tests for streaming canonical usage.

    These tests verify the integration between UsageAccountingOrchestrator
    and WireCaptureOrchestrator for streaming canonical usage capture.
    """

    @pytest.mark.asyncio
    async def test_wire_capture_not_called_when_orchestrator_is_none(
        self,
    ) -> None:
        """Verify no crash when wire_capture_orchestrator is None.

        The orchestrator should gracefully handle missing wire capture service.
        """
        mock_usage_normalization_service = MagicMock()
        mock_usage_normalization_service.build_canonical_record = AsyncMock(
            return_value=CanonicalUsageRecord(
                provider_id="test-backend",
                model_id="test-model",
                completion_outcome=UsageCompletionOutcome.complete,
            )
        )

        orchestrator = UsageAccountingOrchestrator(
            usage_tracking_service=None,
            usage_tracking_wrapper=MagicMock(),
            stream_session_id_resolver=MagicMock(
                resolve_stream_session_id=MagicMock(return_value="test-session")
            ),
            planning_phase_manager=MagicMock(update_counters=AsyncMock()),
            resilience_coordinator=MagicMock(record_success=MagicMock()),
            backend_factory=None,
            backend_lifecycle_manager=None,
            usage_normalization_service=mock_usage_normalization_service,
            wire_capture_orchestrator=None,  # No wire capture
        )

        async def mock_stream() -> AsyncIterator[ProcessedResponse]:
            yield ProcessedResponse(content=b"data: test\n\n", metadata={})

        envelope = StreamingResponseEnvelope(
            content=mock_stream(),
            headers={},
            status_code=200,
        )

        request_context = RequestContext(
            headers={},
            cookies={},
            state=None,
            app_state=None,
            processing_context=ProcessingContext(),
        )

        domain_request = CanonicalChatRequest(
            model="test-model",
            messages=[ChatMessage(role="user", content="test")],
        )

        result = await orchestrator.handle_streaming_response(
            result=envelope,
            backend_type="test-backend",
            effective_model="test-model",
            context=request_context,
            request=domain_request,
            session_id_for_backend="test-session",
            key_name=None,
        )

        # Should not crash when consuming the stream
        assert result.content is not None
        async for _ in result.content:
            pass

        # canonical_usage should still be set on the envelope
        assert result.canonical_usage is not None
