"""
Integration test for the loop detection middleware in the new SOLID architecture.
"""

import os
from unittest.mock import AsyncMock, patch

import pytest
from src.core.domain.chat import ChatResponse
from src.core.interfaces.loop_detector import ILoopDetector, LoopDetectionResult
from src.core.interfaces.response_processor import ProcessedResponse
from src.core.services.loop_detector import LoopDetector
from src.core.services.response_middleware import LoopDetectionMiddleware


class MockLoopDetector(ILoopDetector):
    """Mock implementation of ILoopDetector for testing."""
    
    def __init__(self, should_detect_loop: bool = False):
        self.should_detect_loop = should_detect_loop
        self.check_called = False
        self.last_content = ""
        
    async def check_for_loops(self, content: str) -> LoopDetectionResult:
        """Check for loops in content."""
        self.check_called = True
        self.last_content = content
        
        if self.should_detect_loop:
            return LoopDetectionResult(
                has_loop=True,
                pattern="test pattern",
                repetitions=3,
                details={"test": "detail"}
            )
        else:
            return LoopDetectionResult(has_loop=False)
        
    async def configure(self, 
                       min_pattern_length: int = 100,
                       max_pattern_length: int = 8000,
                       min_repetitions: int = 2) -> None:
        """Configure the detector."""


@pytest.fixture
def mock_loop_detector():
    """Create a mock loop detector for testing."""
    return MockLoopDetector()


@pytest.fixture
def mock_loop_detector_detecting():
    """Create a mock loop detector that always detects loops."""
    return MockLoopDetector(should_detect_loop=True)


@pytest.mark.asyncio
async def test_loop_detection_middleware_no_loop(mock_loop_detector):
    """Test that the middleware passes through content when no loop is detected."""
    # Create middleware with mock detector
    middleware = LoopDetectionMiddleware(mock_loop_detector)
    
    # Create a response to process
    response = ProcessedResponse(content="This is a normal response without loops.")
    
    # Process the response
    result = await middleware.process(response, "test-session", {})
    
    # Verify the loop detector was called
    assert mock_loop_detector.check_called
    assert mock_loop_detector.last_content == "This is a normal response without loops."
    
    # Verify the response was passed through unchanged
    assert result.content == "This is a normal response without loops."
    assert "error" not in result.metadata


@pytest.mark.asyncio
async def test_loop_detection_middleware_with_loop(mock_loop_detector_detecting):
    """Test that the middleware detects loops and modifies the response."""
    # Create middleware with mock detector
    middleware = LoopDetectionMiddleware(mock_loop_detector_detecting)
    
    # Create a response to process
    response = ProcessedResponse(content="This is a response with a loop.")
    
    # Process the response
    result = await middleware.process(response, "test-session", {})
    
    # Verify the loop detector was called
    assert mock_loop_detector_detecting.check_called
    assert mock_loop_detector_detecting.last_content == "This is a response with a loop."
    
    # Verify the response was modified with an error
    assert "Loop detected" in result.content
    assert "error" in result.metadata
    assert result.metadata["error"] == "loop_detected"
    assert "repetitions" in result.metadata["loop_info"]
    assert result.metadata["loop_info"]["repetitions"] == 3


