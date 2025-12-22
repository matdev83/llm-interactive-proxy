"""Unit tests for BackendCompletionFlowEosAdapter.

Tests cover:
- Error type classification mapping
- Session ID extraction from context
- Error status code inclusion
- Backend context inclusion
- Fail-open behavior
- Integration with error handling flow
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from src.core.common.exceptions import (
    APIConnectionError,
    APITimeoutError,
    BackendError,
    RateLimitExceededError,
)
from src.core.config.models.end_of_session import EndOfSessionConfig
from src.core.domain.events.end_of_session_events import (
    EndOfSessionErrorClassification,
    EndOfSessionSignalType,
    EndOfSessionTerminationCategory,
)
from src.core.domain.request_context import RequestContext
from src.core.interfaces.end_of_session_service_interface import IEndOfSessionService
from src.core.services.backend_completion_flow.eos_adapter import (
    BackendCompletionFlowEosAdapter,
)


@pytest.fixture
def mock_eos_service() -> IEndOfSessionService:
    """Create a mock EoS service."""
    mock = MagicMock(spec=IEndOfSessionService)
    mock.record_signal = AsyncMock()
    mock.has_ended = MagicMock(return_value=False)  # Default to not ended
    return mock


@pytest.fixture
def default_config() -> EndOfSessionConfig:
    """Create default EoS configuration."""
    return EndOfSessionConfig(
        enabled=True,
        emit_events=True,
        detect_stream_signals=True,
        detect_tool_completion=True,
    )


@pytest.fixture
def adapter(
    mock_eos_service: IEndOfSessionService, default_config: EndOfSessionConfig
) -> BackendCompletionFlowEosAdapter:
    """Create BackendCompletionFlowEosAdapter instance for testing."""
    return BackendCompletionFlowEosAdapter(
        end_of_session_service=mock_eos_service,
        config=default_config,
    )


@pytest.fixture
def sample_context() -> RequestContext:
    """Create a sample request context."""
    from src.core.domain.request_context import ProcessingContext

    context = RequestContext(
        headers={},
        cookies={},
        state=None,
        app_state=None,
        session_id="test-session-123",
        request_id="req-456",
        processing_context=ProcessingContext(),
    )
    return context


class TestConfigGating:
    """Test configuration gating behavior."""

    @pytest.mark.asyncio
    async def test_disabled_config_skips_recording(
        self,
        mock_eos_service: IEndOfSessionService,
        sample_context: RequestContext,
    ):
        """Test that disabled config prevents recording."""
        config = EndOfSessionConfig(enabled=False)
        adapter = BackendCompletionFlowEosAdapter(
            end_of_session_service=mock_eos_service, config=config
        )

        error = BackendError("Test error", backend_name="openai")
        await adapter.record_error_termination(
            error=error, session_id="test-123", backend_type="openai"
        )

        mock_eos_service.record_signal.assert_not_awaited()


class TestErrorClassification:
    """Test error type classification mapping."""

    @pytest.mark.asyncio
    async def test_classifies_transport_error(
        self,
        adapter: BackendCompletionFlowEosAdapter,
        mock_eos_service: IEndOfSessionService,
    ):
        """Test classification of transport errors."""
        error = APIConnectionError("Connection failed")

        await adapter.record_error_termination(
            error=error, session_id="test-123", backend_type="openai"
        )

        mock_eos_service.record_signal.assert_awaited_once()
        signal = mock_eos_service.record_signal.call_args[0][0]
        assert (
            signal.error_classification
            == EndOfSessionErrorClassification.TRANSPORT_ERROR
        )

    @pytest.mark.asyncio
    async def test_classifies_timeout_error(
        self,
        adapter: BackendCompletionFlowEosAdapter,
        mock_eos_service: IEndOfSessionService,
    ):
        """Test classification of timeout errors."""
        error = APITimeoutError("Request timed out")

        await adapter.record_error_termination(
            error=error, session_id="test-123", backend_type="openai"
        )

        signal = mock_eos_service.record_signal.call_args[0][0]
        assert (
            signal.error_classification
            == EndOfSessionErrorClassification.TRANSPORT_ERROR
        )

    @pytest.mark.asyncio
    async def test_classifies_http_error(
        self,
        adapter: BackendCompletionFlowEosAdapter,
        mock_eos_service: IEndOfSessionService,
    ):
        """Test classification of HTTP errors."""
        from src.core.common.exceptions import LLMProxyError

        # Use a non-BackendError LLMProxyError with status_code for HTTP_ERROR
        error = LLMProxyError("HTTP 500", status_code=500)

        await adapter.record_error_termination(
            error=error, session_id="test-123", backend_type="openai"
        )

        signal = mock_eos_service.record_signal.call_args[0][0]
        assert (
            signal.error_classification
            == EndOfSessionErrorClassification.HTTP_ERROR
        )

    @pytest.mark.asyncio
    async def test_classifies_backend_error(
        self,
        adapter: BackendCompletionFlowEosAdapter,
        mock_eos_service: IEndOfSessionService,
    ):
        """Test classification of backend API errors."""
        # BackendError without status_code should be BACKEND_ERROR
        error = BackendError("Backend API error", backend_name="openai", status_code=None)

        await adapter.record_error_termination(
            error=error, session_id="test-123", backend_type="openai"
        )

        signal = mock_eos_service.record_signal.call_args[0][0]
        assert (
            signal.error_classification
            == EndOfSessionErrorClassification.BACKEND_ERROR
        )

    @pytest.mark.asyncio
    async def test_classifies_unknown_error(
        self,
        adapter: BackendCompletionFlowEosAdapter,
        mock_eos_service: IEndOfSessionService,
    ):
        """Test classification of unknown errors."""
        error = ValueError("Unknown error")

        await adapter.record_error_termination(
            error=error, session_id="test-123", backend_type="openai"
        )

        signal = mock_eos_service.record_signal.call_args[0][0]
        assert (
            signal.error_classification
            == EndOfSessionErrorClassification.UNKNOWN_ERROR
        )

    @pytest.mark.asyncio
    async def test_classifies_httpx_timeout_via_cause(
        self,
        adapter: BackendCompletionFlowEosAdapter,
        mock_eos_service: IEndOfSessionService,
    ):
        """Test classification of httpx.TimeoutException via __cause__."""
        httpx_timeout = httpx.TimeoutException("Request timed out")
        # Create BackendError without status_code to avoid HTTP_ERROR classification
        error = BackendError("Wrapped timeout", backend_name="openai", status_code=None)
        error.__cause__ = httpx_timeout

        await adapter.record_error_termination(
            error=error, session_id="test-123", backend_type="openai"
        )

        signal = mock_eos_service.record_signal.call_args[0][0]
        assert (
            signal.error_classification
            == EndOfSessionErrorClassification.TRANSPORT_ERROR
        )

    @pytest.mark.asyncio
    async def test_classifies_httpx_http_status_error_via_cause(
        self,
        adapter: BackendCompletionFlowEosAdapter,
        mock_eos_service: IEndOfSessionService,
    ):
        """Test classification of httpx.HTTPStatusError via __cause__."""
        response = MagicMock()
        response.status_code = 503
        httpx_error = httpx.HTTPStatusError("HTTP error", request=MagicMock(), response=response)
        error = BackendError("Wrapped HTTP error", backend_name="openai")
        error.__cause__ = httpx_error

        await adapter.record_error_termination(
            error=error, session_id="test-123", backend_type="openai"
        )

        signal = mock_eos_service.record_signal.call_args[0][0]
        assert (
            signal.error_classification
            == EndOfSessionErrorClassification.HTTP_ERROR
        )


class TestSessionIdExtraction:
    """Test session ID extraction from context."""

    @pytest.mark.asyncio
    async def test_extracts_session_id_from_context(
        self,
        adapter: BackendCompletionFlowEosAdapter,
        mock_eos_service: IEndOfSessionService,
        sample_context: RequestContext,
    ):
        """Test that session_id is extracted from context when not provided."""
        error = BackendError("Test error", backend_name="openai")

        await adapter.record_error_termination(
            error=error, session_id=None, backend_type="openai", context=sample_context
        )

        mock_eos_service.record_signal.assert_awaited_once()
        signal = mock_eos_service.record_signal.call_args[0][0]
        assert signal.session_id == sample_context.session_id

    @pytest.mark.asyncio
    async def test_missing_session_id_skips_recording(
        self,
        adapter: BackendCompletionFlowEosAdapter,
        mock_eos_service: IEndOfSessionService,
    ):
        """Test that missing session_id prevents recording."""
        from src.core.domain.request_context import ProcessingContext

        error = BackendError("Test error", backend_name="openai")
        context = RequestContext(
            headers={},
            cookies={},
            state=None,
            app_state=None,
            session_id=None,  # No session_id
            processing_context=ProcessingContext(),
        )

        await adapter.record_error_termination(
            error=error, session_id=None, backend_type="openai", context=context
        )

        mock_eos_service.record_signal.assert_not_awaited()


class TestStatusCodeExtraction:
    """Test HTTP status code extraction."""

    @pytest.mark.asyncio
    async def test_extracts_status_code_from_error(
        self,
        adapter: BackendCompletionFlowEosAdapter,
        mock_eos_service: IEndOfSessionService,
    ):
        """Test that status_code is extracted from error."""
        error = BackendError("HTTP 404", backend_name="openai", status_code=404)

        await adapter.record_error_termination(
            error=error, session_id="test-123", backend_type="openai"
        )

        signal = mock_eos_service.record_signal.call_args[0][0]
        assert signal.error_status_code == 404

    @pytest.mark.asyncio
    async def test_extracts_status_code_from_cause(
        self,
        adapter: BackendCompletionFlowEosAdapter,
        mock_eos_service: IEndOfSessionService,
    ):
        """Test that status_code is extracted from error cause."""
        response = MagicMock()
        response.status_code = 503
        httpx_error = httpx.HTTPStatusError("HTTP error", request=MagicMock(), response=response)
        # Create error without status_code so cause's status_code is used
        error = BackendError("Wrapped error", backend_name="openai", status_code=None)
        error.__cause__ = httpx_error

        await adapter.record_error_termination(
            error=error, session_id="test-123", backend_type="openai"
        )

        signal = mock_eos_service.record_signal.call_args[0][0]
        assert signal.error_status_code == 503


class TestSignalPayload:
    """Test EoS signal payload correctness."""

    @pytest.mark.asyncio
    async def test_signal_includes_all_fields(
        self,
        adapter: BackendCompletionFlowEosAdapter,
        mock_eos_service: IEndOfSessionService,
        sample_context: RequestContext,
    ):
        """Test that signal includes all required fields."""
        error = BackendError("Test error", backend_name="openai", status_code=500)

        await adapter.record_error_termination(
            error=error,
            session_id="test-123",
            backend_type="openai",
            context=sample_context,
        )

        signal = mock_eos_service.record_signal.call_args[0][0]
        assert signal.session_id == "test-123"
        assert signal.signal_type == EndOfSessionSignalType.ERROR_TERMINATION
        assert (
            signal.termination_category == EndOfSessionTerminationCategory.ERROR
        )
        assert signal.error_classification is not None
        assert signal.error_status_code == 500
        assert signal.backend == "openai"
        assert signal.request_id == sample_context.request_id


class TestFailOpen:
    """Test fail-open error handling."""

    @pytest.mark.asyncio
    async def test_service_error_logged_but_not_raised(
        self,
        adapter: BackendCompletionFlowEosAdapter,
        mock_eos_service: IEndOfSessionService,
    ):
        """Test that service errors are logged but not raised."""
        mock_eos_service.record_signal.side_effect = Exception("Service error")
        error = BackendError("Test error", backend_name="openai")

        # Should not raise
        await adapter.record_error_termination(
            error=error, session_id="test-123", backend_type="openai"
        )

        mock_eos_service.record_signal.assert_awaited_once()

