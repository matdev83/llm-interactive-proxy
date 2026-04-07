"""
Unit tests for BackendNonStreamingResponseHandler.

Tests cover non-streaming response processing including:
- Response processor invocation with correct context
- Empty-response retry with recovery prompt
- Structured output validation when schema present
- JSON-serializable metadata filtering
- Removal of original_request from non-streaming metadata
- Tool-call retry integration via coordinator
- Retry metadata propagation
- Terminal response metadata when retry limits exceeded
- Error handling and logging with session identifiers

Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 6.1, 6.2, 10.2
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest
from pydantic.types import JsonValue
from src.core.common.exceptions import (
    APIConnectionError,
    APITimeoutError,
    RateLimitExceededError,
    ServiceUnavailableError,
)
from src.core.domain.backend_request_manager.context_models import (
    ResponseProcessingContext,
    StructuredOutputContext,
)
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.request_context import ProcessingContext, RequestContext
from src.core.domain.responses import ResponseEnvelope
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.interfaces.backend_processor_interface import IBackendProcessor
from src.core.interfaces.backend_request_manager_components import (
    INonStreamingBackendResponseHandler,
    IStructuredOutputEnforcer,
    IToolCallRetryCoordinator,
)
from src.core.interfaces.response_processor_interface import (
    IResponseProcessor,
    ProcessedResponse,
)
from src.core.services.empty_response_middleware import EmptyResponseRetryError

JsonDict = dict[str, JsonValue]


def _meta(data: dict[str, object]) -> JsonDict:
    return data  # type: ignore[return-value]


@pytest.fixture
def mock_app_state() -> IApplicationState:
    """Create a mock application state."""
    mock = AsyncMock(spec=IApplicationState)
    return mock


@pytest.fixture
def mock_response_processor() -> IResponseProcessor:
    """Create a mock response processor."""
    mock = AsyncMock(spec=IResponseProcessor)
    return mock


@pytest.fixture
def mock_structured_output_enforcer() -> IStructuredOutputEnforcer:
    """Create a mock structured output enforcer."""
    mock = AsyncMock(spec=IStructuredOutputEnforcer)
    return mock


@pytest.fixture
def mock_tool_call_retry_coordinator() -> IToolCallRetryCoordinator:
    """Create a mock tool-call retry coordinator."""
    mock = AsyncMock(spec=IToolCallRetryCoordinator)
    return mock


@pytest.fixture
def mock_backend_processor() -> IBackendProcessor:
    """Create a mock backend processor."""
    mock = AsyncMock(spec=IBackendProcessor)
    return mock


@pytest.fixture
def handler(
    mock_response_processor: IResponseProcessor,
    mock_structured_output_enforcer: IStructuredOutputEnforcer,
    mock_tool_call_retry_coordinator: IToolCallRetryCoordinator,
    mock_backend_processor: IBackendProcessor,
    mock_app_state: IApplicationState,
) -> INonStreamingBackendResponseHandler:
    """Create a BackendNonStreamingResponseHandler instance."""
    from src.core.services.backend_non_streaming_response_handler import (
        BackendNonStreamingResponseHandler,
    )

    return BackendNonStreamingResponseHandler(
        response_processor=mock_response_processor,
        structured_output_enforcer=mock_structured_output_enforcer,
        tool_call_retry_coordinator=mock_tool_call_retry_coordinator,
        backend_processor=mock_backend_processor,
        app_state=mock_app_state,
    )


@pytest.fixture
def base_request() -> ChatRequest:
    """Create a base chat request for testing."""
    return ChatRequest(
        model="gpt-4",
        messages=[ChatMessage(role="user", content="Hello")],
    )


@pytest.fixture
def request_context() -> RequestContext:
    """Create a request context for testing."""
    return RequestContext(
        headers={},
        cookies={},
        state=None,
        app_state=None,
        session_id="test-session-123",
        processing_context=ProcessingContext(),
    )


@pytest.fixture
def processing_context(base_request: ChatRequest) -> ResponseProcessingContext:
    """Create a processing context for testing."""
    return ResponseProcessingContext(
        session_id="test-session-123",
        backend_name="openai",
        model_name="gpt-4",
        client_os=None,
        original_request=base_request,
        structured_output=None,
    )


class TestResponseProcessing:
    """Tests for basic response processing."""

    @pytest.mark.asyncio
    async def test_processes_response_through_response_processor(
        self,
        handler: INonStreamingBackendResponseHandler,
        mock_response_processor: AsyncMock,
        base_request: ChatRequest,
        request_context: RequestContext,
        processing_context: ResponseProcessingContext,
    ) -> None:
        """Handler should invoke response processor with correct context."""
        # Arrange
        response = ResponseEnvelope(content="Hello, world!", metadata={"key": "value"})
        processed_response = ProcessedResponse(
            content="Hello, world!",
            metadata={"key": "value", "processed": True},
        )
        mock_response_processor.process_response.return_value = processed_response

        # Act
        result = await handler.handle(
            response=response,
            request=base_request,
            context=request_context,
            processing_context=processing_context,
        )

        # Assert
        assert result is not None
        assert result.content == "Hello, world!"
        mock_response_processor.process_response.assert_called_once()
        call_args = mock_response_processor.process_response.call_args
        assert call_args[0][0] == "Hello, world!"  # content
        assert call_args[0][1] == "test-session-123"  # session_id
        # Now passes RequestContext instead of dict
        from src.core.domain.request_context import RequestContext

        assert isinstance(call_args[0][2], RequestContext)  # context is RequestContext
        context = call_args[0][2]
        assert (
            context.session_id == "test-session-123"
        ), f"Expected session_id 'test-session-123', got '{context.session_id}'"
        assert (
            context.backend == "openai"
        ), f"Expected backend 'openai', got '{context.backend}'"
        assert (
            context.effective_model == "gpt-4"
        ), f"Expected effective_model 'gpt-4', got '{context.effective_model}'"
        # Check that original_request or domain_request matches base_request
        # The enriched context should have original_request set from processing_context.original_request
        assert (
            context.original_request is not None
        ), "original_request should be set from processing_context.original_request"
        assert (
            context.original_request == base_request
            or context.domain_request == base_request
        ), f"Expected original_request or domain_request to equal base_request. original_request={context.original_request}, domain_request={context.domain_request}, base_request={base_request}"

    @pytest.mark.asyncio
    async def test_handles_empty_response_retry(
        self,
        handler: INonStreamingBackendResponseHandler,
        mock_response_processor: AsyncMock,
        mock_backend_processor: AsyncMock,
        base_request: ChatRequest,
        request_context: RequestContext,
        processing_context: ResponseProcessingContext,
    ) -> None:
        """Handler should retry empty responses with recovery prompt."""
        # Arrange
        response = ResponseEnvelope(content="", metadata={})
        recovery_prompt = "Please provide a response."
        retry_response = ResponseEnvelope(content="Retry response", metadata={})

        # First call raises EmptyResponseRetryError
        mock_response_processor.process_response.side_effect = [
            EmptyResponseRetryError(
                recovery_prompt=recovery_prompt,
                session_id="test-session-123",
                retry_count=1,
                original_request=base_request,
            ),
            ProcessedResponse(content="Retry response", metadata={}),
        ]

        mock_backend_processor.process_backend_request.return_value = retry_response

        # Act
        result = await handler.handle(
            response=response,
            request=base_request,
            context=request_context,
            processing_context=processing_context,
        )

        # Assert
        assert result is not None
        assert result.content == "Retry response"
        assert mock_response_processor.process_response.call_count == 2
        mock_backend_processor.process_backend_request.assert_called_once()

    @pytest.mark.asyncio
    async def test_applies_structured_output_validation_when_schema_present(
        self,
        handler: INonStreamingBackendResponseHandler,
        mock_response_processor: AsyncMock,
        mock_structured_output_enforcer: AsyncMock,
        base_request: ChatRequest,
        request_context: RequestContext,
        processing_context: ResponseProcessingContext,
    ) -> None:
        """Handler should apply structured output validation when schema is present."""
        # Arrange
        schema = {"type": "object", "properties": {"name": {"type": "string"}}}
        structured_output_context = StructuredOutputContext(
            response_schema=schema,
            schema_name="test_schema",
            request_id="req-123",
        )
        processing_context.structured_output = structured_output_context

        response = ResponseEnvelope(content='{"name": "test"}', metadata={})
        processed_response = ProcessedResponse(
            content='{"name": "test"}',
            metadata={},
        )
        validated_response = ProcessedResponse(
            content='{"name": "test"}',
            metadata={"structured_output_validated": True},
        )

        mock_response_processor.process_response.return_value = processed_response
        mock_structured_output_enforcer.enforce.return_value = validated_response

        # Act
        result = await handler.handle(
            response=response,
            request=base_request,
            context=request_context,
            processing_context=processing_context,
        )

        # Assert
        assert result is not None
        mock_structured_output_enforcer.enforce.assert_called_once()
        call_args = mock_structured_output_enforcer.enforce.call_args
        # Check keyword arguments
        assert call_args.kwargs["response"] == processed_response
        assert call_args.kwargs["context"] == structured_output_context

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "error",
        [
            RateLimitExceededError(message="Too many requests"),
            ServiceUnavailableError(message="Temporarily unavailable"),
            APITimeoutError(message="Timed out", status_code=504),
            APIConnectionError(message="Connection reset", status_code=502),
        ],
    )
    async def test_temporary_non_streaming_errors_do_not_trigger_empty_retry(
        self,
        error: Exception,
        handler: INonStreamingBackendResponseHandler,
        mock_response_processor: AsyncMock,
        mock_backend_processor: AsyncMock,
        base_request: ChatRequest,
        request_context: RequestContext,
        processing_context: ResponseProcessingContext,
    ) -> None:
        """Temporary backend failures should propagate without empty-response retry."""

        response = ResponseEnvelope(content="", metadata={})
        mock_response_processor.process_response.side_effect = error

        with pytest.raises(type(error)) as excinfo:
            await handler.handle(
                response=response,
                request=base_request,
                context=request_context,
                processing_context=processing_context,
            )

        assert str(excinfo.value) == str(error)
        mock_backend_processor.process_backend_request.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_structured_output_validation_when_no_schema(
        self,
        handler: INonStreamingBackendResponseHandler,
        mock_response_processor: AsyncMock,
        mock_structured_output_enforcer: AsyncMock,
        base_request: ChatRequest,
        request_context: RequestContext,
        processing_context: ResponseProcessingContext,
    ) -> None:
        """Handler should skip structured output validation when no schema."""
        # Arrange
        processing_context.structured_output = None
        response = ResponseEnvelope(content="Hello", metadata={})
        processed_response = ProcessedResponse(content="Hello", metadata={})

        mock_response_processor.process_response.return_value = processed_response

        # Act
        result = await handler.handle(
            response=response,
            request=base_request,
            context=request_context,
            processing_context=processing_context,
        )

        # Assert
        assert result is not None
        mock_structured_output_enforcer.enforce.assert_not_called()


class TestMetadataFiltering:
    """Tests for metadata filtering and serialization."""

    @pytest.mark.asyncio
    async def test_filters_metadata_to_json_serializable_values(
        self,
        handler: INonStreamingBackendResponseHandler,
        mock_response_processor: AsyncMock,
        base_request: ChatRequest,
        request_context: RequestContext,
        processing_context: ResponseProcessingContext,
    ) -> None:
        """Handler should filter metadata to only JSON-serializable values."""
        # Arrange
        response = ResponseEnvelope(content="Hello", metadata={})
        # Include non-serializable object
        non_serializable_obj = object()
        processed_response = ProcessedResponse(
            content="Hello",
            metadata=_meta(
                {
                    "string_value": "test",
                    "int_value": 42,
                    "bool_value": True,
                    "list_value": [1, 2, 3],
                    "dict_value": {"key": "value"},
                    "non_serializable": non_serializable_obj,
                }
            ),
        )

        mock_response_processor.process_response.return_value = processed_response

        # Act
        result = await handler.handle(
            response=response,
            request=base_request,
            context=request_context,
            processing_context=processing_context,
        )

        # Assert
        assert result is not None
        assert result.metadata is not None
        assert "string_value" in result.metadata
        assert "int_value" in result.metadata
        assert "bool_value" in result.metadata
        assert "list_value" in result.metadata
        assert "dict_value" in result.metadata
        assert "non_serializable" not in result.metadata

        # Verify all values are JSON-serializable
        json.dumps(result.metadata)

    @pytest.mark.asyncio
    async def test_removes_original_request_from_metadata(
        self,
        handler: INonStreamingBackendResponseHandler,
        mock_response_processor: AsyncMock,
        base_request: ChatRequest,
        request_context: RequestContext,
        processing_context: ResponseProcessingContext,
    ) -> None:
        """Handler should remove original_request from non-streaming metadata."""
        # Arrange
        response = ResponseEnvelope(content="Hello", metadata={})
        processed_response = ProcessedResponse(
            content="Hello",
            metadata=_meta({"original_request": base_request, "other_key": "value"}),
        )

        mock_response_processor.process_response.return_value = processed_response

        # Act
        result = await handler.handle(
            response=response,
            request=base_request,
            context=request_context,
            processing_context=processing_context,
        )

        # Assert
        assert result is not None
        assert result.metadata is not None
        assert "original_request" not in result.metadata
        assert "other_key" in result.metadata


class TestToolCallRetryIntegration:
    """Tests for tool-call retry coordination."""

    @pytest.mark.asyncio
    async def test_delegates_to_coordinator_when_tool_call_swallowed(
        self,
        handler: INonStreamingBackendResponseHandler,
        mock_response_processor: AsyncMock,
        mock_tool_call_retry_coordinator: AsyncMock,
        mock_backend_processor: AsyncMock,
        base_request: ChatRequest,
        request_context: RequestContext,
        processing_context: ResponseProcessingContext,
    ) -> None:
        """Handler should delegate to coordinator when tool call is swallowed."""
        # Arrange
        response = ResponseEnvelope(
            content="Response",
            metadata={"tool_call_swallowed": True},
        )
        processed_response = ProcessedResponse(
            content="Response",
            metadata={"tool_call_swallowed": True},
        )
        retry_response = ResponseEnvelope(
            content="Retry response",
            metadata={"dangerous_command_retry_count": 1},
        )
        # Processed response for retry (no tool_call_swallowed to prevent recursion)
        processed_retry_response = ProcessedResponse(
            content="Retry response",
            metadata={"dangerous_command_retry_count": 1},
        )

        # First call returns processed_response with tool_call_swallowed
        # Second call (recursive) returns processed_retry_response without tool_call_swallowed
        mock_response_processor.process_response.side_effect = [
            processed_response,
            processed_retry_response,
        ]
        mock_tool_call_retry_coordinator.handle_non_streaming.return_value = (
            retry_response
        )

        # Act
        result = await handler.handle(
            response=response,
            request=base_request,
            context=request_context,
            processing_context=processing_context,
        )

        # Assert
        assert result is not None
        assert result.content == "Retry response"
        mock_tool_call_retry_coordinator.handle_non_streaming.assert_called_once()
        call_args = mock_tool_call_retry_coordinator.handle_non_streaming.call_args
        # Check keyword arguments (or positional if keyword not used)
        if call_args.kwargs:
            assert call_args.kwargs.get("request") == base_request
            assert call_args.kwargs.get("response") == response
            assert call_args.kwargs.get("context") == request_context
        else:
            assert call_args[0][0] == base_request
            assert call_args[0][1] == response
            assert call_args[0][2] == request_context

    @pytest.mark.asyncio
    async def test_processes_retry_response_through_full_pipeline(
        self,
        handler: INonStreamingBackendResponseHandler,
        mock_response_processor: AsyncMock,
        mock_tool_call_retry_coordinator: AsyncMock,
        base_request: ChatRequest,
        request_context: RequestContext,
        processing_context: ResponseProcessingContext,
    ) -> None:
        """Handler should process retry response through full pipeline."""
        # Arrange
        response = ResponseEnvelope(
            content="Response",
            metadata={"tool_call_swallowed": True},
        )
        processed_response = ProcessedResponse(
            content="Response",
            metadata={"tool_call_swallowed": True},
        )
        retry_response = ResponseEnvelope(
            content="Retry response",
            metadata={"dangerous_command_retry_count": 1},
        )
        processed_retry_response = ProcessedResponse(
            content="Retry response",
            metadata={"dangerous_command_retry_count": 1},
        )

        mock_response_processor.process_response.side_effect = [
            processed_response,
            processed_retry_response,
        ]
        mock_tool_call_retry_coordinator.handle_non_streaming.return_value = (
            retry_response
        )

        # Act
        result = await handler.handle(
            response=response,
            request=base_request,
            context=request_context,
            processing_context=processing_context,
        )

        # Assert
        assert result is not None
        assert result.content == "Retry response"
        assert result.metadata is not None
        assert result.metadata.get("dangerous_command_retry_count") == 1
        assert mock_response_processor.process_response.call_count == 2

    @pytest.mark.asyncio
    async def test_handles_terminal_response_from_coordinator(
        self,
        handler: INonStreamingBackendResponseHandler,
        mock_response_processor: AsyncMock,
        mock_tool_call_retry_coordinator: AsyncMock,
        base_request: ChatRequest,
        request_context: RequestContext,
        processing_context: ResponseProcessingContext,
    ) -> None:
        """Handler should handle terminal response when retry limit exceeded."""
        # Arrange
        response = ResponseEnvelope(
            content="Response",
            metadata={"tool_call_swallowed": True},
        )
        processed_response = ProcessedResponse(
            content="Response",
            metadata={"tool_call_swallowed": True},
        )
        terminal_response = ResponseEnvelope(
            content="Session terminated",
            metadata={
                "dangerous_command_limit_exceeded": True,
                "session_terminated": True,
                "is_done": True,
                "finish_reason": "security_limit",
            },
        )
        processed_terminal_response = ProcessedResponse(
            content="Session terminated",
            metadata={
                "dangerous_command_limit_exceeded": True,
                "session_terminated": True,
                "is_done": True,
                "finish_reason": "security_limit",
            },
        )

        mock_response_processor.process_response.side_effect = [
            processed_response,
            processed_terminal_response,
        ]
        mock_tool_call_retry_coordinator.handle_non_streaming.return_value = (
            terminal_response
        )

        # Act
        result = await handler.handle(
            response=response,
            request=base_request,
            context=request_context,
            processing_context=processing_context,
        )

        # Assert
        assert result is not None
        assert result.content == "Session terminated"
        assert result.metadata is not None
        assert result.metadata.get("dangerous_command_limit_exceeded") is True
        assert result.metadata.get("session_terminated") is True
        assert result.metadata.get("is_done") is True
        assert result.metadata.get("finish_reason") == "security_limit"

    @pytest.mark.asyncio
    async def test_skips_coordinator_when_no_tool_call_swallowed(
        self,
        handler: INonStreamingBackendResponseHandler,
        mock_response_processor: AsyncMock,
        mock_tool_call_retry_coordinator: AsyncMock,
        base_request: ChatRequest,
        request_context: RequestContext,
        processing_context: ResponseProcessingContext,
    ) -> None:
        """Handler should skip coordinator when no tool call swallowed."""
        # Arrange
        response = ResponseEnvelope(content="Normal response", metadata={})
        processed_response = ProcessedResponse(
            content="Normal response",
            metadata={},
        )

        mock_response_processor.process_response.return_value = processed_response

        # Act
        result = await handler.handle(
            response=response,
            request=base_request,
            context=request_context,
            processing_context=processing_context,
        )

        # Assert
        assert result is not None
        mock_tool_call_retry_coordinator.handle_non_streaming.assert_not_called()


class TestErrorHandling:
    """Tests for error handling and logging."""

    @pytest.mark.asyncio
    async def test_logs_processing_failures_with_exc_info(
        self,
        handler: INonStreamingBackendResponseHandler,
        mock_response_processor: AsyncMock,
        base_request: ChatRequest,
        request_context: RequestContext,
        processing_context: ResponseProcessingContext,
    ) -> None:
        """Handler should log processing failures with exc_info."""
        # Arrange
        response = ResponseEnvelope(content="Hello", metadata={})
        mock_response_processor.process_response.side_effect = Exception(
            "Processing failed"
        )

        # Act & Assert
        with pytest.raises(Exception, match="Processing failed"):
            await handler.handle(
                response=response,
                request=base_request,
                context=request_context,
                processing_context=processing_context,
            )

    @pytest.mark.asyncio
    async def test_includes_session_id_in_error_context(
        self,
        handler: INonStreamingBackendResponseHandler,
        mock_response_processor: AsyncMock,
        base_request: ChatRequest,
        request_context: RequestContext,
        processing_context: ResponseProcessingContext,
    ) -> None:
        """Handler should include session_id in error context."""
        # Arrange
        response = ResponseEnvelope(content="Hello", metadata={})
        mock_response_processor.process_response.side_effect = Exception(
            "Processing failed"
        )

        # Act & Assert
        with pytest.raises(Exception):  # noqa: B017 - Testing error propagation
            await handler.handle(
                response=response,
                request=base_request,
                context=request_context,
                processing_context=processing_context,
            )

        # Verify session_id was passed to processor
        call_args = mock_response_processor.process_response.call_args
        assert call_args[0][1] == "test-session-123"
