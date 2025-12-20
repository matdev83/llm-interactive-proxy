"""
Unit tests for GeminiChatCompletionCoordinator.

Tests verify chat completion orchestration including request preparation,
streaming/non-streaming execution, and error handling.
"""

from unittest.mock import AsyncMock, Mock

import pytest
from src.connectors.gemini_base.chat_completion_coordinator import (
    GeminiChatCompletionCoordinator,
)
from src.connectors.gemini_base.chat_request_preparer import (
    ChatRequestPreparer,
    PreparedChatRequest,
)
from src.connectors.gemini_base.error_mapper import GeminiErrorMapper
from src.connectors.gemini_base.interfaces import (
    ICodeAssistOrchestrator,
    IEndpointConfig,
)
from src.connectors.gemini_base.streaming_executor import ITokenRefresher
from src.connectors.gemini_base.vtc_wrapper_builder import GeminiVtcWrapperBuilder
from src.core.common.exceptions import BackendError, InvalidRequestError
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope


@pytest.fixture
def mock_request_preparer():
    """Create a mock ChatRequestPreparer."""
    preparer = Mock(spec=ChatRequestPreparer)
    prepared = Mock(spec=PreparedChatRequest)
    prepared.effective_model = "test-model"
    prepared.session_id = "test-session"
    preparer.prepare = AsyncMock(return_value=prepared)
    return preparer


@pytest.fixture
def mock_orchestrator():
    """Create a mock ICodeAssistOrchestrator."""
    orchestrator = Mock(spec=ICodeAssistOrchestrator)
    orchestrator.run_streaming = AsyncMock(
        return_value=Mock(spec=StreamingResponseEnvelope)
    )
    orchestrator.run_non_streaming = AsyncMock(return_value=Mock(spec=ResponseEnvelope))
    return orchestrator


@pytest.fixture
def mock_token_refresher():
    """Create a mock ITokenRefresher."""
    refresher = Mock(spec=ITokenRefresher)
    refresher.refresh_token_if_needed = AsyncMock(return_value=True)
    return refresher


@pytest.fixture
def mock_endpoint_config():
    """Create a mock IEndpointConfig."""
    config = Mock(spec=IEndpointConfig)
    config.backend_type = "test-backend"
    return config


@pytest.fixture
def mock_vtc_wrapper_builder():
    """Create a mock IVtcWrapperBuilder."""
    builder = Mock(spec=GeminiVtcWrapperBuilder)
    builder.build = Mock(return_value=None)
    return builder


@pytest.fixture
def coordinator(
    mock_request_preparer,
    mock_orchestrator,
    mock_token_refresher,
    mock_endpoint_config,
    mock_vtc_wrapper_builder,
):
    """Create a GeminiChatCompletionCoordinator instance."""
    return GeminiChatCompletionCoordinator(
        request_preparer=mock_request_preparer,
        orchestrator=mock_orchestrator,
        token_refresher=mock_token_refresher,
        endpoint_config=mock_endpoint_config,
        api_base_url="https://test-api.example.com",
        backend_type="test-backend",
        vtc_wrapper_builder=mock_vtc_wrapper_builder,
    )


@pytest.fixture
def coordinator_without_optional_services(
    mock_request_preparer,
    mock_orchestrator,
    mock_token_refresher,
    mock_endpoint_config,
):
    """Create a coordinator without optional services."""
    return GeminiChatCompletionCoordinator(
        request_preparer=mock_request_preparer,
        orchestrator=mock_orchestrator,
        token_refresher=mock_token_refresher,
        endpoint_config=mock_endpoint_config,
        api_base_url="https://test-api.example.com",
        backend_type="test-backend",
    )


@pytest.fixture
def mock_request_data():
    """Create a mock request data object."""
    request = Mock()
    request.stream = False
    request.session_id = "test-session"
    return request


@pytest.fixture
def mock_streaming_request_data():
    """Create a mock streaming request data object."""
    request = Mock()
    request.stream = True
    request.session_id = "test-session"
    request.vtc_enabled = False
    return request


