"""
Mock backend implementation for regression testing.

This module provides a consistent mock backend that can be used by both
the legacy implementation and the new SOLID architecture for regression testing.
"""

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any, TypedDict

from src.constants import BackendType


class Message(TypedDict):
    role: str
    content: str | None
    tool_calls: list[dict[str, Any]] | None
    tool_calls: list[dict[str, Any]] | None


class Choice(TypedDict):
    message: Message
    finish_reason: str
    index: int


class Usage(TypedDict):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class ChatCompletionResponse(TypedDict):
    id: str
    object: str
    created: int
    model: str
    choices: list[Choice]
    usage: Usage


class MockRegressionBackend:
    """Mock backend implementation for regression testing.

    This class implements the minimal interface needed by both the legacy
    implementation and the new SOLID architecture.
    """

    def __init__(self):
        self.name = "mock-regression"
        self.is_functional = True
        self.available_models = ["mock-model"]
        self.call_count = 0
        self.last_request = None
        self.last_messages = None
        self.last_model = None
        self.last_kwargs = None

    async def initialize(self, **kwargs):
        """Initialize the backend."""
        # Always succeed initialization
        self.is_functional = True
        return True

    def get_available_models(self) -> list[str]:
        """Return the list of available models."""
        return self.available_models

    async def chat_completions(
        self,
        request_data: Any,
        processed_messages: list[dict[str, Any]],
        effective_model: str,
        **kwargs,
    ) -> tuple[ChatCompletionResponse, dict[str, str]] | AsyncIterator[dict[str, Any]]:
        """Handle chat completion requests.

        Args:
            request_data: The request data (could be different types in legacy vs new)
            processed_messages: The processed messages
            effective_model: The effective model to use
            **kwargs: Additional keyword arguments

        Returns:
            Either a tuple of (response, headers) or a streaming response iterator
        """
        self.call_count += 1
        self.last_request = request_data
        self.last_messages = processed_messages
        self.last_model = effective_model
        self.last_kwargs = kwargs

        # Check if streaming is requested
        stream = getattr(request_data, "stream", kwargs.get("stream", False))

        if stream:
            # Return the generator directly
            return self.stream_generator()
        else:
            return self._create_standard_response()

    async def stream_generator(self):
        """Generate streaming response chunks."""
        # First chunk with role
        yield {
            "id": "mock-response-id",
            "object": "chat.completion.chunk",
            "created": 1677858242,
            "model": "mock-model",
            "choices": [
                {"delta": {"role": "assistant"}, "index": 0, "finish_reason": None}
            ],
        }

        # Content chunks
        message = "This is a mock response from the regression test backend."
        words = message.split()

        for word in words:
            await asyncio.sleep(0.01)  # Small delay for realism
            yield {
                "id": "mock-response-id",
                "object": "chat.completion.chunk",
                "created": 1677858242,
                "model": "mock-model",
                "choices": [
                    {
                        "delta": {"content": word + " "},
                        "index": 0,
                        "finish_reason": None,
                    }
                ],
            }

        # Final chunk
        yield {
            "id": "mock-response-id",
            "object": "chat.completion.chunk",
            "created": 1677858242,
            "model": "mock-model",
            "choices": [{"delta": {}, "index": 0, "finish_reason": "stop"}],
        }

    def _create_standard_response(
        self,
    ) -> tuple[ChatCompletionResponse, dict[str, str]]:
        """Create a standard (non-streaming) response."""
        response: ChatCompletionResponse = {
            "id": "mock-response-id",
            "object": "chat.completion",
            "created": 1677858242,
            "model": "mock-model",
            "choices": [
                {
                    "message": Message(
                        role="assistant",
                        content="This is a mock response from the regression test backend.",
                        tool_calls=None,
                    ),
                    "finish_reason": "stop",
                    "index": 0,
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
        }

        # Handle tool calls if present in the last request
        if (
            self.last_request
            and hasattr(self.last_request, "tools")
            and self.last_request.tools
        ):
            # Check if tool_choice is "auto" or a specific tool
            tool_choice = getattr(self.last_request, "tool_choice", None)
            if tool_choice and tool_choice != "none":
                response["choices"][0]["message"]["tool_calls"] = [
                    {
                        "id": "call_abc123",
                        "type": "function",
                        "function": {
                            "name": "get_current_weather",
                            "arguments": json.dumps({"location": "San Francisco, CA"}),
                        },
                    }
                ]
                response["choices"][0]["finish_reason"] = "tool_calls"
                # Remove content when tool calls are present
                response["choices"][0]["message"]["content"] = None

        headers = {"content-type": "application/json", "x-mock-backend": "true"}

        return response, headers


# Legacy compatibility
class MockRegressionBackendFactory:
    """Factory for creating MockRegressionBackend instances for legacy code."""

    @staticmethod
    def create_backend():
        """Create a new MockRegressionBackend instance."""
        return MockRegressionBackend()

    @staticmethod
    def register_backend():
        """Register the mock backend with the legacy backend registry."""
        try:
            from src.backends import register_backend

            # Create a factory function for the legacy backend registry
            def factory_func(config, httpx_client):
                backend = MockRegressionBackend()
                return backend

            # Register with legacy backend system
            register_backend(BackendType.MOCK, factory_func)
        except ImportError:
            # src.backends might not be available in some environments
            pass


# New architecture compatibility
class MockRegressionBackendProvider:
    """Provider for creating MockRegressionBackend instances for new architecture."""

    @staticmethod
    def register_backend(app):
        """Register the mock backend with the new architecture."""
        from src.core.services.backend_factory import BackendFactory

        # Get the backend factory from the service provider
        service_provider = app.state.service_provider
        backend_factory = service_provider.get_service(BackendFactory)

        # Register the mock backend with the factory
        backend_factory.register_backend_type(
            "mock-regression", lambda client, **kwargs: MockRegressionBackend()
        )
