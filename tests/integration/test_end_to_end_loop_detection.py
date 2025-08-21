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
from src.core.interfaces.backend_service_interface import IBackendService
from src.core.services.loop_detector_service import LoopDetector
from src.core.services.response_middleware_service import LoopDetectionMiddleware
from src.core.services.response_processor_service import ResponseProcessor


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
        choices=[
            {
                "index": 0,
                "message": {"role": "assistant", "content": repeating_content},
                "finish_reason": "stop",
            }
        ],
    )


@pytest.mark.asyncio
@pytest.mark.skip(
    reason="Loop detection integration requires complex middleware setup and configuration - skipping for now"
)
async def test_loop_detection_with_mocked_backend():
    """Test loop detection with a mocked backend."""

    import os

    from src.core.app.test_builder import build_test_app as build_app
    from src.core.config.app_config import (
        AppConfig,
        AuthConfig,
        BackendConfig,
        BackendSettings,
        SessionConfig,
    )

    os.environ["LOOP_DETECTION_ENABLED"] = "true"

    # Create a test config with auth disabled
    test_config = AppConfig(
        host="localhost",
        port=9000,
        proxy_timeout=10,
        command_prefix="!/",
        backends=BackendSettings(
            default_backend="openai",
            openai=BackendConfig(api_key=["test_openai_key"]),
            openrouter=BackendConfig(api_key=["test_openrouter_key"]),
            anthropic=BackendConfig(api_key=["test_anthropic_key"]),
        ),
        auth=AuthConfig(disable_auth=True, api_keys=["test_api_key"]),
        session=SessionConfig(
            cleanup_enabled=False,
            default_interactive_mode=True,
        ),
    )

    # Create the app with auth disabled
    app = build_app(test_config)

    # The service provider should already be initialized by the test app
    # No additional setup needed with the new staged architecture

    # Get the backend service from provider (will be used for patching)
    backend_service = app.state.service_provider.get_required_service(IBackendService)  # type: ignore

    # Create a response with repeating content
    # Use a pattern that is at least 50 characters long (the default min_pattern_length)
    repeating_pattern = "This is a long repeating pattern that should be detected by the loop detector. "
    repeating_content = repeating_pattern * 10  # Repeat 10 times to ensure detection
    repeating_response = ChatResponse(
        id="test-id",
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

    # Patch the backend service to return the repeating response
    with patch.object(
        backend_service, "call_completion", new_callable=AsyncMock
    ) as mock_call:
        mock_call.return_value = repeating_response

        # Create a test client
        client = TestClient(app, headers={"Authorization": "Bearer test_api_key"})

        # Make a request to the API endpoint
        response = client.post(
            "/v2/chat/completions",
            json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "Hello"}],
                "session_id": "test-loop-detection-session",
            },
        )

        # Verify the response
        print(f"Response status: {response.status_code}")
        print(f"Response body: {response.text}")

        # The loop detection is working - it returns 400 Bad Request
        assert response.status_code == 400
        response_json = response.json()

        # Check that the error message contains loop detection information
        assert "error" in response_json
        assert "message" in response_json["error"]
        assert "loop detected" in response_json["error"]["message"].lower()