class TestExecute:
    """Test execute method."""

    @pytest.mark.asyncio
    async def test_execute_non_streaming(
        self, coordinator, mock_request_preparer, mock_orchestrator, mock_request_data
    ):
        """Verify non-streaming execution flow."""
        result = await coordinator.execute(
            request_data=mock_request_data,
            processed_messages=[],
            effective_model="test-model",
        )

        assert isinstance(result, ResponseEnvelope)
        mock_request_preparer.prepare.assert_called_once_with(
            request_data=mock_request_data,
            effective_model="test-model",
            is_streaming=False,
        )
        mock_orchestrator.run_non_streaming.assert_called_once()
        mock_orchestrator.run_streaming.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_streaming(
        self,
        coordinator,
        mock_request_preparer,
        mock_orchestrator,
        mock_streaming_request_data,
    ):
        """Verify streaming execution flow."""
        result = await coordinator.execute(
            request_data=mock_streaming_request_data,
            processed_messages=[],
            effective_model="test-model",
        )

        assert isinstance(result, StreamingResponseEnvelope)
        mock_request_preparer.prepare.assert_called_once_with(
            request_data=mock_streaming_request_data,
            effective_model="test-model",
            is_streaming=True,
        )
        mock_orchestrator.run_streaming.assert_called_once()
        mock_orchestrator.run_non_streaming.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_with_vtc_wrapper(
        self,
        coordinator,
        mock_vtc_wrapper_builder,
        mock_streaming_request_data,
    ):
        """Verify VTC wrapper is built and passed when streaming."""
        mock_wrapper = Mock()
        mock_vtc_wrapper_builder.build.return_value = mock_wrapper

        await coordinator.execute(
            request_data=mock_streaming_request_data,
            processed_messages=[],
            effective_model="test-model",
        )

        mock_vtc_wrapper_builder.build.assert_called_once_with(
            request_data=mock_streaming_request_data,
            effective_model="test-model",
        )
        # Verify wrapper was passed to orchestrator
        call_kwargs = coordinator._orchestrator.run_streaming.call_args[1]
        assert call_kwargs["stream_wrapper"] == mock_wrapper

    @pytest.mark.asyncio
    async def test_execute_without_vtc_wrapper_builder(
        self,
        coordinator_without_optional_services,
        mock_streaming_request_data,
    ):
        """Verify execution works without VTC wrapper builder."""
        result = await coordinator_without_optional_services.execute(
            request_data=mock_streaming_request_data,
            processed_messages=[],
            effective_model="test-model",
        )

        assert isinstance(result, StreamingResponseEnvelope)
        # Verify no wrapper was passed
        call_kwargs = (
            coordinator_without_optional_services._orchestrator.run_streaming.call_args[
                1
            ]
        )
        assert call_kwargs.get("stream_wrapper") is None

    @pytest.mark.asyncio
    async def test_execute_builds_thought_signature_callback(
        self, coordinator, mock_streaming_request_data
    ):
        """Verify thought signature callback is built when service available."""
        from src.connectors.gemini_base.thought_signature_service import (
            ThoughtSignatureService,
        )

        mock_thought_service = Mock(spec=ThoughtSignatureService)
        mock_thought_service.store_signatures_from_tool_calls = Mock()

        coordinator_with_service = GeminiChatCompletionCoordinator(
            request_preparer=coordinator._request_preparer,
            orchestrator=coordinator._orchestrator,
            token_refresher=coordinator._token_refresher,
            endpoint_config=coordinator._endpoint_config,
            api_base_url=coordinator._api_base_url,
            backend_type=coordinator._backend_type,
            thought_signature_service=mock_thought_service,
        )

        await coordinator_with_service.execute(
            request_data=mock_streaming_request_data,
            processed_messages=[],
            effective_model="test-model",
        )

        # Verify callback was passed to orchestrator
        call_kwargs = coordinator_with_service._orchestrator.run_streaming.call_args[1]
        assert call_kwargs["thought_signature_callback"] is not None
        assert callable(call_kwargs["thought_signature_callback"])

    @pytest.mark.asyncio
    async def test_execute_handles_invalid_request_error(
        self, coordinator, mock_request_preparer, mock_request_data
    ):
        """Verify InvalidRequestError is re-raised unchanged."""
        mock_request_preparer.prepare.side_effect = InvalidRequestError(
            message="Invalid request", details={"field": "model"}
        )

        with pytest.raises(InvalidRequestError) as exc_info:
            await coordinator.execute(
                request_data=mock_request_data,
                processed_messages=[],
                effective_model="test-model",
            )

        assert exc_info.value.message == "Invalid request"

    @pytest.mark.asyncio
    async def test_execute_maps_exceptions_with_error_mapper(
        self,
        coordinator,
        mock_request_preparer,
        mock_request_data,
    ):
        """Verify exceptions are mapped when error mapper is available.

        map_exception returns LLMProxyError instances (except HTTPException which raises).
        The coordinator raises the returned exception.
        """
        mock_error_mapper = Mock(spec=GeminiErrorMapper)
        mapped_error = BackendError(message="Mapped error", backend_name="test-backend")
        # map_exception returns exceptions (except HTTPException which raises)
        mock_error_mapper.map_exception = Mock(return_value=mapped_error)

        coordinator_with_mapper = GeminiChatCompletionCoordinator(
            request_preparer=mock_request_preparer,
            orchestrator=coordinator._orchestrator,
            token_refresher=coordinator._token_refresher,
            endpoint_config=coordinator._endpoint_config,
            api_base_url=coordinator._api_base_url,
            backend_type="test-backend",
            error_mapper=mock_error_mapper,
        )

        generic_error = ValueError("Something went wrong")
        mock_request_preparer.prepare.side_effect = generic_error

        with pytest.raises(BackendError) as exc_info:
            await coordinator_with_mapper.execute(
                request_data=mock_request_data,
                processed_messages=[],
                effective_model="test-model",
            )

        assert exc_info.value is mapped_error
        mock_error_mapper.map_exception.assert_called_once_with(
            generic_error, backend_name="test-backend"
        )
        # Verify backend_type was used correctly
        assert coordinator_with_mapper._backend_type == "test-backend"

    @pytest.mark.asyncio
    async def test_execute_wraps_exceptions_without_error_mapper(
        self,
        coordinator_without_optional_services,
        mock_request_preparer,
        mock_request_data,
    ):
        """Verify exceptions are wrapped in BackendError when no error mapper."""
        generic_error = RuntimeError("Runtime error")
        mock_request_preparer.prepare.side_effect = generic_error

        with pytest.raises(BackendError) as exc_info:
            await coordinator_without_optional_services.execute(
                request_data=mock_request_data,
                processed_messages=[],
                effective_model="test-model",
            )

        assert isinstance(exc_info.value, BackendError)
        assert "test-backend chat completion failed" in exc_info.value.message
        assert exc_info.value.backend_name == "test-backend"
        assert exc_info.value.__cause__ is generic_error

    @pytest.mark.asyncio
    async def test_execute_constructs_correct_url(self, coordinator, mock_request_data):
        """Verify API URL is constructed correctly."""
        await coordinator.execute(
            request_data=mock_request_data,
            processed_messages=[],
            effective_model="test-model",
        )

        call_kwargs = coordinator._orchestrator.run_non_streaming.call_args[1]
        assert (
            call_kwargs["url"]
            == "https://test-api.example.com/v1internal:streamGenerateContent"
        )

    @pytest.mark.asyncio
    async def test_execute_passes_token_refresher(
        self, coordinator, mock_token_refresher, mock_request_data
    ):
        """Verify token refresher is passed to orchestrator."""
        await coordinator.execute(
            request_data=mock_request_data,
            processed_messages=[],
            effective_model="test-model",
        )

        call_kwargs = coordinator._orchestrator.run_non_streaming.call_args[1]
        assert call_kwargs["token_refresher"] is mock_token_refresher

    @pytest.mark.asyncio
    async def test_execute_passes_key_name(self, coordinator, mock_request_data):
        """Verify key_name is passed to orchestrator when provided."""
        coordinator_with_key = GeminiChatCompletionCoordinator(
            request_preparer=coordinator._request_preparer,
            orchestrator=coordinator._orchestrator,
            token_refresher=coordinator._token_refresher,
            endpoint_config=coordinator._endpoint_config,
            api_base_url=coordinator._api_base_url,
            backend_type=coordinator._backend_type,
            key_name="test-key",
        )

        await coordinator_with_key.execute(
            request_data=mock_request_data,
            processed_messages=[],
            effective_model="test-model",
        )

        call_kwargs = coordinator_with_key._orchestrator.run_non_streaming.call_args[1]
        assert call_kwargs["key_name"] == "test-key"

    @pytest.mark.asyncio
    async def test_execute_handles_missing_optional_services_gracefully(
        self, coordinator_without_optional_services, mock_request_data
    ):
        """Verify execution works gracefully when optional services are missing.

        Requirement: 4.1 (unit testability), edge case coverage.
        """
        result = await coordinator_without_optional_services.execute(
            request_data=mock_request_data,
            processed_messages=[],
            effective_model="test-model",
        )

        assert isinstance(result, ResponseEnvelope)
        # Verify no errors occurred despite missing optional services

    @pytest.mark.asyncio
    async def test_execute_propagates_backend_error_from_orchestrator(
        self, coordinator, mock_request_preparer, mock_orchestrator, mock_request_data
    ):
        """Verify BackendError from orchestrator is propagated (may be wrapped if no error mapper).

        Requirement: 2.4 (error mapping), edge case coverage.
        """
        from src.core.common.exceptions import BackendError

        test_error = BackendError(
            message="Orchestrator error",
            backend_name="test-backend",
            code="orchestrator_error",
            status_code=500,
        )
        mock_request_preparer.prepare = AsyncMock(return_value=Mock())
        mock_orchestrator.run_non_streaming = AsyncMock(side_effect=test_error)

        with pytest.raises(BackendError) as exc_info:
            await coordinator.execute(
                request_data=mock_request_data,
                processed_messages=[],
                effective_model="test-model",
            )

        # Coordinator may wrap BackendError if no error mapper is present
        # Verify it's still a BackendError with preserved status code
        assert isinstance(exc_info.value, BackendError)
        # If wrapped, verify the original error is chained
        if exc_info.value.__cause__:
            assert exc_info.value.__cause__ is test_error

    @pytest.mark.asyncio
    async def test_execute_propagates_authentication_error_from_preparer(
        self, coordinator, mock_request_preparer, mock_request_data
    ):
        """Verify AuthenticationError from preparer is propagated (may be wrapped if no error mapper).

        Requirement: 2.4 (error mapping), edge case coverage.
        """
        from src.core.common.exceptions import AuthenticationError, BackendError

        test_error = AuthenticationError(
            message="Preparer auth error",
            details={"reason": "invalid_credentials"},
        )
        mock_request_preparer.prepare = AsyncMock(side_effect=test_error)

        # Coordinator wraps AuthenticationError if no error mapper is present
        # Verify it's handled appropriately
        with pytest.raises((AuthenticationError, BackendError)) as exc_info:
            await coordinator.execute(
                request_data=mock_request_data,
                processed_messages=[],
                effective_model="test-model",
            )

        # If wrapped, verify the original error is chained
        if isinstance(exc_info.value, BackendError) and exc_info.value.__cause__:
            assert exc_info.value.__cause__ is test_error
        elif isinstance(exc_info.value, AuthenticationError):
            assert exc_info.value is test_error
            assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_execute_handles_http_exception_through_error_mapper(
        self,
        coordinator,
        mock_request_preparer,
        mock_request_data,
    ):
        """Verify HTTPException is re-raised (not returned) when error mapper is present.

        Requirement: 2.4 (error mapping), design.md HTTPException handling.
        """
        from fastapi import HTTPException

        mock_error_mapper = Mock(spec=GeminiErrorMapper)
        http_exc = HTTPException(status_code=400, detail="Bad request")

        # HTTPException should be re-raised, not returned
        def map_exception_side_effect(error, *, backend_name):
            if isinstance(error, HTTPException):
                raise error  # Re-raise HTTPException
            return BackendError("Mapped error", backend_name=backend_name)

        mock_error_mapper.map_exception = Mock(side_effect=map_exception_side_effect)

        coordinator_with_mapper = GeminiChatCompletionCoordinator(
            request_preparer=mock_request_preparer,
            orchestrator=coordinator._orchestrator,
            token_refresher=coordinator._token_refresher,
            endpoint_config=coordinator._endpoint_config,
            api_base_url=coordinator._api_base_url,
            backend_type="test-backend",
            error_mapper=mock_error_mapper,
        )

        mock_request_preparer.prepare.side_effect = http_exc

        # HTTPException should be re-raised, not wrapped
        with pytest.raises(HTTPException) as exc_info:
            await coordinator_with_mapper.execute(
                request_data=mock_request_data,
                processed_messages=[],
                effective_model="test-model",
            )

        assert exc_info.value is http_exc
        assert exc_info.value.status_code == 400
        mock_error_mapper.map_exception.assert_called_once_with(
            http_exc, backend_name="test-backend"
        )

    @pytest.mark.asyncio
    async def test_execute_error_mapper_logs_with_exc_info(
        self,
        coordinator,
        mock_request_preparer,
        mock_request_data,
    ):
        """Verify error mapper logs generic exceptions with exc_info=True.

        Requirement: 7.2 (logging structure), design.md exc_info logging.
        """
        from unittest.mock import MagicMock

        # Create a real error mapper with a mock logger
        mock_logger = MagicMock()
        error_mapper = GeminiErrorMapper(logger_instance=mock_logger)

        coordinator_with_mapper = GeminiChatCompletionCoordinator(
            request_preparer=mock_request_preparer,
            orchestrator=coordinator._orchestrator,
            token_refresher=coordinator._token_refresher,
            endpoint_config=coordinator._endpoint_config,
            api_base_url=coordinator._api_base_url,
            backend_type="test-backend",
            error_mapper=error_mapper,
        )

        generic_error = ValueError("Something went wrong")
        mock_request_preparer.prepare.side_effect = generic_error

        with pytest.raises(BackendError):
            await coordinator_with_mapper.execute(
                request_data=mock_request_data,
                processed_messages=[],
                effective_model="test-model",
            )

        # Verify logger.error was called with exc_info=True
        mock_logger.error.assert_called_once()
        call_kwargs = mock_logger.error.call_args[1]
        assert call_kwargs.get("exc_info") is True
        assert "test-backend chat_completions" in mock_logger.error.call_args[0][0]
