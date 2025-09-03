"""Tests for the versioned API endpoints."""

import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from src.core.app.test_builder import build_test_app as build_app
from src.core.domain.chat import ChatResponse
from src.core.interfaces.backend_service_interface import IBackendService


@pytest.fixture
def app():
    """Create a test app with the new architecture enabled."""
    from src.core.config.app_config import (
        AppConfig,
        AuthConfig,
        BackendConfig,
        BackendSettings,
        SessionConfig,
    )

    # Set environment variables to use new services
    os.environ["USE_NEW_BACKEND_SERVICE"] = "true"
    os.environ["USE_NEW_SESSION_SERVICE"] = "true"
    os.environ["USE_NEW_COMMAND_SERVICE"] = "true"
    os.environ["USE_NEW_REQUEST_PROCESSOR"] = "true"

    # Create a test configuration with proper API keys
    test_config = AppConfig(
        host="localhost",
        port=9000,
        proxy_timeout=300,
        command_prefix="!/",
        backends=BackendSettings(
            default_backend="openai",
            openai=BackendConfig(api_key=["test_openai_key"]),
            openrouter=BackendConfig(api_key=["test_openrouter_key"]),
            anthropic=BackendConfig(api_key=["test_anthropic_key"]),
        ),
        auth=AuthConfig(
            disable_auth=False, api_keys=["test-proxy-key"]  # Enable auth with test key
        ),
        session=SessionConfig(
            cleanup_enabled=False,
            default_interactive_mode=True,
        ),
    )

    # Build app with the test configuration
    app = build_app(test_config)

    yield app

    # Clean up
    for key in [
        "USE_NEW_BACKEND_SERVICE",
        "USE_NEW_SESSION_SERVICE",
        "USE_NEW_COMMAND_SERVICE",
        "USE_NEW_REQUEST_PROCESSOR",
    ]:
        if key in os.environ:
            del os.environ[key]


@pytest.fixture
def client(app: FastAPI):
    """Create a test client that uses the fully-initialized test_app."""
    # Use the test_app fixture which provides a fully initialized app
    # The TestClient context manager handles startup/shutdown events
    with TestClient(app) as client:
        yield client


@pytest.fixture
async def initialized_app(app: FastAPI):
    """Return the initialized app for testing.

    The app is already properly initialized by build_app in the app fixture.
    This fixture exists for compatibility with tests that expect it.
    """
    # Ensure the app has all required services properly initialized
    from src.core.app.controllers.chat_controller import ChatController
    from src.core.config.app_config import AppConfig
    from src.core.di.services import set_service_provider
    from src.core.interfaces.request_processor_interface import IRequestProcessor
    from src.core.services.request_processor_service import RequestProcessor

    # If service provider is not available or chat controller isn't registered, initialize it
    if (
        not hasattr(app.state, "service_provider")
        or app.state.service_provider is None
        or app.state.service_provider.get_service(ChatController) is None
    ):

        # Get or create config
        config = getattr(app.state, "app_config", None)
        if config is None:
            config = AppConfig()
            app.state.app_config = config

        # Use the modern staged initialization approach instead of deprecated methods
        from src.core.app.test_builder import build_test_app_async

        # Build test app using the modern async approach - this handles all initialization automatically
        test_app = await build_test_app_async(config)

        # Copy the service provider from the properly initialized test app
        provider = test_app.state.service_provider
        set_service_provider(provider)
        app.state.service_provider = provider

        # Verify that the key services are available
        try:
            request_processor = provider.get_service(IRequestProcessor)
            if request_processor is None:
                # Create and register RequestProcessor if not available
                from src.core.interfaces.backend_service_interface import (
                    IBackendService,
                )
                from src.core.interfaces.command_service_interface import (
                    ICommandService,
                )
                from src.core.interfaces.response_processor_interface import (
                    IResponseProcessor,
                )
                from src.core.interfaces.session_service_interface import (
                    ISessionService,
                )

                # Get required dependencies
                cmd = provider.get_service(ICommandService)
                backend = provider.get_service(IBackendService)
                session = provider.get_service(ISessionService)
                response_proc = provider.get_service(IResponseProcessor)

                # Create request processor if all dependencies are available
            if cmd and backend and session and response_proc:
                try:
                    # Create request processor properly
                    request_processor = RequestProcessor(
                        command_service=cmd,
                        backend_service=backend,
                        session_service=session,
                        response_processor=response_proc,
                    )

                    # Register it in the provider
                    provider._singleton_instances[IRequestProcessor] = request_processor
                    provider._singleton_instances[RequestProcessor] = request_processor

                    # Also create ChatController and register it
                    from src.core.app.controllers.chat_controller import ChatController

                    chat_controller = ChatController(request_processor)
                    provider._singleton_instances[ChatController] = chat_controller
                except Exception as e:
                    print(f"Error creating RequestProcessor or ChatController: {e}")
        except Exception as e:
            print(f"Error setting up request processor: {e}")

    yield app


def test_versioned_endpoint_exists(client: TestClient):
    """Test that the versioned endpoint exists."""
    # Should not return 404
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "test-model",
            "messages": [{"role": "user", "content": "Test message"}],
        },
    )

    # We expect an error due to missing services, but not a 404
    assert response.status_code != 404


