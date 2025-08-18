"""
Pytest configuration for chat completions tests.

This file provides fixtures specific to chat completion tests.
"""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(test_client: TestClient) -> TestClient:
    """Alias for test_client fixture to match test expectations."""
    return test_client


@pytest.fixture
def app(test_app):
    """Return the FastAPI app for tests that need direct app access."""
    return test_app


@pytest.fixture
def interactive_client(test_client: TestClient) -> TestClient:
    """Alias for an interactive-mode client used across cline-oriented tests."""
    return test_client


@pytest.fixture
def commands_disabled_client(test_client: TestClient) -> TestClient:
    """Client with interactive commands disabled for tests expecting that behavior."""
    test_client.app.state.disable_interactive_commands = True
    return test_client


@pytest.fixture
def mock_gemini_backend(interactive_client: TestClient) -> None:
    """Attach a minimal mock Gemini backend to the app state for tests expecting it."""

    class _MockGemini:
        api_keys: list[str] = ["k"]

        def get_available_models(self):
            return ["gemini:gemini-2.0-flash-001", "gemini:gemini-pro"]

    from src.core.interfaces.backend_service_interface import IBackendService

    svc = interactive_client.app.state.service_provider.get_required_service(
        IBackendService
    )
    svc._backends["gemini"] = _MockGemini()
    return None


class _MockOpenRouter:
    def __init__(self):
        pass

    def get_available_models(self):
        return ["openrouter:gpt-4", "openrouter:claude-3-sonnet"]

    async def chat_completions(self, *args, **kwargs):
        return {
            "id": "mock-response",
            "object": "chat.completion",
            "created": 1234567890,
            "model": "openrouter:gpt-4",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "Mock response"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        }


@pytest.fixture
def mock_openrouter_backend(interactive_client: TestClient) -> _MockOpenRouter:
    """Provide a minimal mock OpenRouter backend for tests."""
    backend = _MockOpenRouter()
    from src.core.interfaces.backend_service_interface import IBackendService

    svc = interactive_client.app.state.service_provider.get_required_service(
        IBackendService
    )
    svc._backends["openrouter"] = backend
    return backend
