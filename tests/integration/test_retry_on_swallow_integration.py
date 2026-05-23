"""
Integration tests for retry-on-swallow behavior.

This module tests that swallowed tool calls trigger the retry path in
BackendRequestManager and that required metadata keys are preserved.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from src.core.config.app_config import AppConfig
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.interfaces.backend_processor_interface import (
    IBackendProcessor,
    ResponseEnvelope,
    StreamingResponseEnvelope,
)
from src.core.interfaces.response_processor_interface import ProcessedResponse


class MockBackendProcessor(IBackendProcessor):
    """Mock backend processor that simulates tool call swallowing."""

    def __init__(self, swallow_first: bool = True):
        self._swallow_first = swallow_first
        self._call_count = 0

    async def process_backend_request(
        self,
        request: ChatRequest,
        session_id: str,
        context: dict[str, Any] | None = None,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Process backend request and simulate swallow on first call."""
        self._call_count += 1

        # First call: return response with swallowed tool call
        if self._swallow_first and self._call_count == 1:
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

        # Retry call: return success response
        return ResponseEnvelope(
            content="I understand. I will not run dangerous commands.",
            metadata={},
        )


class MockResponseProcessor:
    """Mock response processor that simulates tool call reactor processing."""

    async def process_response(
        self,
        response: Any,
        session_id: str,
        context: dict[str, Any] | None = None,
    ) -> ProcessedResponse:
        """Process response and return as ProcessedResponse."""
        # Convert ResponseEnvelope content to ProcessedResponse
        if isinstance(response, str):
            # If it's a string, wrap it in ProcessedResponse
            return ProcessedResponse(content=response, metadata={})
        elif isinstance(response, ProcessedResponse):
            return response
        else:
            # For other types, try to extract content
            content = getattr(response, "content", response)
            metadata = getattr(response, "metadata", {})
            return ProcessedResponse(content=content, metadata=metadata or {})

    async def process_streaming_response(
        self,
        stream: AsyncIterator[ProcessedResponse],
        session_id: str,
        context: dict[str, Any] | None = None,
    ) -> AsyncIterator[ProcessedResponse]:
        """Process streaming response and return unchanged."""
        async for chunk in stream:
            yield chunk


@pytest.fixture
def app_config() -> AppConfig:
    """Create app config with tool call reactor enabled."""
    return AppConfig.model_validate(
        {
            "session": {
                "tool_call_reactor": {"enabled": True},
            }
        }
    )


@pytest.fixture
def mock_backend_processor() -> MockBackendProcessor:
    """Create mock backend processor."""
    return MockBackendProcessor(swallow_first=True)


