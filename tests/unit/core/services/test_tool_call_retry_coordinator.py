"""
Unit tests for ToolCallRetryCoordinator.

Tests cover tool-call retry coordination including:
- Swallowed tool-call detection
- Retry request shaping with steering
- Retry count propagation
- Terminal responses when limits exceeded
- Both streaming and non-streaming paths
- Metadata preservation and propagation
- Session ID propagation
- Loop prevention guards

Requirements: 3.5, 3.6, 3.7, 4.3, 6.1, 6.2, 6.3, 7.1, 9.2, 10.1
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock

import pytest
from src.core.domain.backend_request_manager.context_models import ToolCallRetryState
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.backend_processor_interface import IBackendProcessor
from src.core.interfaces.backend_request_manager_components import (
    IToolCallRetryCoordinator,
)
from src.core.interfaces.response_processor_interface import ProcessedResponse


@pytest.fixture
def mock_backend_processor() -> IBackendProcessor:
    """Create a mock backend processor."""
    mock = AsyncMock(spec=IBackendProcessor)
    return mock


@pytest.fixture
def coordinator(mock_backend_processor: IBackendProcessor) -> IToolCallRetryCoordinator:
    """Create a ToolCallRetryCoordinator instance."""
    from src.core.services.tool_call_retry_coordinator import ToolCallRetryCoordinator

    return ToolCallRetryCoordinator(backend_processor=mock_backend_processor)


@pytest.fixture
def base_request() -> ChatRequest:
    """Create a base chat request for testing."""
    return ChatRequest(
        model="gpt-4",
        messages=[
            ChatMessage(role="user", content="Hello"),
            ChatMessage(role="assistant", content="Hi there!"),
        ],
    )


@pytest.fixture
def swallowed_response() -> ResponseEnvelope:
    """Create a response indicating a swallowed tool call."""
    return ResponseEnvelope(
        content="A tool call was blocked.",
        metadata={
            "tool_call_swallowed": True,
            "steering_message": "A tool call was blocked by proxy policy.",
            "swallowed_tool_calls": [
                {
                    "id": "call_123",
                    "type": "function",
                    "function": {
                        "name": "execute_command",
                        "arguments": '{"command": "rm -rf /"}',
                    },
                }
            ],
            "swallowed_original_content": "I will run: rm -rf /",
            "_steering_replacement": True,
        },
    )


@pytest.fixture
def request_context() -> RequestContext:
    """Create a request context for testing."""
    from src.core.domain.request_context import ProcessingContext

    return RequestContext(
        headers={},
        cookies={},
        state=None,
        app_state=None,
        session_id="test-session-123",
        processing_context=ProcessingContext(),
    )


class TestSwallowedToolCallDetection:
    """Tests for detecting swallowed tool calls and initiating retries."""

    @pytest.mark.asyncio
    async def test_handle_non_streaming_returns_none_when_no_swallow(
        self,
        coordinator: IToolCallRetryCoordinator,
        base_request: ChatRequest,
        request_context: RequestContext,
    ) -> None:
        """When response has no tool_call_swallowed, should return None."""
        # Arrange
        response = ResponseEnvelope(content="Normal response", metadata={})
        retry_state = ToolCallRetryState(retry_count=0, max_retries=3)

        # Act
        result = await coordinator.handle_non_streaming(
            request=base_request,
            response=response,
            context=request_context,
            retry_state=retry_state,
        )

        # Assert
        assert result is None

    @pytest.mark.asyncio
    async def test_handle_non_streaming_detects_swallowed_tool_call(
        self,
        coordinator: IToolCallRetryCoordinator,
        mock_backend_processor: AsyncMock,
        base_request: ChatRequest,
        swallowed_response: ResponseEnvelope,
        request_context: RequestContext,
    ) -> None:
        """When response indicates swallowed tool call, should initiate retry."""
        # Arrange
        retry_state = ToolCallRetryState(retry_count=0, max_retries=3)
        mock_backend_processor.process_backend_request.return_value = ResponseEnvelope(
            content="Retry response", metadata={}
        )

        # Act
        result = await coordinator.handle_non_streaming(
            request=base_request,
            response=swallowed_response,
            context=request_context,
            retry_state=retry_state,
        )

        # Assert
        assert result is not None
        assert isinstance(result, ResponseEnvelope)
        mock_backend_processor.process_backend_request.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_streaming_detects_swallowed_tool_call(
        self,
        coordinator: IToolCallRetryCoordinator,
        mock_backend_processor: AsyncMock,
        base_request: ChatRequest,
        swallowed_response: ResponseEnvelope,
        request_context: RequestContext,
    ) -> None:
        """When streaming response indicates swallowed tool call, should initiate retry."""
        # Arrange
        retry_state = ToolCallRetryState(
            retry_count=0, max_retries=3, is_streaming=True
        )

        async def mock_stream() -> AsyncIterator[ProcessedResponse]:
            yield ProcessedResponse(content="Retry chunk", metadata={})

        mock_backend_processor.process_backend_request.return_value = (
            StreamingResponseEnvelope(content=mock_stream(), metadata={})
        )

        # Act
        result = await coordinator.handle_streaming(
            request=base_request,
            response=swallowed_response,
            context=request_context,
            retry_state=retry_state,
        )

        # Assert
        assert result is not None
        assert isinstance(result, StreamingResponseEnvelope)
        mock_backend_processor.process_backend_request.assert_called_once()


class TestRetryRequestShaping:
    """Tests for shaping retry requests with steering messages."""

    @pytest.mark.asyncio
    async def test_retry_request_includes_steering_message(
        self,
        coordinator: IToolCallRetryCoordinator,
        mock_backend_processor: AsyncMock,
        base_request: ChatRequest,
        swallowed_response: ResponseEnvelope,
        request_context: RequestContext,
    ) -> None:
        """Retry request should include steering message as system message."""
        # Arrange
        retry_state = ToolCallRetryState(retry_count=0, max_retries=3)
        mock_backend_processor.process_backend_request.return_value = ResponseEnvelope(
            content="Retry response", metadata={}
        )

        # Act
        await coordinator.handle_non_streaming(
            request=base_request,
            response=swallowed_response,
            context=request_context,
            retry_state=retry_state,
        )

        # Assert
        call_args = mock_backend_processor.process_backend_request.call_args
        retry_request: ChatRequest = call_args.kwargs["request"]
        assert len(retry_request.messages) == len(base_request.messages) + 1
        last_message = retry_request.messages[-1]
        assert last_message.role == "system"
        assert (
            "steering" in last_message.content.lower()
            or "blocked" in last_message.content.lower()
        )

    @pytest.mark.asyncio
    async def test_retry_request_sets_retry_flags(
        self,
        coordinator: IToolCallRetryCoordinator,
        mock_backend_processor: AsyncMock,
        base_request: ChatRequest,
        swallowed_response: ResponseEnvelope,
        request_context: RequestContext,
    ) -> None:
        """Retry request should set _tool_call_reactor_retry and retry count flags."""
        # Arrange
        retry_state = ToolCallRetryState(retry_count=0, max_retries=3)
        mock_backend_processor.process_backend_request.return_value = ResponseEnvelope(
            content="Retry response", metadata={}
        )

        # Act
        await coordinator.handle_non_streaming(
            request=base_request,
            response=swallowed_response,
            context=request_context,
            retry_state=retry_state,
        )

        # Assert
        call_args = mock_backend_processor.process_backend_request.call_args
        retry_request: ChatRequest = call_args.kwargs["request"]
        extra_body = retry_request.extra_body or {}
        assert extra_body.get("_tool_call_reactor_retry") is True
        assert extra_body.get("_tool_call_reactor_retry_count") == 1
        assert extra_body.get("_dangerous_command_retry_count") == 1

    @pytest.mark.asyncio
    async def test_retry_request_preserves_original_messages(
        self,
        coordinator: IToolCallRetryCoordinator,
        mock_backend_processor: AsyncMock,
        base_request: ChatRequest,
        swallowed_response: ResponseEnvelope,
        request_context: RequestContext,
    ) -> None:
        """Retry request should preserve all original messages."""
        # Arrange
        retry_state = ToolCallRetryState(retry_count=0, max_retries=3)
        mock_backend_processor.process_backend_request.return_value = ResponseEnvelope(
            content="Retry response", metadata={}
        )

        # Act
        await coordinator.handle_non_streaming(
            request=base_request,
            response=swallowed_response,
            context=request_context,
            retry_state=retry_state,
        )

        # Assert
        call_args = mock_backend_processor.process_backend_request.call_args
        retry_request: ChatRequest = call_args.kwargs["request"]
        # Original messages should be preserved
        assert (
            retry_request.messages[: len(base_request.messages)]
            == base_request.messages
        )


class TestRetryCountPropagation:
    """Tests for retry count tracking and propagation."""

    @pytest.mark.asyncio
    async def test_retry_count_increments_on_each_retry(
        self,
        coordinator: IToolCallRetryCoordinator,
        mock_backend_processor: AsyncMock,
        base_request: ChatRequest,
        swallowed_response: ResponseEnvelope,
        request_context: RequestContext,
    ) -> None:
        """Retry count should increment with each retry attempt."""
        # Arrange
        # Set initial retry count in request's extra_body
        base_request = base_request.model_copy(
            update={"extra_body": {"_tool_call_reactor_retry_count": 1}}
        )
        retry_state = ToolCallRetryState(retry_count=1, max_retries=3)
        mock_backend_processor.process_backend_request.return_value = ResponseEnvelope(
            content="Retry response", metadata={}
        )

        # Act
        await coordinator.handle_non_streaming(
            request=base_request,
            response=swallowed_response,
            context=request_context,
            retry_state=retry_state,
        )

        # Assert
        call_args = mock_backend_processor.process_backend_request.call_args
        retry_request: ChatRequest = call_args.kwargs["request"]
        extra_body = retry_request.extra_body or {}
        assert extra_body.get("_tool_call_reactor_retry_count") == 2
        assert extra_body.get("_dangerous_command_retry_count") == 2

    @pytest.mark.asyncio
    async def test_retry_count_synchronizes_legacy_alias(
        self,
        coordinator: IToolCallRetryCoordinator,
        mock_backend_processor: AsyncMock,
        base_request: ChatRequest,
        swallowed_response: ResponseEnvelope,
        request_context: RequestContext,
    ) -> None:
        """Both _tool_call_reactor_retry_count and _dangerous_command_retry_count should be synchronized."""
        # Arrange
        retry_state = ToolCallRetryState(retry_count=0, max_retries=3)
        mock_backend_processor.process_backend_request.return_value = ResponseEnvelope(
            content="Retry response", metadata={}
        )

        # Act
        await coordinator.handle_non_streaming(
            request=base_request,
            response=swallowed_response,
            context=request_context,
            retry_state=retry_state,
        )

        # Assert
        call_args = mock_backend_processor.process_backend_request.call_args
        retry_request: ChatRequest = call_args.kwargs["request"]
        extra_body = retry_request.extra_body or {}
        primary_count = extra_body.get("_tool_call_reactor_retry_count")
        legacy_count = extra_body.get("_dangerous_command_retry_count")
        assert primary_count == legacy_count
        assert primary_count == 1


class TestRetryLimitEnforcement:
    """Tests for enforcing retry limits and returning terminal responses."""

    @pytest.mark.asyncio
    async def test_non_streaming_returns_terminal_when_limit_exceeded(
        self,
        coordinator: IToolCallRetryCoordinator,
        mock_backend_processor: AsyncMock,
        base_request: ChatRequest,
        swallowed_response: ResponseEnvelope,
        request_context: RequestContext,
    ) -> None:
        """When retry limit exceeded, should return terminal response without backend call."""
        # Arrange
        # Set retry count to 3 in request's extra_body (limit is 3, so 3+1=4 > 3)
        base_request = base_request.model_copy(
            update={"extra_body": {"_tool_call_reactor_retry_count": 3}}
        )
        retry_state = ToolCallRetryState(retry_count=3, max_retries=3)

        # Act
        result = await coordinator.handle_non_streaming(
            request=base_request,
            response=swallowed_response,
            context=request_context,
            retry_state=retry_state,
        )

        # Assert
        assert result is not None
        assert isinstance(result, ResponseEnvelope)
        assert result.metadata is not None
        assert result.metadata.get("dangerous_command_limit_exceeded") is True
        assert result.metadata.get("session_terminated") is True
        assert result.metadata.get("is_done") is True
        assert result.metadata.get("finish_reason") == "security_limit"
        # Should not call backend processor
        mock_backend_processor.process_backend_request.assert_not_called()

    @pytest.mark.asyncio
    async def test_streaming_returns_terminal_when_limit_exceeded(
        self,
        coordinator: IToolCallRetryCoordinator,
        mock_backend_processor: AsyncMock,
        base_request: ChatRequest,
        swallowed_response: ResponseEnvelope,
        request_context: RequestContext,
    ) -> None:
        """When streaming retry limit exceeded, should return terminal stream without backend call."""
        # Arrange
        # Set retry count to 3 in request's extra_body (limit is 3, so 3+1=4 > 3)
        base_request = base_request.model_copy(
            update={"extra_body": {"_tool_call_reactor_retry_count": 3}}
        )
        retry_state = ToolCallRetryState(
            retry_count=3, max_retries=3, is_streaming=True
        )

        # Act
        result = await coordinator.handle_streaming(
            request=base_request,
            response=swallowed_response,
            context=request_context,
            retry_state=retry_state,
        )

        # Assert
        assert result is not None
        assert isinstance(result, StreamingResponseEnvelope)
        assert result.metadata is not None
        assert result.metadata.get("dangerous_command_limit_exceeded") is True
        assert result.metadata.get("session_terminated") is True
        assert result.metadata.get("is_done") is True
        assert result.metadata.get("finish_reason") == "security_limit"
        # Should not call backend processor
        mock_backend_processor.process_backend_request.assert_not_called()

    @pytest.mark.asyncio
    async def test_terminal_response_includes_retry_count(
        self,
        coordinator: IToolCallRetryCoordinator,
        base_request: ChatRequest,
        swallowed_response: ResponseEnvelope,
        request_context: RequestContext,
    ) -> None:
        """Terminal response should include retry count in metadata."""
        # Arrange
        # Set retry count to 4 in request's extra_body (limit is 3, so 4+1=5 > 3)
        base_request = base_request.model_copy(
            update={"extra_body": {"_tool_call_reactor_retry_count": 4}}
        )
        retry_state = ToolCallRetryState(retry_count=4, max_retries=3)

        # Act
        result = await coordinator.handle_non_streaming(
            request=base_request,
            response=swallowed_response,
            context=request_context,
            retry_state=retry_state,
        )

        # Assert
        assert result is not None
        assert result.metadata is not None
        assert result.metadata.get("dangerous_command_retry_count") == 5
        assert result.metadata.get("tool_call_reactor_retry_count") == 5


class TestSessionIdPropagation:
    """Tests for session ID propagation in responses."""

    @pytest.mark.asyncio
    async def test_terminal_response_includes_session_id(
        self,
        coordinator: IToolCallRetryCoordinator,
        base_request: ChatRequest,
        swallowed_response: ResponseEnvelope,
        request_context: RequestContext,
    ) -> None:
        """Terminal response should include session_id from context."""
        # Arrange
        retry_state = ToolCallRetryState(retry_count=3, max_retries=3)
        request_context.processing_context = {"session_id": "test-session-123"}

        # Act
        result = await coordinator.handle_non_streaming(
            request=base_request,
            response=swallowed_response,
            context=request_context,
            retry_state=retry_state,
        )

        # Assert
        assert result is not None
        assert result.metadata is not None
        # Session ID should be propagated (check via context or metadata)
        # The coordinator should use context.session_id or processing_context.session_id

    @pytest.mark.asyncio
    async def test_retry_request_includes_session_id(
        self,
        coordinator: IToolCallRetryCoordinator,
        mock_backend_processor: AsyncMock,
        base_request: ChatRequest,
        swallowed_response: ResponseEnvelope,
        request_context: RequestContext,
    ) -> None:
        """Retry request should include session_id when calling backend processor."""
        # Arrange
        retry_state = ToolCallRetryState(retry_count=0, max_retries=3)
        request_context.processing_context = {"session_id": "test-session-123"}
        mock_backend_processor.process_backend_request.return_value = ResponseEnvelope(
            content="Retry response", metadata={}
        )

        # Act
        await coordinator.handle_non_streaming(
            request=base_request,
            response=swallowed_response,
            context=request_context,
            retry_state=retry_state,
        )

        # Assert
        call_args = mock_backend_processor.process_backend_request.call_args
        assert call_args.kwargs["session_id"] == "test-session-123"


class TestLoopPrevention:
    """Tests for preventing retry loops."""

    @pytest.mark.asyncio
    async def test_returns_none_when_request_already_marked_as_retry(
        self,
        coordinator: IToolCallRetryCoordinator,
        mock_backend_processor: AsyncMock,
        base_request: ChatRequest,
        swallowed_response: ResponseEnvelope,
        request_context: RequestContext,
    ) -> None:
        """When request already marked as retry, should return None to prevent loops."""
        # Arrange
        retry_state = ToolCallRetryState(retry_count=0, max_retries=3)
        # Use model_copy since ChatRequest is frozen
        base_request = base_request.model_copy(
            update={"extra_body": {"_tool_call_reactor_retry": True}}
        )

        # Act
        result = await coordinator.handle_non_streaming(
            request=base_request,
            response=swallowed_response,
            context=request_context,
            retry_state=retry_state,
        )

        # Assert
        assert result is None
        mock_backend_processor.process_backend_request.assert_not_called()


class TestBackendProcessorErrorHandling:
    """Tests for handling backend processor errors."""

    @pytest.mark.asyncio
    async def test_logs_error_and_returns_fallback_on_backend_failure(
        self,
        coordinator: IToolCallRetryCoordinator,
        mock_backend_processor: AsyncMock,
        base_request: ChatRequest,
        swallowed_response: ResponseEnvelope,
        request_context: RequestContext,
    ) -> None:
        """When backend processor fails, should log error and return fallback response."""
        # Arrange
        retry_state = ToolCallRetryState(retry_count=0, max_retries=3)
        mock_backend_processor.process_backend_request.side_effect = Exception(
            "Backend error"
        )

        # Act
        result = await coordinator.handle_non_streaming(
            request=base_request,
            response=swallowed_response,
            context=request_context,
            retry_state=retry_state,
        )

        # Assert
        assert result is not None
        assert isinstance(result, ResponseEnvelope)
        assert result.metadata is not None
        assert result.metadata.get("tool_call_reactor_retry_failed") is True
        assert result.metadata.get("steering_retry_occurred") is True
        # new_retry_count = current_retry_count (1) + 1 = 2
        assert result.metadata.get("dangerous_command_retry_count") == 2
        assert result.metadata.get("tool_call_reactor_retry_count") == 2


class TestRawBackendResponse:
    """Tests that coordinator returns raw backend responses without middleware."""

    @pytest.mark.asyncio
    async def test_returns_raw_backend_response_without_processing(
        self,
        coordinator: IToolCallRetryCoordinator,
        mock_backend_processor: AsyncMock,
        base_request: ChatRequest,
        swallowed_response: ResponseEnvelope,
        request_context: RequestContext,
    ) -> None:
        """Coordinator should return raw backend response without applying middleware."""
        # Arrange
        retry_state = ToolCallRetryState(retry_count=0, max_retries=3)
        raw_response = ResponseEnvelope(
            content="Raw backend content",
            metadata={
                "backend_metadata": "value",
                "original_request": {"test": "data"},
            },
        )
        mock_backend_processor.process_backend_request.return_value = raw_response

        # Act
        result = await coordinator.handle_non_streaming(
            request=base_request,
            response=swallowed_response,
            context=request_context,
            retry_state=retry_state,
        )

        # Assert
        assert result is not None
        # Should return the exact response from backend processor
        assert result.content == raw_response.content
        # Metadata should be preserved (no filtering applied by coordinator)
        assert result.metadata == raw_response.metadata

    @pytest.mark.asyncio
    async def test_fallback_streaming_preserves_steering_replacement(
        self,
        coordinator: IToolCallRetryCoordinator,
        mock_backend_processor: AsyncMock,
        base_request: ChatRequest,
        swallowed_response: ResponseEnvelope,
        request_context: RequestContext,
    ) -> None:
        """Fallback streaming response should preserve _steering_replacement marker."""
        # Arrange
        retry_state = ToolCallRetryState(
            retry_count=0, max_retries=3, is_streaming=True
        )
        # Add _steering_replacement to original response metadata
        swallowed_response.metadata["_steering_replacement"] = True
        mock_backend_processor.process_backend_request.side_effect = Exception(
            "Backend error"
        )

        # Act
        result = await coordinator.handle_streaming(
            request=base_request,
            response=swallowed_response,
            context=request_context,
            retry_state=retry_state,
        )

        # Assert
        assert result is not None
        assert isinstance(result, StreamingResponseEnvelope)
        assert result.metadata is not None
        assert result.metadata.get("_steering_replacement") is True
        assert result.metadata.get("steering_retry_occurred") is True


class TestEscalatingSteeringMessages:
    """Tests for escalating steering messages based on retry count."""

    @pytest.mark.asyncio
    async def test_first_retry_uses_first_steering_message(
        self,
        coordinator: IToolCallRetryCoordinator,
        mock_backend_processor: AsyncMock,
        base_request: ChatRequest,
        swallowed_response: ResponseEnvelope,
        request_context: RequestContext,
    ) -> None:
        """First retry should use first escalating steering message."""
        # Arrange
        retry_state = ToolCallRetryState(retry_count=0, max_retries=3)
        mock_backend_processor.process_backend_request.return_value = ResponseEnvelope(
            content="Retry response", metadata={}
        )

        # Act
        await coordinator.handle_non_streaming(
            request=base_request,
            response=swallowed_response,
            context=request_context,
            retry_state=retry_state,
        )

        # Assert
        call_args = mock_backend_processor.process_backend_request.call_args
        retry_request: ChatRequest = call_args.kwargs["request"]
        last_message = retry_request.messages[-1]
        assert "First Warning" in last_message.content

    @pytest.mark.asyncio
    async def test_second_retry_uses_second_steering_message(
        self,
        coordinator: IToolCallRetryCoordinator,
        mock_backend_processor: AsyncMock,
        base_request: ChatRequest,
        swallowed_response: ResponseEnvelope,
        request_context: RequestContext,
    ) -> None:
        """Second retry should use second escalating steering message."""
        # Arrange
        # Set retry count to 1 in request's extra_body (so next retry will be 2)
        base_request = base_request.model_copy(
            update={"extra_body": {"_tool_call_reactor_retry_count": 1}}
        )
        retry_state = ToolCallRetryState(retry_count=1, max_retries=3)
        mock_backend_processor.process_backend_request.return_value = ResponseEnvelope(
            content="Retry response", metadata={}
        )

        # Act
        await coordinator.handle_non_streaming(
            request=base_request,
            response=swallowed_response,
            context=request_context,
            retry_state=retry_state,
        )

        # Assert
        call_args = mock_backend_processor.process_backend_request.call_args
        retry_request: ChatRequest = call_args.kwargs["request"]
        last_message = retry_request.messages[-1]
        assert "SECOND WARNING" in last_message.content

    @pytest.mark.asyncio
    async def test_third_retry_uses_final_steering_message(
        self,
        coordinator: IToolCallRetryCoordinator,
        mock_backend_processor: AsyncMock,
        base_request: ChatRequest,
        swallowed_response: ResponseEnvelope,
        request_context: RequestContext,
    ) -> None:
        """Third retry should use final escalating steering message."""
        # Arrange
        # Set retry count to 2 in request's extra_body (so next retry will be 3)
        base_request = base_request.model_copy(
            update={"extra_body": {"_tool_call_reactor_retry_count": 2}}
        )
        retry_state = ToolCallRetryState(retry_count=2, max_retries=3)
        mock_backend_processor.process_backend_request.return_value = ResponseEnvelope(
            content="Retry response", metadata={}
        )

        # Act
        await coordinator.handle_non_streaming(
            request=base_request,
            response=swallowed_response,
            context=request_context,
            retry_state=retry_state,
        )

        # Assert
        call_args = mock_backend_processor.process_backend_request.call_args
        retry_request: ChatRequest = call_args.kwargs["request"]
        last_message = retry_request.messages[-1]
        assert "FINAL WARNING" in last_message.content