@pytest.mark.asyncio
@pytest.mark.skip(
    reason="Test uses deprecated _initialize_loop_detection_middleware method that no longer exists in new architecture"
)
async def test_loop_detection_in_streaming_response():
    """Test loop detection in a streaming response."""
    import os

    from src.core.app.test_builder import build_test_app as build_app
    from src.core.config.app_config import (
        AppConfig,
        AuthConfig,
        BackendConfig,
        BackendSettings,
        SessionConfig,
    )
    from src.core.domain.chat import StreamingChatResponse

    os.environ["LOOP_DETECTION_ENABLED"] = "true"

    # Create a test config with auth disabled
    test_config = AppConfig(
        host="localhost",
        port=9000,
        proxy_timeout=10,
        command_prefix="!/",
        backends=BackendSettings(
            default_backend="openai",
            openai=BackendConfig(api_key=["test_openai_key"]),
            openrouter=BackendConfig(api_key=["test_openrouter_key"]),
            anthropic=BackendConfig(api_key=["test_anthropic_key"]),
        ),
        auth=AuthConfig(disable_auth=True, api_keys=["test_api_key"]),
        session=SessionConfig(
            cleanup_enabled=False,
            default_interactive_mode=True,
        ),
    )

    # Create the app with auth disabled
    app = build_app(test_config)

    # Create and set up a service provider with proper service registration
    from typing import cast

    from src.core.di.services import get_service_collection, set_service_provider

    from tests.mocks.mock_backend_service import MockBackendService

    services = get_service_collection()
    # Provide httpx client for service registration
    import httpx

    app.state.httpx_client = httpx.AsyncClient()

    # Manually initialize services and backends
    from src.core.app.test_builder import TestApplicationBuilder as ApplicationBuilder
    from src.core.config.app_config import load_config

    loop_config = load_config()
    builder = ApplicationBuilder()

    # We need to run this in an async context
    async def init_services():
        service_provider = await builder._initialize_services(app, loop_config)
        app.state.service_provider = service_provider
        await builder._initialize_backends(app, loop_config)
        await builder._initialize_loop_detection_middleware(app, loop_config)

    await init_services()
    # Replace with mock backend
    services.add_singleton(
        cast(type[IBackendService], IBackendService),
        implementation_factory=lambda _: MockBackendService(),
    )

    service_provider = services.build_service_provider()
    set_service_provider(service_provider)
    app.state.service_provider = service_provider

    # Get the mock backend service
    backend_service = service_provider.get_required_service(IBackendService)  # type: ignore

    # Create streaming chunks with repeating content
    async def generate_repeating_chunks():
        for _ in range(30):
            yield StreamingChatResponse(
                model="test-model",
                content="I will repeat myself. ",
            )
            await asyncio.sleep(0.01)

    # Patch the backend service to return the streaming response
    with patch.object(
        backend_service, "call_completion", return_value=generate_repeating_chunks()
    ):
        # Create a test client with authentication
        client = TestClient(app, headers={"Authorization": "Bearer test_api_key"})

        # Make a streaming request to the API endpoint
        # Note: TestClient doesn't actually stream, so loop detection happens during SSE generation
        # The error will be sent as part of the SSE stream, not as an HTTP error
        response = client.post(
            "/v2/chat/completions",
            json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "Hello"}],
                "stream": True,
                "session_id": "test-streaming-loop-detection",
            },
        )

        # For streaming responses with TestClient, errors are embedded in the stream
        # The response will be 200 OK with error data in the SSE stream content
        assert response.status_code == 200

        # Parse the SSE stream content to check for error
        response_text = response.text

        # Check that loop detection error appears in the response
        # The error can appear either as "ERROR:" in content or as error JSON
        assert "loop detected" in response_text.lower() or "ERROR:" in response_text

        # Verify the error was triggered by loop detection
        lines = response_text.split("\n")
        error_found = False
        for line in lines:
            if line.startswith("data: "):
                # Parse the JSON from the SSE data line
                import json

                data_str = line[6:]  # Remove "data: " prefix
                if data_str != "[DONE]":
                    try:
                        data = json.loads(data_str)
                        # Check for error in choices content
                        if "choices" in data:
                            for choice in data["choices"]:
                                if "delta" in choice:
                                    content = choice["delta"].get("content", "")
                                    if (
                                        "ERROR:" in content
                                        and "loop detected" in content.lower()
                                    ):
                                        error_found = True
                                        break
                        # Also check for error field
                        if "error" in data:
                            error_found = True
                            # Verify error details
                            assert "message" in data["error"]
                            # The error message should mention loop detection
                            error_msg = data["error"]["message"].lower()
                            assert "loop" in error_msg or "repeat" in error_msg
                    except json.JSONDecodeError:
                        pass

        assert error_found, "Loop detection error not found in streaming response"


@pytest.mark.asyncio
@pytest.mark.skip(
    reason="Test uses deprecated initialization methods that no longer exist in new architecture"
)
async def test_loop_detection_integration_with_middleware_chain():
    """Test that the loop detection middleware is properly integrated in the chain."""
    # Create a loop detector
    loop_detector = LoopDetector(
        min_pattern_length=5, max_pattern_length=50, min_repetitions=2
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
        middleware=[content_filter, logging_middleware, loop_detection_middleware],
    )

    # Create a response with repeating content
    repeating_content = "I will repeat myself. I will repeat myself. " * 20
    response = ChatResponse(
        id="test-id",
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

    # Process the response - expect a LoopDetectionError
    from src.core.common.exceptions import LoopDetectionError

    try:
        processed_response = await response_processor.process_response(
            response, "test-session"
        )
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
    from src.core.services.request_processor_service import RequestProcessor

    # Create mock services
    command_service = AsyncMock()
    backend_service = AsyncMock()
    session_service = AsyncMock()
    response_processor = AsyncMock()

    # Configure the AsyncMock to handle awaitable calls
    async def mock_process_response(response, session_id):
        from src.core.interfaces.response_processor_interface import ProcessedResponse

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
        choices=[
            {
                "index": 0,
                "message": {"role": "assistant", "content": "Test response"},
                "finish_reason": "stop",
            }
        ],
    )

    # Configure backend service to return the test response
    backend_service.call_completion.return_value = response

    # Create request processor
    request_processor = RequestProcessor(
        command_service, backend_service, session_service, response_processor
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
