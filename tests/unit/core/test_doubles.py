"""
Test doubles (mocks, stubs, fakes) for core interfaces.

This module provides test implementations of interfaces for use in unit tests.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI
from src.core.domain.chat import (
    ChatCompletionChoice,
    ChatCompletionChoiceMessage,
    ChatMessage,
    ChatRequest,
    ChatResponse,
)
from src.core.domain.command_results import CommandResult
from src.core.domain.commands.base_command import BaseCommand
from src.core.domain.configuration import (
    BackendConfig,
    LoopDetectionConfig,
    ReasoningConfig,
)
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.domain.session import (
    Session,
    SessionInteraction,
    SessionState,
    SessionStateAdapter,
)
from src.core.interfaces.backend_processor_interface import IBackendProcessor
from src.core.interfaces.backend_service_interface import BackendError, IBackendService
from src.core.interfaces.command_processor_interface import ICommandProcessor
from src.core.interfaces.command_service_interface import (
    ProcessedResult,
)
from src.core.interfaces.di_interface import (
    IServiceProvider,
    IServiceScope,
)
from src.core.interfaces.domain_entities_interface import ISession
from src.core.interfaces.loop_detector_interface import (
    ILoopDetector,
    LoopDetectionResult,
)
from src.core.interfaces.rate_limiter_interface import IRateLimiter, RateLimitInfo
from src.core.interfaces.repositories_interface import ISessionRepository
from src.core.interfaces.response_handler_interface import (
    INonStreamingResponseHandler,
    IStreamingResponseHandler,
)
from src.core.interfaces.response_processor_interface import (
    IResponseProcessor,
    ProcessedResponse,
)
from src.core.interfaces.session_service_interface import ISessionService


class MockSuccessCommand(BaseCommand):
    def __init__(self, command_name: str, app: FastAPI | None = None) -> None:
        self._name = command_name
        self._called = False
        self._called_with_args: dict[str, Any] | None = None

    @property
    def name(self) -> str:
        return self._name

    @property
    def format(self) -> str:
        return f"{self._name}(<args>)"

    @property
    def description(self) -> str:
        return f"Mock command for {self._name}"

    @property
    def called(self) -> bool:
        return self._called

    @property
    def called_with_args(self) -> dict[str, Any] | None:
        return self._called_with_args

    def reset_mock_state(self) -> None:
        self._called = False
        self._called_with_args = None

    async def execute(
        self, args: Mapping[str, Any], session: Session, context: Any = None
    ) -> CommandResult:
        self._called = True
        self._called_with_args = dict(args)  # Convert Mapping to Dict for storage
        return CommandResult(
            success=True, message=f"{self._name} executed successfully", name=self._name
        )


#
# Mock Service Provider
#
class MockServiceProvider(IServiceProvider):
    """A mock service provider for testing."""

    def __init__(self) -> None:
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

    def __init__(self, provider: MockServiceProvider) -> None:
        self._provider = provider

    @property
    def service_provider(self) -> IServiceProvider:
        return self._provider

    async def dispose(self) -> None:
        pass


#
# Mock Backend Service
#
class MockBackendService(IBackendService, IBackendProcessor):
    """A mock backend service for testing."""

    def __init__(self) -> None:
        self.responses: list[
            ResponseEnvelope | StreamingResponseEnvelope | Exception
        ] = []
        self.calls: list[ChatRequest] = []
        self.validations: dict[str, dict[str, bool]] = {
            "openrouter": {"test-model": True}
        }

    def add_response(
        self, response: ResponseEnvelope | StreamingResponseEnvelope | Exception
    ) -> None:
        # If the response is an async generator, wrap it in a StreamingResponseEnvelope
        self.responses.append(response)

    async def call_completion(
        self, request: ChatRequest, stream: bool = False, allow_failover: bool = True
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        self.calls.append(request)

        if not self.responses:
            raise BackendError("No responses configured for MockBackendService")

        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response

        # Normalize domain-level ChatResponse into ResponseEnvelope for tests
        from src.core.domain.chat import ChatResponse
        from src.core.domain.responses import ResponseEnvelope

        if hasattr(response, "__aiter__"):
            return response

        if isinstance(response, ChatResponse):
            # Convert ChatResponse dataclass to legacy dict shape expected by tests
            choices_list = []
            for ch in getattr(response, "choices", []) or []:
                msg = getattr(ch, "message", None)
                msg_dict = {}
                if msg is not None:
                    # msg may be dataclass or dict
                    role = getattr(msg, "role", None)
                    content = getattr(msg, "content", None)
                    if isinstance(role, str):
                        msg_dict["role"] = role
                    if content is not None:
                        msg_dict["content"] = content
                choices_list.append(
                    {
                        "index": getattr(ch, "index", 0),
                        "message": msg_dict,
                        "finish_reason": getattr(ch, "finish_reason", "stop"),
                    }
                )

            content = {
                "id": getattr(response, "id", ""),
                "object": "chat.completion",
                "created": getattr(response, "created", 0),
                "model": getattr(response, "model", ""),
                "choices": choices_list,
                "usage": getattr(response, "usage", None),
            }

            return ResponseEnvelope(
                content=content,
                headers={"content-type": "application/json"},
                status_code=200,
            )

        return response

    async def chat_completions(
        self,
        request: ChatRequest,
        **kwargs: Any,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        return await self.call_completion(request, stream=bool(request.stream))

    # Backwards-compatible helper used by RequestProcessor which expects an
    # IBackendProcessor-like API in some tests. Delegate to call_completion.
    async def process_backend_request(
        self, request: ChatRequest, session_id: str | None = None, context: Any = None
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        return await self.call_completion(
            request, stream=bool(getattr(request, "stream", False))
        )

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

    def __init__(self) -> None:
        self.sessions: dict[str, Session] = {}

    async def get_session(self, session_id: str) -> Session:
        if session_id not in self.sessions:
            self.sessions[session_id] = Session(
                session_id=session_id,
                state=SessionStateAdapter(
                    SessionState(
                        backend_config=BackendConfig(
                            backend_type="mock", model="mock-model"
                        ),
                        reasoning_config=ReasoningConfig(temperature=0.7),  # type: ignore
                        loop_config=LoopDetectionConfig(loop_detection_enabled=True),  # type: ignore
                    )
                ),
                created_at=datetime.now(timezone.utc),
                last_active_at=datetime.now(timezone.utc),
            )
        return self.sessions[session_id]

    async def get_session_async(self, session_id: str) -> Session:
        """Legacy compatibility method, identical to get_session."""
        return await self.get_session(session_id)

    async def create_session(self, session_id: str) -> Session:
        if session_id in self.sessions:
            raise ValueError(f"Session with ID {session_id} already exists.")
        session = Session(
            session_id=session_id,
            state=SessionStateAdapter(
                SessionState(
                    backend_config=BackendConfig(
                        backend_type="mock", model="mock-model"
                    ),
                    reasoning_config=ReasoningConfig(temperature=0.7),  # type: ignore
                    loop_config=LoopDetectionConfig(loop_detection_enabled=True),  # type: ignore
                )
            ),
            created_at=datetime.now(timezone.utc),
            last_active_at=datetime.now(timezone.utc),
        )
        self.sessions[session_id] = session
        return session

    async def get_or_create_session(self, session_id: str | None = None) -> Session:
        if session_id is None:
            # Generate a new session ID if not provided
            session_id = f"test-session-{len(self.sessions) + 1}"
        return await self.get_session(session_id)

    async def update_session(self, session: ISession) -> None:
        self.sessions[session.session_id] = session  # type: ignore

    async def update_session_backend_config(
        self, session_id: str, backend_type: str, model: str
    ) -> None:
        session = await self.get_session(session_id)
        # Use the new field names for BackendConfig
        new_backend_config = BackendConfig(backend_type=backend_type, model=model)
        session.state = session.state.with_backend_config(new_backend_config)
        self.sessions[session_id] = session

    async def delete_session(self, session_id: str) -> bool:
        if session_id in self.sessions:
            del self.sessions[session_id]
            return True
        return False

    async def get_all_sessions(self) -> list[Session]:
        return list(self.sessions.values())


class MockCommandProcessor(ICommandProcessor):
    """A mock command processor for testing."""

    def __init__(self) -> None:
        self.processed: list[list[Any]] = []
        self.results: list[ProcessedResult] = []

    async def process_messages(
        self,
        messages: list[Any],
        session_id: str,
        context: RequestContext | None = None,
    ) -> ProcessedResult:
        self.processed.append(messages)

        if not self.results:
            return ProcessedResult(
                modified_messages=messages, command_executed=False, command_results=[]
            )

        return self.results.pop(0)

    def add_result(self, result: ProcessedResult) -> None:
        self.results.append(result)


#
# Mock Rate Limiter
#
class MockRateLimiter(IRateLimiter):
    """A mock rate limiter for testing."""

    def __init__(self) -> None:
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

    def __init__(self) -> None:
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
        min_pattern_length: int = 100,
        max_pattern_length: int = 8000,
        min_repetitions: int = 2,
    ) -> None:
        pass

    def add_result(self, result: LoopDetectionResult) -> None:
        self.results.append(result)


class MockResponseProcessor(IResponseProcessor):
    """A mock response processor for testing."""

    def __init__(self) -> None:
        self.processed: list[Any] = []
        self.non_streaming_handler = MockNonStreamingResponseHandler()
        self.streaming_handler = MockStreamingResponseHandler()

    async def process_response(
        self, response: Any, session_id: str
    ) -> ProcessedResponse:
        self.processed.append(response)
        processed_response = await self.non_streaming_handler.process_response(response)
        return ProcessedResponse(
            content=processed_response.content,
        )

    async def register_middleware(self, middleware: Any, priority: int = 0) -> None:
        """Register a response middleware (mock implementation)."""

    def process_streaming_response(
        self, response_iterator: AsyncIterator[Any], session_id: str
    ) -> AsyncIterator[ProcessedResponse]:
        async def mock_iterator() -> AsyncIterator[ProcessedResponse]:
            async for chunk in response_iterator:
                yield ProcessedResponse(content=chunk.decode("utf-8"))

        return mock_iterator()


class MockNonStreamingResponseHandler(INonStreamingResponseHandler):
    """A mock non-streaming response handler for testing."""

    async def process_response(self, response: dict[str, Any]) -> ResponseEnvelope:
        return ResponseEnvelope(
            content=response,
            status_code=200,
            headers={"content-type": "application/json"},
        )


class MockStreamingResponseHandler(IStreamingResponseHandler):
    """A mock streaming response handler for testing."""

    async def process_response(
        self, response: AsyncIterator[bytes]
    ) -> StreamingResponseEnvelope:
        return StreamingResponseEnvelope(content=response)


#
# Mock Session Repository
#
class MockSessionRepository(ISessionRepository):
    """A mock session repository for testing."""

    def __init__(self) -> None:
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
            state=SessionStateAdapter(
                SessionState(
                    backend_config=BackendConfig(backend_type="openai", model="gpt-4"),
                    reasoning_config=ReasoningConfig(temperature=0.7),  # type: ignore
                    loop_config=LoopDetectionConfig(loop_detection_enabled=True),  # type: ignore
                )
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
            handler="proxy",
            backend="openai",
            model="gpt-4",
            response=response,
        )

    @staticmethod
    def create_chat_request(
        messages: list[ChatMessage] | None = None,
    ) -> ChatRequest:
        """Create a test chat request."""
        if messages is None:
            messages = [ChatMessage(role="user", content="Hello")]

        return ChatRequest(
            messages=messages,
            model="gpt-4",
            stream=False,
        )

    @staticmethod
    def create_chat_response(
        content: str = "Hello there!",
    ) -> ResponseEnvelope:
        """Create a test chat response envelope."""
        chat_response = ChatResponse(
            id="resp-123",
            created=int(datetime.now(timezone.utc).timestamp()),
            model="gpt-4",
            choices=[
                ChatCompletionChoice(
                    index=0,
                    message=ChatCompletionChoiceMessage(
                        role="assistant", content=content
                    ),
                    finish_reason="stop",
                )
            ],
            usage={"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        )
        return ResponseEnvelope(
            content=chat_response.model_dump(),
            status_code=200,
            headers={"content-type": "application/json"},
        )
