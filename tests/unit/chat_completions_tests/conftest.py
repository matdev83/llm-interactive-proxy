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

    if (
        not hasattr(interactive_client.app.state, "gemini_backend")
        or getattr(interactive_client.app.state, "gemini_backend", None) is None
    ):
        interactive_client.app.state.gemini_backend = _MockGemini()
    return None
