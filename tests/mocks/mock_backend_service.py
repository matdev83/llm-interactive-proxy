"""
Mock BackendService for testing.
"""

from collections.abc import AsyncIterator

from src.core.domain.chat import ChatRequest, ChatResponse, StreamingChatResponse
from src.core.interfaces.backend_service_interface import IBackendService


class MockBackendService(IBackendService):
    """Mock implementation of IBackendService for testing."""

    def __init__(self) -> None:
        self.call_completion_was_called = False

    async def call_completion(
        self,
        request: ChatRequest,
        stream: bool = False,
        allow_failover: bool = True,
        context: object | None = None,
    ) -> ChatResponse | AsyncIterator[StreamingChatResponse]:
        self.call_completion_was_called = True
        return await self.chat_completions(
            request,
            stream=stream,
            allow_failover=allow_failover,
            context=context,
        )

    async def chat_completions(
        self, request: ChatRequest, **kwargs
    ) -> ChatResponse | AsyncIterator[StreamingChatResponse]:
        self.call_completion_was_called = True
        if kwargs.get("stream", False):

            async def stream_generator() -> AsyncIterator[StreamingChatResponse]:
                # Return raw dictionaries that match OpenAI's streaming format
                yield {
                    "id": "test-id",
                    "object": "chat.completion.chunk",
                    "created": 123,
                    "model": "test-model",
                    "choices": [{"delta": {"content": "Hello, "}, "index": 0}],
                }
                yield {
                    "id": "test-id",
                    "object": "chat.completion.chunk",
                    "created": 123,
                    "model": "test-model",
                    "choices": [{"delta": {"content": "world!"}, "index": 0}],
                }

            return stream_generator()
        else:
            return ChatResponse(
                id="test-id",
                object="chat.completion",
                created=123,
                model="test-model",
                choices=[
                    {
                        "message": {"role": "assistant", "content": "Hello, world!"},
                        "index": 0,
                        "finish_reason": "stop",
                    }
                ],
                usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            )

    async def validate_backend_and_model(
        self, backend: str, model: str
    ) -> tuple[bool, str | None]:
        return True, None
