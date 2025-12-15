"""
Mock BackendService for testing.
"""

from collections.abc import AsyncIterator
from typing import Any

from src.connectors.base import LLMBackend
from src.core.domain.chat import ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.backend_service_interface import IBackendService
from src.core.interfaces.response_processor_interface import ProcessedResponse


class MockBackendService(IBackendService):
    """Mock implementation of IBackendService for testing."""

    def __init__(self) -> None:
        self.call_completion_was_called = False

    async def call_completion(
        self,
        request: ChatRequest,
        stream: bool = False,
        allow_failover: bool = True,
        context: RequestContext | None = None,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        self.call_completion_was_called = True
        return await self.chat_completions(request, stream=stream)

    async def chat_completions(
        self, request: ChatRequest, **kwargs: Any
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        self.call_completion_was_called = True
        if kwargs.get("stream", False):

            async def stream_generator() -> AsyncIterator[ProcessedResponse]:
                # Return ProcessedResponse objects for streaming
                yield ProcessedResponse(
                    content={
                        "id": "test-id",
                        "object": "chat.completion.chunk",
                        "created": 123,
                        "model": "test-model",
                        "choices": [{"delta": {"content": "Hello, "}, "index": 0}],
                    }
                )
                yield ProcessedResponse(
                    content={
                        "id": "test-id",
                        "object": "chat.completion.chunk",
                        "created": 123,
                        "model": "test-model",
                        "choices": [{"delta": {"content": "world!"}, "index": 0}],
                    }
                )

            return StreamingResponseEnvelope(
                content=stream_generator(), headers={}, status_code=200
            )
        else:
            # Return non-streaming response
            return ResponseEnvelope(
                content={
                    "id": "test-id",
                    "object": "chat.completion",
                    "created": 123,
                    "model": "test-model",
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": "Hello, world!",
                            },
                            "index": 0,
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "total_tokens": 0,
                    },
                },
                headers={},
                status_code=200,
            )

    async def validate_backend_and_model(
        self, backend: str, model: str
    ) -> tuple[bool, str | None]:
        return True, None

    def get_active_backends(self) -> dict[str, LLMBackend]:
        """Get all active backend instances.

        Returns:
            A dictionary mapping backend instance names to LLMBackend objects.
        """
        return {}

    def get_backend(self, backend_type: str) -> LLMBackend:
        """Get a backend instance synchronously (for testing purposes).

        Args:
            backend_type: The type of backend to get

        Returns:
            A backend instance

        Raises:
            KeyError: If backend not found
        """
        raise KeyError(f"Backend '{backend_type}' not found in mock")
