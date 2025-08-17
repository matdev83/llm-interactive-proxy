"""
Test doubles (mocks, stubs, fakes) for core interfaces.

This module provides test implementations of interfaces for use in unit tests.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any

from src.core.domain.chat import (
    ChatRequest,
    ChatResponse,
    StreamingChatResponse,
)
from src.core.domain.configuration import (
    BackendConfig,
    LoopDetectionConfig,
    ReasoningConfig,
)
from src.core.domain.session import Session, SessionInteraction, SessionState
from src.core.interfaces.backend_service import BackendError, IBackendService
from src.core.interfaces.command_service import (
    ICommandService,
    ProcessedResult,
)
from src.core.interfaces.di import (
    IServiceProvider,
    IServiceScope,
)
from src.core.interfaces.domain_entities import ISession
from src.core.interfaces.loop_detector import ILoopDetector, LoopDetectionResult
from src.core.interfaces.rate_limiter import IRateLimiter, RateLimitInfo
from src.core.interfaces.repositories import ISessionRepository
from src.core.interfaces.response_processor import (
    IResponseMiddleware,
    IResponseProcessor,
    ProcessedResponse,
)
from src.core.interfaces.session_service import ISessionService


#
# Mock Service Provider
#
class MockServiceProvider(IServiceProvider):
    """A mock service provider for testing."""

    def __init__(self):
        self.services: dict[type, Any] = {}

    def get_service(self, service_type: type[Any]) -> Any | None:
        return self.services.get(service_type)

    def get_required_service(self, service_type: type[Any]) -> Any:
        service = self.get_service(service_type)
        if service is None:
            raise KeyError(f"No service registered for {service_type.__name__}")
        return service

    def create_scope(self) -> IServiceScope:
        return MockServiceScope(self)


class MockServiceScope(IServiceScope):
    """A mock service scope for testing."""

    def __init__(self, provider: MockServiceProvider):
        self._provider = provider

    @property
    def service_provider(self) -> IServiceProvider:
        return self._provider

    async def dispose(self) -> None:
        pass


#
# Mock Backend Service
#
class MockBackendService(IBackendService):
    """A mock backend service for testing."""

    def __init__(self):
        self.responses: list[ChatResponse | Exception] = []
        self.stream_responses: list[list[StreamingChatResponse]] = []
        self.calls: list[ChatRequest] = []
        self.validations: dict[str, dict[str, bool]] = {}

    def add_response(self, response: ChatResponse | Exception) -> None:
        self.responses.append(response)

    async def call_completion(
        self, request: ChatRequest, stream: bool = False
    ) -> ChatResponse | AsyncIterator[StreamingChatResponse]:
        self.calls.append(request)

        if stream:
            if not self.stream_responses:
                raise BackendError("No stream responses configured")
            responses = self.stream_responses.pop(0)

            async def response_iterator():
                for response in responses:
                    yield response
                    await asyncio.sleep(0.01)

            return response_iterator()
        else:
            if not self.responses:
                raise BackendError("No responses configured")
            response = self.responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response

    async def chat_completions(
        self, request: ChatRequest, **kwargs: Any
    ) -> ChatResponse | AsyncIterator[StreamingChatResponse]:
        # This method is now implemented to satisfy the IBackendService interface
        # It can simply call call_completion, or have its own logic if needed for specific tests
        return await self.call_completion(request, stream=bool(request.stream))

    async def validate_backend_and_model(
        self, backend: str, model: str
    ) -> tuple[bool, str | None]:
        if backend not in self.validations:
            return False, f"Backend {backend} not supported"

        if model not in self.validations[backend]:
            return False, f"Model {model} not supported on backend {backend}"

        is_valid = self.validations[backend][model]
        error = None if is_valid else f"Invalid model {model} for backend {backend}"
        return is_valid, error


#
# Mock Session Service
#
class MockSessionService(ISessionService):
    """A mock session service for testing."""

    def __init__(self):
        self.sessions: dict[str, Session] = {}

    async def get_session(self, session_id: str) -> Session:
        if session_id not in self.sessions:
            self.sessions[session_id] = Session(
                session_id=session_id,
                state=SessionState(
                    backend_config=BackendConfig(),
                    reasoning_config=ReasoningConfig(),
                    loop_config=LoopDetectionConfig(),
                ),
                created_at=datetime.now(timezone.utc),
                last_active_at=datetime.now(timezone.utc),
            )
        return self.sessions[session_id]

    async def update_session(self, session: ISession) -> None:
        self.sessions[session.session_id] = session  # type: ignore

    async def delete_session(self, session_id: str) -> bool:
        if session_id in self.sessions:
            del self.sessions[session_id]
            return True
        return False

    async def get_all_sessions(self) -> list[Session]:
        return list(self.sessions.values())


#
# Mock Command Service
#
class MockCommandService(ICommandService):
    """A mock command service for testing."""

    def __init__(self):
        self.commands: dict[str, Any] = {}
        self.processed: list[list[Any]] = []
        self.results: list[ProcessedResult] = []

    async def process_commands(
        self, messages: list[Any], session_id: str
    ) -> ProcessedResult:
        self.processed.append(messages)

        if not self.results:
            return ProcessedResult(
                modified_messages=messages, command_executed=False, command_results=[]
            )

        return self.results.pop(0)

    async def register_command(self, command_name: str, command_handler: Any) -> None:
        self.commands[command_name] = command_handler

    def add_result(self, result: ProcessedResult) -> None:
        self.results.append(result)


#
# Mock Rate Limiter
#
class MockRateLimiter(IRateLimiter):
    """A mock rate limiter for testing."""

    def __init__(self):
        self.limits: dict[str, RateLimitInfo] = {}
        self.usage: dict[str, int] = {}

    async def check_limit(self, key: str) -> RateLimitInfo:
        if key not in self.limits:
            return RateLimitInfo(
                is_limited=False,
                remaining=100,
                reset_at=None,
                limit=100,
                time_window=60,
            )
        return self.limits[key]

    async def record_usage(self, key: str, cost: int = 1) -> None:
        self.usage[key] = self.usage.get(key, 0) + cost

    async def reset(self, key: str) -> None:
        if key in self.usage:
            del self.usage[key]

    async def set_limit(self, key: str, limit: int, time_window: int) -> None:
        self.limits[key] = RateLimitInfo(
            is_limited=False,
            remaining=limit,
            reset_at=None,
            limit=limit,
            time_window=time_window,
        )


#
# Mock Loop Detector
#
class MockLoopDetector(ILoopDetector):
    """A mock loop detector for testing."""

    def __init__(self):
        self.tool_calls: list[dict[str, Any]] = []
        self.results: list[LoopDetectionResult] = []

    async def check_for_loops(self, content: str) -> LoopDetectionResult:
        if not self.results:
            return LoopDetectionResult(has_loop=False)
        return self.results.pop(0)

    async def register_tool_call(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> None:
        self.tool_calls.append({"name": tool_name, "arguments": arguments})

    async def clear_history(self) -> None:
        self.tool_calls.clear()

    async def configure(
        self,
        _min_pattern_length: int = 100,
        _max_pattern_length: int = 8000,
        _min_repetitions: int = 2,
    ) -> None:
        pass

    def add_result(self, result: LoopDetectionResult) -> None:
        self.results.append(result)


#
# Mock Response Processor
#
class MockResponseProcessor(IResponseProcessor):
    """A mock response processor for testing."""

    def __init__(self):
        self.middleware: list[IResponseMiddleware] = []
        self.processed: list[Any] = []
        self.results: list[ProcessedResponse] = []
        self.stream_results: list[list[ProcessedResponse]] = []

    async def process_response(
        self, response: Any, session_id: str
    ) -> ProcessedResponse:
        self.processed.append(response)

        if not self.results:
            return ProcessedResponse(content="Mock response")

        return self.results.pop(0)

    def process_streaming_response(
        self, response_iter: AsyncIterator[Any], session_id: str
    ) -> AsyncIterator[ProcessedResponse]:
        # This is a simplified implementation for testing
        # In a real implementation, we'd process the stream

        async def response_generator():
            chunks = []
            async for chunk in response_iter:
                chunks.append(chunk)

            self.processed.append(chunks)

            if not self.stream_results:
                yield ProcessedResponse(content="Mock chunk")
                return

            results = self.stream_results.pop(0)
            for result in results:
                yield result

        return response_generator()

    async def register_middleware(
        self, middleware: IResponseMiddleware, _priority: int = 0
    ) -> None:
        self.middleware.append(middleware)

    def add_result(self, result: ProcessedResponse) -> None:
        self.results.append(result)


#
# Mock Session Repository
#
class MockSessionRepository(ISessionRepository):
    """A mock session repository for testing."""

    def __init__(self):
        self.sessions: dict[str, Session] = {}
        self.user_sessions: dict[str, list[Session]] = {}

    async def get_by_id(self, id: str) -> Session | None:
        return self.sessions.get(id)

    async def get_all(self) -> list[Session]:
        return list(self.sessions.values())

    async def add(self, entity: Session) -> Session:
        self.sessions[entity.session_id] = entity
        return entity

    async def update(self, entity: Session) -> Session:
        self.sessions[entity.session_id] = entity
        return entity

    async def delete(self, id: str) -> bool:
        if id in self.sessions:
            del self.sessions[id]
            return True
        return False

    async def get_by_user_id(self, user_id: str) -> list[Session]:
        return self.user_sessions.get(user_id, [])

    async def cleanup_expired(self, max_age_seconds: int) -> int:
        count = 0
        current_time = datetime.now(timezone.utc)

        expired_ids = [
            session_id
            for session_id, session in self.sessions.items()
            if (current_time - session.last_active_at).total_seconds() > max_age_seconds
        ]

        for session_id in expired_ids:
            del self.sessions[session_id]
            count += 1

        return count


#
# Test Data Builder
#
class TestDataBuilder:
    """Helper for building test data objects."""

    @staticmethod
    def create_session(session_id: str = "test-session") -> Session:
        """Create a test session."""
        return Session(
            session_id=session_id,
            state=SessionState(
                backend_config=BackendConfig(
                    backend_type="openai", model="gpt-4", interactive_mode=True
                ),
                reasoning_config=ReasoningConfig(temperature=0.7),
                loop_config=LoopDetectionConfig(loop_detection_enabled=True),
            ),
            created_at=datetime.now(timezone.utc),
            last_active_at=datetime.now(timezone.utc),
        )

    @staticmethod
    def create_interaction(
        prompt: str = "Hello", response: str = "Hi there!"
    ) -> SessionInteraction:
        """Create a test interaction."""
        return SessionInteraction(
            prompt=prompt,
            handler="backend",
            backend="openai",
            model="gpt-4",
            response=response,
        )

    @staticmethod
    def create_chat_request(
        messages: list[dict[str, Any]] | None = None,
    ) -> ChatRequest:
        """Create a test chat request."""
        if messages is None:
            messages = [{"role": "user", "content": "Hello"}]

        return ChatRequest(
            messages=[
                {"role": item["role"], "content": item["content"]} for item in messages
            ],
            model="gpt-4",
            stream=False,
        )

    @staticmethod
    def create_chat_response(content: str = "Hello there!") -> ChatResponse:
        """Create a test chat response."""
        return ChatResponse(
            id="resp-123",
            created=int(datetime.now(timezone.utc).timestamp()),
            model="gpt-4",
            choices=[
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            usage={"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        )
