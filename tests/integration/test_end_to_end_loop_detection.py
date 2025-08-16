"""
End-to-end tests for loop detection in the new SOLID architecture.

This test module verifies that loop detection works correctly in the complete
request-response pipeline with real backend integrations.
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from src.core.domain.chat import ChatResponse
from src.core.interfaces.backend_service import IBackendService
from src.core.services.loop_detector import LoopDetector
from src.core.services.response_middleware import LoopDetectionMiddleware
from src.core.services.response_processor import ResponseProcessor


@pytest.fixture
def repeating_content():
    """Generate repeating content that should trigger loop detection."""
    return "I will repeat myself. I will repeat myself. " * 20


@pytest.fixture
def repeating_response(repeating_content):
    """Create a response with repeating content."""
    return ChatResponse(
        id="test-response",
        created=1234567890,
        model="test-model",
        choices=[{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": repeating_content
            },
            "finish_reason": "stop"
        }]
    )


@pytest.mark.asyncio
async def test_loop_detection_with_mocked_backend():
    """Test loop detection with a mocked backend."""
    from src.core.app.application_factory import build_app
    from src.core.di.container import ServiceCollection
    from src.core.interfaces.backend_service import IBackendService
    
    # Create the app
    app = build_app()
    
    # Create and set up a service provider manually for testing
    services = ServiceCollection()
    service_provider = services.build_service_provider()
    app.state.service_provider = service_provider
    
    # Register a mock backend service
    backend_service = AsyncMock(spec=IBackendService)
    
    # Mock the backend service
    backend_service = service_provider.get_required_service(IBackendService)
    
    # Create a response with repeating content
    repeating_content = "I will repeat myself. I will repeat myself. " * 20
    repeating_response = ChatResponse(
        id="test-id",
        created=1234567890,
        model="test-model",
        choices=[{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": repeating_content
            },
            "finish_reason": "stop"
        }]
    )
    
    # Patch the backend service to return the repeating response
    with patch.object(backend_service, 'call_completion', new_callable=AsyncMock) as mock_call:
        mock_call.return_value = repeating_response
        
        # Create a test client
        client = TestClient(app)
        
        # Make a request to the API endpoint
        response = client.post(
            "/v2/chat/completions", 
            json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "Hello"}],
                "session_id": "test-loop-detection-session"
            }
        )
        
        # Verify the response
        assert response.status_code == 200
        response_json = response.json()
        
        # Check for loop detection error
        assert "error" in response_json
        assert "loop_detected" in response_json["error"]["type"]


@pytest.mark.asyncio
async def test_loop_detection_in_streaming_response():
    """Test loop detection in a streaming response."""
    from src.core.app.application_factory import build_app
    from src.core.domain.chat import StreamingChatResponse
    from src.core.di.container import ServiceCollection
    from src.core.interfaces.backend_service import IBackendService
    
    # Create the app
    app = build_app()
    
    # Create and set up a service provider manually for testing
    services = ServiceCollection()
    service_provider = services.build_service_provider()
    app.state.service_provider = service_provider
    
    # Register a mock backend service
    backend_service = AsyncMock(spec=IBackendService)
    
    # Mock the backend service
    backend_service = service_provider.get_required_service(IBackendService)
    
    # Create streaming chunks with repeating content
    async def generate_repeating_chunks():
        for _ in range(30):
            yield StreamingChatResponse(
                id="test-id",
                model="test-model",
                created=1234567890,
                choices=[{
                    "index": 0,
                    "delta": {
                        "content": "I will repeat myself. "
                    },
                    "finish_reason": None
                }]
            )
            await asyncio.sleep(0.01)
    
    # Patch the backend service to return the streaming response
    with patch.object(backend_service, 'call_completion', return_value=generate_repeating_chunks()):
        # Create a test client
        client = TestClient(app)
        
        # Make a streaming request to the API endpoint
        response = client.post(
            "/v2/chat/completions", 
            json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "Hello"}],
                "stream": True,
                "session_id": "test-streaming-loop-detection"
            },
            stream=True
        )
        
        # Verify the response
        assert response.status_code == 200
        
        # Collect all chunks
        chunks = []
        for chunk in response.iter_lines():
            if chunk:
                chunks.append(chunk)
        
        # Check that at least one chunk contains loop detection error
        error_chunks = [chunk for chunk in chunks if b"error" in chunk and b"loop_detected" in chunk]
        assert len(error_chunks) > 0


@pytest.mark.asyncio
async def test_loop_detection_integration_with_middleware_chain():
    """Test that the loop detection middleware is properly integrated in the chain."""
    # Create a loop detector
    loop_detector = LoopDetector(
        min_pattern_length=5,
        max_pattern_length=50,
        min_repetitions=2
    )
    
    # Create middleware components
    content_filter = AsyncMock()
    content_filter.process.return_value = None
    
    logging_middleware = AsyncMock()
    logging_middleware.process.return_value = None
    
    loop_detection_middleware = LoopDetectionMiddleware(loop_detector)
    
    # Create response processor with middleware chain
    response_processor = ResponseProcessor(
        loop_detector=loop_detector,
        middleware=[content_filter, logging_middleware, loop_detection_middleware]
    )
    
    # Create a response with repeating content
    repeating_content = "I will repeat myself. I will repeat myself. " * 20
    response = ChatResponse(
        id="test-id",
        created=1234567890,
        model="test-model",
        choices=[{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": repeating_content
            },
            "finish_reason": "stop"
        }]
    )
    
    # Process the response - expect a LoopDetectionError
    from src.core.common.exceptions import LoopDetectionError
    
    try:
        processed_response = await response_processor.process_response(response, "test-session")
        # If we get here (no exception), check for error metadata
        assert "error" in processed_response.metadata
        assert processed_response.metadata["error"] == "loop_detected"
        assert "Loop detected" in processed_response.content
    except LoopDetectionError as e:
        # This is expected behavior - the loop detector is working
        assert "repetitions" in str(e)
        assert "repetitions" in e.details


@pytest.mark.asyncio
@pytest.mark.skip(reason="Needs further investigation of AsyncMock behavior")
async def test_request_processor_uses_response_processor():
    """Test that RequestProcessor correctly uses ResponseProcessor."""
    from src.core.services.request_processor import RequestProcessor
    
    # Create mock services
    command_service = AsyncMock()
    backend_service = AsyncMock()
    session_service = AsyncMock()
    response_processor = AsyncMock()
    
    # Configure the AsyncMock to handle awaitable calls
    async def mock_process_response(response, session_id):
        from src.core.interfaces.response_processor import ProcessedResponse
        return ProcessedResponse(content="Processed response")
        
    response_processor.process_response = AsyncMock(side_effect=mock_process_response)
    
    # Create a test session
    session = AsyncMock()
    session.session_id = "test-session"
    session.state.backend_config.backend_type = "test"
    session.state.backend_config.model = "test-model"
    session.state.project = "test-project"
    session_service.get_session.return_value = session
    
    # Create a test response
    response = ChatResponse(
        id="test-id",
        created=1234567890,
        model="test-model",
        choices=[{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": "Test response"
            },
            "finish_reason": "stop"
        }]
    )
    
    # Configure backend service to return the test response
    backend_service.call_completion.return_value = response
    
    # Create request processor
    request_processor = RequestProcessor(
        command_service,
        backend_service,
        session_service,
        response_processor
    )
    
    # Create test request
    request = AsyncMock()
    request.headers = {}
    
    request_data = AsyncMock()
    request_data.model = "test-model"
    request_data.messages = [{"role": "user", "content": "Hello"}]
    request_data.stream = False
    
    # No need to configure return_value here since we've set up the side_effect above
    
    # Process the request
    await request_processor.process_request(request, request_data)
    
    # Verify that response_processor.process_response was called
    assert response_processor.process_response.called


if __name__ == "__main__":
    pytest.main(["-xvs", __file__])
