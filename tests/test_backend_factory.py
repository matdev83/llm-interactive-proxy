"""
Test-specific backend factory that never attempts real API connections.

This module provides mock backends for testing that implement the required interfaces
but never make real API calls.
"""

import asyncio
import logging
from typing import Any
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from src.core.domain.chat import ChatRequest
from src.core.interfaces.backend_service_interface import IBackendService

logger = logging.getLogger(__name__)


class MockBackendBase:
    """Base class for mock backends used in tests."""

    def __init__(self, name: str):
        """Initialize the mock backend.

        Args:
            name: The name of the backend
        """
        self.name = name
        self.api_keys = ["test-key"]
        self.available_models = [f"{name}-model-1", f"{name}-model-2"]

        # Create a mock for chat_completions
        self.chat_completions_mock = AsyncMock()
        self.chat_completions_mock.return_value = self._create_default_response()

    def _create_default_response(self) -> dict[str, Any]:
        """Create a default response for the mock backend."""
        return {
            "id": f"mock-{self.name}-response",
            "object": "chat.completion",
            "created": 1234567890,
            "model": f"{self.name}-model-1",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": f"Mock {self.name} response",
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        }

    def get_available_models(self) -> list[str]:
        """Get the available models for this backend."""
        return self.available_models

    async def chat_completions(
        self,
        request_data: ChatRequest,
        processed_messages: list[dict[str, Any]],
        effective_model: str,
    ) -> Any:
        """Mock implementation of chat_completions that returns a predefined response."""
        return self.chat_completions_mock(
            request_data=request_data,
            processed_messages=processed_messages,
            effective_model=effective_model,
        )

    def configure_response(self, response: dict[str, Any]) -> None:
        """Configure the response that will be returned by chat_completions."""
        self.chat_completions_mock.return_value = response

    def configure_streaming_response(self, chunks: list[str]) -> None:
        """Configure a streaming response."""

        async def gen():
            for chunk in chunks:
                yield f"data: {chunk}\n\n"
                await asyncio.sleep(0.01)

        response = StreamingResponse(gen(), media_type="text/event-stream")
        self.chat_completions_mock.return_value = response

    def configure_error(self, status_code: int, error_message: str) -> None:
        """Configure an error response."""
        from fastapi import HTTPException

        self.chat_completions_mock.side_effect = HTTPException(
            status_code=status_code, detail={"error": error_message}
        )


class MockOpenAI(MockBackendBase):
    """Mock OpenAI backend for testing."""

    def __init__(self):
        """Initialize the mock OpenAI backend."""
        super().__init__("openai")
        self.available_models = ["gpt-3.5-turbo", "gpt-4"]


class MockOpenRouter(MockBackendBase):
    """Mock OpenRouter backend for testing."""

    def __init__(self):
        """Initialize the mock OpenRouter backend."""
        super().__init__("openrouter")
        self.available_models = ["openrouter:gpt-4", "openrouter:claude-3-sonnet"]


class MockGemini(MockBackendBase):
    """Mock Gemini backend for testing."""

    def __init__(self):
        """Initialize the mock Gemini backend."""
        super().__init__("gemini")
        self.available_models = ["gemini:gemini-pro", "gemini:gemini-1.5-pro"]


class MockAnthropicBackend(MockBackendBase):
    """Mock Anthropic backend for testing."""

    def __init__(self):
        """Initialize the mock Anthropic backend."""
        super().__init__("anthropic")
        self.available_models = ["claude-3-opus", "claude-3-sonnet"]


class TestBackendFactory:
    """Factory for creating mock backends for testing."""

    @staticmethod
    def create_backend(name: str) -> MockBackendBase:
        """Create a mock backend instance based on the name.

        Args:
            name: The name of the backend to create

        Returns:
            A mock backend instance

        Raises:
            ValueError: If the backend name is not supported
        """
        if name == "openai":
            return MockOpenAI()
        elif name == "openrouter":
            return MockOpenRouter()
        elif name == "gemini":
            return MockGemini()
        elif name == "anthropic":
            return MockAnthropicBackend()
        else:
            # Create a generic mock backend
            return MockBackendBase(name)

    @staticmethod
    async def initialize_backend_for_test(
        app: FastAPI, backend_name: str
    ) -> MockBackendBase:
        """Initialize a mock backend for testing and register it with the backend service.

        Args:
            app: The FastAPI application
            backend_name: The name of the backend to initialize

        Returns:
            The initialized mock backend
        """
        # Create the mock backend
        backend = TestBackendFactory.create_backend(backend_name)

        # Register it with the backend service
        backend_service = app.state.service_provider.get_required_service(
            IBackendService
        )
        if backend_service is None:
            raise RuntimeError("IBackendService not available from service provider")

        # Store the backend in the backend service
        if not hasattr(backend_service, "_backends"):
            backend_service._backends = {}
        backend_service._backends[backend_name] = backend

        return backend


def patch_backend_initialization(app: FastAPI) -> None:
    """Patch the backend initialization to use mock backends.

    This function replaces the real backend initialization with our mock version
    that never makes real API calls.

    Args:
        app: The FastAPI application to patch
    """
    # Store the original function for reference
    original_func = getattr(app.state, "original_initialize_backend_for_test", None)
    if original_func is None:
        # Only store the original once
        from tests.conftest import initialize_backend_for_test

        app.state.original_initialize_backend_for_test = initialize_backend_for_test

    # Replace the function in the module
    import tests.conftest

    tests.conftest.initialize_backend_for_test = (
        TestBackendFactory.initialize_backend_for_test
    )

    # Log that we've patched the function
    logger.info("Patched backend initialization to use mock backends")