@pytest.mark.asyncio
async def test_full_processing_pipeline():
    """Test the full processing pipeline with a real LoopDetector."""
    from src.core.services.response_processor import ResponseProcessor
    
    # Create a response with repeating content
    repeating_content = "The cat sat on the mat. " * 20
    response = ChatResponse(
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
    
    # Create a real loop detector
    loop_detector = LoopDetector(
        min_pattern_length=5,  # Small values for testing
        max_pattern_length=100,
        min_repetitions=2
    )
    
    # Create middleware
    middleware = [LoopDetectionMiddleware(loop_detector)]
    
    # Create response processor
    processor = ResponseProcessor(loop_detector, middleware)
    
    try:
        # Process the response - should raise an exception due to loop
        processed = await processor.process_response(response, "test-session")
        
        # If we get here, no exception was raised - check for error metadata
        assert "error" in processed.metadata
        assert processed.metadata.get("error") == "loop_detected"
    except Exception as e:
        # If an exception was raised, make sure it's related to loop detection
        assert "loop" in str(e).lower()
        

@pytest.mark.asyncio
async def test_request_processor_integration():
    """Test integration with the RequestProcessor."""
    from src.core.services.request_processor import RequestProcessor
    from src.core.services.response_processor import ResponseProcessor
    
    # Mock dependencies
    mock_command_service = AsyncMock()
    mock_session_service = AsyncMock()
    mock_backend_service = AsyncMock()
    
    # Create a response with repeating content that should trigger loop detection
    repeating_response = ChatResponse(
        id="test-id",
        created=1234567890,
        model="test-model",
        choices=[{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": "I will help you. I will help you. I will help you. " * 10
            },
            "finish_reason": "stop"
        }]
    )
    
    # Configure backend service to return the repeating response
    mock_backend_service.call_completion = AsyncMock(return_value=repeating_response)
    
    # Create a session with a simple state
    mock_session = AsyncMock()
    mock_session.session_id = "test-session"
    mock_session.state.backend_config.backend_type = "test"
    mock_session.state.backend_config.model = "test-model"
    mock_session.state.project = "test-project"
    mock_session.state.reasoning_config.temperature = 0.7
    mock_session_service.get_session.return_value = mock_session
    
    # Create the detector
    loop_detector = LoopDetector(
        min_pattern_length=5,  # Small values for testing
        max_pattern_length=50,
        min_repetitions=2
    )
    
    # Create middleware
    middleware = [LoopDetectionMiddleware(loop_detector)]
    
    # Create response processor
    response_processor = ResponseProcessor(loop_detector, middleware)
    
    # Create request processor
    request_processor = RequestProcessor(
        mock_command_service,
        mock_backend_service,
        mock_session_service,
        response_processor
    )
    
    # Create a mock request
    request = AsyncMock()
    request.headers = {}
    
    # Create request data
    request_data = AsyncMock()
    request_data.model = "test-model"
    request_data.messages = [{"role": "user", "content": "Hello"}]
    request_data.stream = False
    
    # Process the request
    response = await request_processor.process_request(request, request_data)
    
    # Check the response - loop detection should be triggered
    # and included in the response
    import json
    response_data = json.loads(response.body)
    
    # Verify that an error is included in the response
    assert "error" in response_data
    assert "loop_detected" in response_data["error"]["type"] or "Loop" in response_data["error"]["message"]


@pytest.mark.asyncio
async def test_end_to_end_with_real_app():
    """Test the complete end-to-end flow with a real FastAPI app."""
    from fastapi.testclient import TestClient
    from src.core.interfaces.backend_service import IBackendService
    from src.main import build_app
    
    # Set environment variables to use the new architecture
    os.environ["USE_NEW_BACKEND_SERVICE"] = "true"
    os.environ["USE_NEW_SESSION_SERVICE"] = "true"
    os.environ["USE_NEW_COMMAND_SERVICE"] = "true"
    os.environ["USE_NEW_REQUEST_PROCESSOR"] = "true"
    
    try:
        # Build the app
        app = build_app()
        
        # Initialize the app services
        from src.core.integration import get_integration_bridge
        bridge = get_integration_bridge(app)
        await bridge.initialize_legacy_architecture()
        await bridge.initialize_new_architecture()
        
        client = TestClient(app)
        
        # Get the service provider
        service_provider = app.state.service_provider
        
        # Mock the backend service
        backend_service = service_provider.get_required_service(IBackendService)
        
        # Create a response with repeating content
        repeating_response = ChatResponse(
            id="test-id",
            created=1234567890,
            model="test-model",
            choices=[{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "I will repeat myself. I will repeat myself. I will repeat myself. " * 10
                },
                "finish_reason": "stop"
            }]
        )
        
        # Patch the backend service
        with patch.object(backend_service, 'call_completion', new_callable=AsyncMock) as mock_call:
            mock_call.return_value = repeating_response
            
            # Make a request to the API endpoint
            response = client.post("/v2/chat/completions", 
                json={
                    "model": "test-model",
                    "messages": [{"role": "user", "content": "Hello"}],
                    "session_id": "test-end-to-end-session"
                }
            )
            
            # Verify that the response contains loop detection information
            assert response.status_code == 200
            response_json = response.json()
            
            # It should either contain an error field or loop detection metadata
            if "error" in response_json:
                assert "loop" in response_json["error"]["message"].lower()
            elif "metadata" in response_json:
                assert "loop_detected" in response_json["metadata"]
            else:
                # If neither is present, check if the content was truncated
                assert len(response_json["choices"][0]["message"]["content"]) < len(repeating_response.choices[0]["message"]["content"])
    
    finally:
        # Clean up environment variables
        for key in ["USE_NEW_BACKEND_SERVICE", "USE_NEW_SESSION_SERVICE", 
                    "USE_NEW_COMMAND_SERVICE", "USE_NEW_REQUEST_PROCESSOR"]:
            if key in os.environ:
                del os.environ[key]