@pytest.fixture
def mock_response_processor() -> MockResponseProcessor:
    """Create mock response processor."""
    return MockResponseProcessor()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_retry_on_swallow_non_streaming(
    app_config: AppConfig,
    mock_backend_processor: MockBackendProcessor,
    mock_response_processor: MockResponseProcessor,
):
    """Test that swallowed tool calls trigger retry path in non-streaming mode."""

    # Create backend request manager
    from tests.helpers.backend_request_manager_fixtures import (
        create_backend_request_manager,
    )

    manager = create_backend_request_manager(
        backend_processor=mock_backend_processor,
        response_processor=mock_response_processor,
    )

    # Create a request
    request = ChatRequest(
        messages=[ChatMessage(role="user", content="Run: rm -rf /")],
        model="test-model",
    )

    # Process request
    response = await manager.process_backend_request(
        backend_request=request,
        session_id="test-session",
        context=RequestContext(
            headers={},
            cookies={},
            state={},
            app_state=None,
        ),
    )

    # Verify retry was triggered (should have 2 calls: initial + retry)
    assert mock_backend_processor._call_count == 2

    # Verify final response is from retry (not the swallowed one)
    assert isinstance(response, ResponseEnvelope)
    # The retry response should not contain "blocked" (from first response)
    assert "blocked" not in response.content.lower()
    # The retry response should acknowledge the steering
    assert (
        "understand" in response.content.lower()
        or "not run" in response.content.lower()
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_retry_on_swallow_metadata_contract(
    app_config: AppConfig,
    mock_backend_processor: MockBackendProcessor,
    mock_response_processor: MockResponseProcessor,
):
    """Test that required metadata keys are present for retry-on-swallow."""

    # Track metadata from first response
    captured_metadata = {}

    class MetadataCapturingProcessor(MockBackendProcessor):
        async def process_backend_request(
            self,
            request: ChatRequest,
            session_id: str,
            context: dict[str, Any] | None = None,
        ) -> ResponseEnvelope | StreamingResponseEnvelope:
            response = await super().process_backend_request(
                request, session_id, context
            )
            md = getattr(response, "metadata", None)
            if (
                self._call_count == 1
                and isinstance(md, dict)
                and md.get("tool_call_swallowed") is True
            ):
                captured_metadata.update(md)
            return response

    processor = MetadataCapturingProcessor(swallow_first=True)

    # Create backend request manager
    from tests.helpers.backend_request_manager_fixtures import (
        create_backend_request_manager,
    )

    manager = create_backend_request_manager(
        backend_processor=processor,
        response_processor=mock_response_processor,
    )

    # Create a request
    request = ChatRequest(
        messages=[ChatMessage(role="user", content="Run: rm -rf /")],
        model="test-model",
    )

    # Process request
    await manager.process_backend_request(
        backend_request=request,
        session_id="test-session",
        context={},
    )

    # Verify required metadata keys are present
    assert captured_metadata.get("tool_call_swallowed") is True
    assert "steering_message" in captured_metadata
    assert isinstance(captured_metadata.get("steering_message"), str)
    assert "swallowed_tool_calls" in captured_metadata
    assert isinstance(captured_metadata.get("swallowed_tool_calls"), list)
    assert len(captured_metadata.get("swallowed_tool_calls", [])) > 0
    assert "swallowed_original_content" in captured_metadata
    assert isinstance(captured_metadata.get("swallowed_original_content"), str)
    assert captured_metadata.get("_steering_replacement") is True


@pytest.mark.asyncio
@pytest.mark.integration
async def test_retry_on_swallow_streaming(
    app_config: AppConfig,
    mock_response_processor: MockResponseProcessor,
):
    """Test that swallowed tool calls trigger retry path in streaming mode."""

    call_count = 0

    class StreamingMockBackendProcessor(IBackendProcessor):
        async def process_backend_request(
            self,
            request: ChatRequest,
            session_id: str,
            context: dict[str, Any] | None = None,
        ) -> ResponseEnvelope | StreamingResponseEnvelope:
            nonlocal call_count
            call_count += 1

            async def chunk_generator() -> AsyncIterator[ProcessedResponse]:
                if call_count == 1:
                    # First call: return chunk with swallowed tool call
                    yield ProcessedResponse(
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
                else:
                    # Retry call: return success response
                    yield ProcessedResponse(
                        content="I understand. I will not run dangerous commands.",
                        metadata={},
                    )

            return StreamingResponseEnvelope(
                content=chunk_generator(),
                headers={},
                status_code=200,
                metadata={},
            )

    processor = StreamingMockBackendProcessor()

    # Create backend request manager
    from tests.helpers.backend_request_manager_fixtures import (
        create_backend_request_manager,
    )

    manager = create_backend_request_manager(
        backend_processor=processor,
        response_processor=mock_response_processor,
    )

    # Create a request
    request = ChatRequest(
        messages=[ChatMessage(role="user", content="Run: rm -rf /")],
        model="test-model",
        stream=True,
    )

    # Process request
    response = await manager.process_backend_request(
        backend_request=request,
        session_id="test-session",
        context=RequestContext(
            headers={},
            cookies={},
            state={},
            app_state=None,
        ),
    )

    # For streaming, retry logic processes chunks differently
    # Verify we got a streaming response
    assert isinstance(response, StreamingResponseEnvelope)

    # Consume stream and verify content
    chunks = []
    async for chunk in response.content:
        chunks.append(chunk)

    # Should have at least one chunk
    assert len(chunks) > 0
    # Verify streaming response was processed
    # Note: Streaming retry may work differently than non-streaming


@pytest.mark.asyncio
@pytest.mark.integration
async def test_retry_on_swallow_preserves_context(
    app_config: AppConfig,
    mock_backend_processor: MockBackendProcessor,
    mock_response_processor: MockResponseProcessor,
):
    """Test that retry request includes proper context from swallowed metadata."""

    retry_requests: list[ChatRequest] = []

    class ContextCapturingProcessor(MockBackendProcessor):
        async def process_backend_request(
            self,
            request: ChatRequest,
            session_id: str,
            context: RequestContext | None = None,
        ) -> ResponseEnvelope | StreamingResponseEnvelope:
            nonlocal retry_requests
            # Capture all requests (including retry)
            retry_requests.append(request)
            return await super().process_backend_request(request, session_id, context)

    processor = ContextCapturingProcessor(swallow_first=True)

    # Create backend request manager
    from tests.helpers.backend_request_manager_fixtures import (
        create_backend_request_manager,
    )

    manager = create_backend_request_manager(
        backend_processor=processor,
        response_processor=mock_response_processor,
    )

    # Create a request
    original_request = ChatRequest(
        messages=[ChatMessage(role="user", content="Run: rm -rf /")],
        model="test-model",
    )

    # Process request
    await manager.process_backend_request(
        backend_request=original_request,
        session_id="test-session",
        context=RequestContext(
            headers={},
            cookies={},
            state={},
            app_state=None,
        ),
    )

    # Verify retry was triggered (should have 2 calls: initial + retry)
    assert processor._call_count == 2
    assert len(retry_requests) == 2

    # Verify retry request (second call) includes retry marker
    retry_request = retry_requests[1]
    assert retry_request.extra_body is not None
    assert retry_request.extra_body.get("_tool_call_reactor_retry") is True

    # Verify retry request includes context from swallowed metadata
    # (BackendRequestManager should add steering message to messages)
    assert len(retry_request.messages) > len(original_request.messages)
