"""Shared pytest fixtures for backend streaming response handler tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.domain.backend_request_manager.context_models import (
    ResponseProcessingContext,
)
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.request_context import ProcessingContext, RequestContext
from src.core.interfaces.backend_processor_interface import IBackendProcessor
from src.core.interfaces.backend_request_manager_components import (
    ILoopDetectorFactory,
    IQualityVerifierStreamVerifier,
    IStreamingBackendResponseHandler,
    IToolCallRetryCoordinator,
)
from src.core.interfaces.response_processor_interface import IResponseProcessor


@pytest.fixture
def mock_response_processor() -> IResponseProcessor:
    """Create a mock response processor."""
    mock = AsyncMock(spec=IResponseProcessor)
    return mock


@pytest.fixture
def mock_loop_detector_factory() -> ILoopDetectorFactory:
    """Create a mock loop detector factory."""
    mock = MagicMock(spec=ILoopDetectorFactory)
    return mock


@pytest.fixture
def mock_quality_verifier_stream_verifier() -> IQualityVerifierStreamVerifier:
    """Create a mock Angel stream verifier."""
    mock = AsyncMock(spec=IQualityVerifierStreamVerifier)

    async def passthrough(request, stream, context):
        async for chunk in stream:
            yield chunk

    mock.verify_or_passthrough.side_effect = passthrough
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
    mock_loop_detector_factory: ILoopDetectorFactory,
    mock_quality_verifier_stream_verifier: IQualityVerifierStreamVerifier,
    mock_tool_call_retry_coordinator: IToolCallRetryCoordinator,
    mock_backend_processor: IBackendProcessor,
) -> IStreamingBackendResponseHandler:
    """Create a BackendStreamingResponseHandler instance."""
    from src.core.services.backend_request_manager.streaming_response_handler import (
        BackendStreamingResponseHandler,
    )

    return BackendStreamingResponseHandler(
        response_processor=mock_response_processor,
        loop_detector_factory=mock_loop_detector_factory,
        quality_verifier_stream_verifier=mock_quality_verifier_stream_verifier,
        tool_call_retry_coordinator=mock_tool_call_retry_coordinator,
        backend_processor=mock_backend_processor,
    )


@pytest.fixture
def base_request() -> ChatRequest:
    """Create a base chat request for testing."""
    return ChatRequest(
        model="gpt-4",
        messages=[ChatMessage(role="user", content="Hello")],
        stream=True,
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
        client_os="Windows",
        original_request=base_request,
        structured_output=None,
    )
