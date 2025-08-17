"""
Integration test for the loop detection middleware in the new SOLID architecture.
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch  # Added MagicMock

import pytest
import src.core.config.config_loader  # Added import
from src.core.common.exceptions import LoopDetectionError
from src.core.domain.chat import ChatResponse
from src.core.domain.session import Session, SessionState  # Added import
from src.core.interfaces.loop_detector import ILoopDetector, LoopDetectionResult
from src.core.interfaces.response_processor import ProcessedResponse
from src.core.interfaces.session_service import ISessionService  # Added import
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
                details={"test": "detail"},
            )
        else:
            return LoopDetectionResult(has_loop=False)

    async def configure(
        self,
        min_pattern_length: int = 100,
        max_pattern_length: int = 8000,
        min_repetitions: int = 2,
    ) -> None:
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
    response = ProcessedResponse(
        content="This is a normal response without loops. This is a normal response without loops. This is a normal response without loops. This is a normal response without loops. This is a normal response without loops. This is a normal response without loops. This is a normal response without loops. This is a normal response without loops. This is a normal response without loops. This is a normal response without loops."
    )

    # Process the response
    result = await middleware.process(response, "test-session", {})

    # Verify the loop detector was called
    assert mock_loop_detector.check_called
    assert (
        mock_loop_detector.last_content
        == "This is a normal response without loops. This is a normal response without loops. This is a normal response without loops. This is a normal response without loops. This is a normal response without loops. This is a normal response without loops. This is a normal response without loops. This is a normal response without loops. This is a normal response without loops. This is a normal response without loops."
    )

    # Verify the response was passed through unchanged
    assert (
        result.content
        == "This is a normal response without loops. This is a normal response without loops. This is a normal response without loops. This is a normal response without loops. This is a normal response without loops. This is a normal response without loops. This is a normal response without loops. This is a normal response without loops. This is a normal response without loops. This is a normal response without loops."
    )
    assert "error" not in result.metadata


@pytest.mark.asyncio
async def test_loop_detection_middleware_with_loop(mock_loop_detector_detecting):
    """Test that the middleware detects loops and modifies the response."""
    # Create middleware with mock detector
    middleware = LoopDetectionMiddleware(mock_loop_detector_detecting)

    # Create a response to process
    response = ProcessedResponse(
        content="This is a response with a loop. This is a response with a loop. This is a response with a loop. This is a response with a loop. This is a response with a loop. This is a response with a loop. This is a response with a loop. This is a response with a loop. This is a response with a loop. This is a response with a loop."
    )

    # Process the response
    with pytest.raises(LoopDetectionError) as exc_info:
        await middleware.process(response, "test-session", {})

    # Verify the loop detector was called
    assert mock_loop_detector_detecting.check_called
    assert (
        mock_loop_detector_detecting.last_content
        == "This is a response with a loop. This is a response with a loop. This is a response with a loop. This is a response with a loop. This is a response with a loop. This is a response with a loop. This is a response with a loop. This is a response with a loop. This is a response with a loop. This is a response with a loop."
    )

    # Verify the exception details
    assert "Loop detected" in str(exc_info.value)
    assert exc_info.value.details["repetitions"] == 3


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
        choices=[
            {
                "index": 0,
                "message": {"role": "assistant", "content": repeating_content},
                "finish_reason": "stop",
            }
        ],
    )

    # Create a real loop detector
    loop_detector = LoopDetector(
        min_pattern_length=5,  # Small values for testing
        max_pattern_length=100,
        min_repetitions=2,
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

    # Mock session service to return a valid session

    # Create a response with repeating content that should trigger loop detection
    repeating_response = ChatResponse(
        id="test-id",
        created=1234567890,
        model="test-model",
        choices=[
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "I will help you. I will help you. I will help you. "
                    * 10,
                },
                "finish_reason": "stop",
            }
        ],
    )

    # Configure backend service to return the repeating response
    mock_backend_service.call_completion = AsyncMock(return_value=repeating_response)

    # Create a session with a simple state
    class MockBackendConfig:
        backend_type = "test"
        model = "test-model"

    class MockReasoningConfig:
        temperature = 0.7

    class MockSessionState:
        backend_config = MockBackendConfig()
        project = "test-project"
        reasoning_config = MockReasoningConfig()

    mock_session = MagicMock()  # Changed to MagicMock
    mock_session.session_id = "test-session"
    mock_session.state = MockSessionState()
    mock_session_service.get_session.return_value = mock_session

    # Create the detector
    loop_detector = LoopDetector(
        min_pattern_length=5,  # Small values for testing
        max_pattern_length=50,
        min_repetitions=2,
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
        response_processor,
    )

    # Create a mock request
    request = AsyncMock()
    request.headers = {}

    # Create request data
    from src.core.app.controllers.chat_controller import ChatCompletionRequest

    request_data = ChatCompletionRequest(
        model="test-model",
        messages=[{"role": "user", "content": "Hello"}],
        stream=False,
        user=None,
        tool_choice=None,
    )

    # Process the request
    with pytest.raises(LoopDetectionError) as exc_info:
        await request_processor.process_request(request, request_data)

    # Verify the exception details
    assert "Response loop detected" in str(exc_info.value)
    assert exc_info.value.details["repetitions"] == 30


@pytest.mark.asyncio
async def test_end_to_end_with_real_app():
    """Test the complete end-to-end flow with a real FastAPI app."""
    from fastapi.testclient import TestClient
    from src.core.app.application_factory import build_app
    from src.core.interfaces.backend_service import IBackendService

    # Store original _load_config before patching
    original_load_config = src.core.config.config_loader._load_config

    # Set environment variables to use the new architecture
    os.environ["USE_NEW_BACKEND_SERVICE"] = "true"
    os.environ["USE_NEW_SESSION_SERVICE"] = "true"
    os.environ["USE_NEW_COMMAND_SERVICE"] = "true"
    os.environ["USE_NEW_REQUEST_PROCESSOR"] = "true"

    try:
        # Set proxy API key for the test
        os.environ["LLM_INTERACTIVE_PROXY_API_KEY"] = "test-proxy-key"

        # Patch _load_config to include the API key in the config
        with patch("src.core.app.application_factory._load_config") as mock_load_config:
            # Call the original _load_config to get the base config
            base_config = original_load_config()

            # Add the api_keys to the base config
            base_config["api_keys"] = ["test-proxy-key"]

            # Set the mock's return value to the modified config
            mock_load_config.return_value = base_config

            # Build the app
            app = build_app()

        # Initialize the app services
        import httpx  # Added import
        from src.core.integration import get_integration_bridge

        bridge = get_integration_bridge(app)
        app.state.httpx_client = AsyncMock(
            spec=httpx.AsyncClient
        )  # Added mock httpx_client
        await bridge.initialize_new_architecture()

        with TestClient(app) as client:  # Use TestClient in a with statement
            # Get the service provider
            service_provider = app.state.service_provider

            # Get the real session service and add a mock session
            session_service = service_provider.get_required_service(ISessionService)
            mock_session = Session(
                session_id="test-end-to-end-session",
                state=SessionState(project="test-project"),
            )
            await session_service.update_session(
                mock_session
            )  # Add the session to the repository

            # Mock the backend service
            backend_service = service_provider.get_required_service(IBackendService)

            # Create a response with repeating content
            repeating_response = ChatResponse(
                id="test-id",
                created=1234567890,
                model="test-model",
                choices=[
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "I will repeat myself. I will repeat myself. I will repeat myself. "
                            * 10,
                        },
                        "finish_reason": "stop",
                    }
                ],
            )

            # Patch the backend service
            with patch.object(
                backend_service, "call_completion", new_callable=AsyncMock
            ) as mock_call:
                mock_call.return_value = repeating_response

                # Make a request to the API endpoint
                response = client.post(
                    "/v2/chat/completions",
                    json={
                        "model": "test-model",
                        "messages": [{"role": "user", "content": "Hello"}],
                        "session_id": "test-end-to-end-session",
                    },
                    headers={"Authorization": "Bearer test-proxy-key"},
                )

                # Verify that the response contains loop detection information
                assert response.status_code == 400
                response_json = response.json()
                assert "error" in response_json
                assert response_json["error"]["type"] == "LoopDetectionError"

    finally:
        # Clean up environment variables
        if "LLM_INTERACTIVE_PROXY_API_KEY" in os.environ:
            del os.environ["LLM_INTERACTIVE_PROXY_API_KEY"]
        for key in [
            "USE_NEW_BACKEND_SERVICE",
            "USE_NEW_SESSION_SERVICE",
            "USE_NEW_COMMAND_SERVICE",
            "USE_NEW_REQUEST_PROCESSOR",
        ]:
            if key in os.environ:
                del os.environ[key]