@pytest.mark.asyncio
async def test_versioned_endpoint_with_backend_service(
    initialized_app: FastAPI, client: TestClient
):
    """Test that the versioned endpoint uses the backend service."""
    # Mock the backend service to return a successful response
    from src.core.domain.chat import ChatResponse

    # Create a mock response
    mock_response = ChatResponse(
        id="test-id",
        created=1629380000,  # Add timestamp for created field
        model="test-model",
        choices=[
            {
                "message": {
                    "role": "assistant",
                    "content": "This is a test response from the backend service",
                },
                "index": 0,
                "finish_reason": "stop",
            }
        ],
        usage={"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
    )

    # Get the service provider from the app
    service_provider = initialized_app.state.service_provider

    # Get the backend service
    backend_service = service_provider.get_service(IBackendService)

    # Mock the call_completion method
    original_call_completion = backend_service.call_completion

    async def mock_call_completion(*args, **kwargs):
        return mock_response

    # Apply the mock
    backend_service.call_completion = mock_call_completion

    try:
        # Test with a direct call to the backend service
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "Test backend service"}],
            },
            headers={"Authorization": "Bearer test-proxy-key"},
        )

        # Check the response
        assert response.status_code == 200
        assert (
            "This is a test response from the backend service"
            in response.json()["choices"][0]["message"]["content"]
        )

    finally:
        # Restore the original method
        backend_service.call_completion = original_call_completion


@pytest.mark.asyncio
async def test_versioned_endpoint_with_commands(
    initialized_app: FastAPI, client: TestClient
):
    """Test that the versioned endpoint processes commands."""
    # Mock the request processor to handle commands
    from src.core.interfaces.request_processor_interface import IRequestProcessor

    # Create a mock response
    mock_response = ChatResponse(
        id="test-id",
        created=1629380000,  # Add timestamp for created field
        model="test-model",
        choices=[
            {
                "message": {"role": "assistant", "content": "Command processed: hello"},
                "index": 0,
                "finish_reason": "stop",
            }
        ],
        usage={"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
    )

    # Get the service provider from the app
    service_provider = initialized_app.state.service_provider

    # Get the request processor
    request_processor = service_provider.get_service(IRequestProcessor)

    # Mock the process_request method
    original_process_request = request_processor.process_request

    async def mock_process_request(*args, **kwargs):
        # The real process_request signature is (request, request_data).
        # Support both positional and keyword invocation so the mock
        # intercepts commands regardless of how it's called.
        messages = []
        # If called with kwargs (unlikely), respect that first
        if "messages" in kwargs:
            messages = kwargs.get("messages") or []
        else:
            # Try to extract from positional args: args[1] is request_data
            if len(args) >= 2:
                request_data = args[1]
                # request_data may be a pydantic model or dict
                if hasattr(request_data, "model_dump"):
                    data = request_data.model_dump()
                elif isinstance(request_data, dict):
                    data = request_data
                else:
                    # Try to read attributes
                    try:
                        data = getattr(request_data, "__dict__", {})
                    except Exception:
                        data = {}
                messages = data.get("messages", []) or []

        # Messages may be ChatMessage objects or dicts
        for msg in messages:
            content = None
            if hasattr(msg, "content"):
                content = getattr(msg, "content", None)
            elif isinstance(msg, dict):
                content = msg.get("content")
            if isinstance(content, str) and content.startswith("!/hello"):
                return mock_response

        return await original_process_request(*args, **kwargs)

    # Apply the mock
    request_processor.process_request = mock_process_request

    try:
        # Test with a command
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "!/hello"}],
            },
            headers={"Authorization": "Bearer test-proxy-key"},
        )

        # Check that the command was processed
        assert response.status_code == 200
        assert (
            "Command processed: hello"
            in response.json()["choices"][0]["message"]["content"]
        )

    finally:
        # Restore the original method
        request_processor.process_request = original_process_request


@pytest.mark.asyncio
async def test_compatibility_endpoint(initialized_app: FastAPI, client: TestClient):
    """Test that the compatibility endpoint works."""
    # Mock the request processor to return a successful response
    from src.core.interfaces.request_processor_interface import IRequestProcessor

    # Create a mock response
    mock_response = ChatResponse(
        id="test-id",
        created=1629380000,  # Add timestamp for created field
        model="test-model",
        choices=[
            {
                "message": {
                    "role": "assistant",
                    "content": "This is a compatibility test response",
                },
                "index": 0,
                "finish_reason": "stop",
            }
        ],
        usage={"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
    )

    # Get the service provider from the app
    service_provider = initialized_app.state.service_provider

    # Get the request processor
    request_processor = service_provider.get_service(IRequestProcessor)

    # Mock the process_request method
    original_process_request = request_processor.process_request

    async def mock_process_request(*args, **kwargs):
        return mock_response

    # Apply the mock
    request_processor.process_request = mock_process_request

    try:
        # Test the compatibility endpoint (v1)
        v1_response = client.post(
            "/v1/chat/completions",
            json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "Hello"}],
            },
            headers={"Authorization": "Bearer test-proxy-key"},
        )

        # Test the new endpoint (v2)
        # The v2 endpoint has been removed, so this test should only use v1
        # v2_response = client.post(
        #     "/v2/chat/completions",
        #     json={
        #         "model": "test-model",
        #         "messages": [{"role": "user", "content": "Hello"}],
        #     },
        #     headers={"Authorization": "Bearer test-proxy-key"},
        # )

        # Check that both endpoints return the same response structure
        assert v1_response.status_code == 200
        # assert v2_response.status_code == 200

        # Compare the response structures
        # v1_json = v1_response.json()
        # v2_json = v2_response.json()

        # Both should have the same structure
        # assert v1_json["id"] == v2_json["id"]
        # assert v1_json["model"] == v2_json["model"]
        # assert (
        #     v1_json["choices"][0]["message"]["content"]
        #     == v2_json["choices"][0]["message"]["content"]
        # )

    finally:
        # Restore the original method
        request_processor.process_request = original_process_request
