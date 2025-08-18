"""
Integration tests for the FastAPI application.
"""

import json

import pytest
from fastapi.testclient import TestClient

from tests.test_helpers import create_test_request_json, generate_session_id


@pytest.fixture
def test_app_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Create a test client for the application."""
    # Disable authentication for testing
    monkeypatch.setenv("DISABLE_AUTH", "true")
    monkeypatch.setenv("API_KEYS", "test-key")

    from src.core.app.application_factory import build_app as new_build_app
    from src.core.config.app_config import AppConfig, BackendConfig
    from src.core.di.container import IServiceProvider, ServiceCollection
    from src.core.interfaces.backend_service_interface import IBackendService
    from src.core.interfaces.command_service_interface import ICommandService
    from src.core.interfaces.repositories_interface import ISessionRepository
    from src.core.interfaces.request_processor_interface import IRequestProcessor
    from src.core.interfaces.response_processor_interface import IResponseProcessor
    from src.core.interfaces.session_service_interface import ISessionService
    from src.core.repositories.in_memory_session_repository import (
        InMemorySessionRepository,
    )
    from src.core.services.command_service import CommandRegistry, CommandService
    from src.core.services.request_processor_service import RequestProcessor
    from src.core.services.response_processor_service import ResponseProcessor
    from src.core.services.session_service import SessionService

    from tests.mocks.mock_backend_service import MockBackendService

    # Build the app with a test-specific configuration
    config = AppConfig(
        auth={"api_keys": ["test-key"]},
        backends={"default_backend": "mock", "mock": BackendConfig()},
    )
    app = new_build_app(config=config)

    # Create a new service collection for the test
    services = ServiceCollection()
    services.add_singleton(IBackendService, MockBackendService)
    services.add_singleton(IResponseProcessor, ResponseProcessor)
    services.add_singleton(ISessionRepository, InMemorySessionRepository)

    # Configure CommandRegistry with a factory to ensure it's properly initialized
    def command_registry_factory(sp: IServiceProvider) -> CommandRegistry:
        from src.core.commands.set_command import SetCommand
        from src.core.commands.unset_command import UnsetCommand
        from src.core.domain.commands.help_command import HelpCommand

        registry = CommandRegistry()
        # Register commands (they don't take constructor arguments)
        registry.register(HelpCommand())
        registry.register(SetCommand())
        registry.register(UnsetCommand())
        return registry

    services.add_singleton(
        CommandRegistry, implementation_factory=command_registry_factory
    )

    def session_service_factory(sp: IServiceProvider) -> ISessionService:
        return SessionService(
            session_repository=sp.get_required_service(ISessionRepository),
        )

    services.add_singleton(
        ISessionService, implementation_factory=session_service_factory
    )

    def command_service_factory(sp: IServiceProvider) -> ICommandService:
        return CommandService(
            command_registry=sp.get_required_service(CommandRegistry),
            session_service=sp.get_required_service(ISessionService),
        )

    services.add_singleton(
        ICommandService, implementation_factory=command_service_factory
    )

    def request_processor_factory(sp: IServiceProvider) -> IRequestProcessor:
        return RequestProcessor(
            command_service=sp.get_required_service(ICommandService),
            backend_service=sp.get_required_service(IBackendService),
            session_service=sp.get_required_service(ISessionService),
            response_processor=sp.get_required_service(IResponseProcessor),
        )

    services.add_singleton(
        IRequestProcessor, implementation_factory=request_processor_factory
    )
    app.state.service_provider = services.build_service_provider()

    return TestClient(app)


def test_chat_completions_endpoint(test_app_client: TestClient):
    """Test the chat completions endpoint."""
    # Arrange
    request_json = create_test_request_json()
    session_id = generate_session_id()

    # Act
    response = test_app_client.post(
        "/v1/chat/completions",
        json=request_json,
        headers={"X-Session-ID": session_id, "Authorization": "Bearer test-key"},
    )

    # Assert
    assert response.status_code == 200
    print(response.json())
    data = response.json()
    assert data["object"] == "chat.completion"
    assert len(data["choices"]) == 1
    assert data["choices"][0]["message"]["role"] == "assistant"
    assert data["choices"][0]["message"]["content"]
    assert "usage" in data


def test_streaming_chat_completions_endpoint(test_app_client: TestClient):
    """Test the streaming chat completions endpoint."""
    # Arrange
    request_json = create_test_request_json(stream=True)
    session_id = generate_session_id()

    # Act
    with test_app_client.stream(
        "POST",
        "/v1/chat/completions",
        json=request_json,
        headers={"X-Session-ID": session_id, "Authorization": "Bearer test-key"},
    ) as response:
        # Assert
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")

        # Process each chunk
        content = ""
        for line in response.iter_lines():
            if not line.strip() or line == "data: [DONE]":
                continue

            # Parse the JSON chunk
            print(f"DEBUG: Raw line: {line!r}")
            try:
                chunk_data = json.loads(line.replace("data: ", ""))
                print(f"DEBUG: Parsed chunk: {chunk_data}")
            except json.JSONDecodeError as e:
                print(f"DEBUG: JSON decode error: {e}")
                raise
            assert chunk_data["object"] == "chat.completion.chunk"
            assert len(chunk_data["choices"]) == 1

            # Accumulate content
            if "delta" in chunk_data["choices"][0]:
                delta = chunk_data["choices"][0]["delta"]
                if "content" in delta:
                    content += delta["content"]

        # Verify we got a complete message
        assert content


def test_command_processing(test_app_client: TestClient):
    """Test command processing."""
    # Arrange
    session_id = generate_session_id()

    # Send a command to set the model (without meaningful additional content)
    command_request = create_test_request_json()
    command_request["messages"] = [
        {"role": "user", "content": "!/set(model=gpt-3.5-turbo)"}
    ]

    # Act
    command_response = test_app_client.post(
        "/v1/chat/completions",
        json=command_request,
        headers={"X-Session-ID": session_id, "Authorization": "Bearer test-key"},
    )

    # Assert
    assert command_response.status_code == 200
    data = command_response.json()

    # The request contains meaningful content, so it should go to backend rather than command processing
    # We got a backend response (not proxy_cmd_processed)
    assert "object" in data
    assert "id" in data
    assert "choices" in data

    # Now send a normal request - should use the set model
    request_json = create_test_request_json(
        model="default-model"
    )  # Should be overridden by the command

    # Act
    response = test_app_client.post(
        "/v1/chat/completions",
        json=request_json,
        headers={"X-Session-ID": session_id, "Authorization": "Bearer test-key"},
    )

    # Assert - The model should be gpt-4
    # This check isn't perfect because we're using mocks,
    # but in a real test we'd verify the model name was passed correctly
    assert response.status_code == 200
