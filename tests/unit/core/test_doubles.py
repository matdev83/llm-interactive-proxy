"""
Test doubles (mocks, stubs, fakes) for core interfaces.

This module provides test implementations of interfaces for use in unit tests.
"""

from __future__ import annotations

from collections.abc import Mapping
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
from src.core.domain.processed_result import ProcessedResult
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
from src.core.interfaces.di_interface import (
    IServiceProvider,
    IServiceScope,
)
from src.core.interfaces.domain_entities_interface import ISession
from src.core.interfaces.rate_limiter_interface import IRateLimiter, RateLimitInfo
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
        from src.core.domain.responses import ResponseEnvelope as _ResponseEnvelope

        if hasattr(response, "__aiter__"):
            return response

        if isinstance(response, ChatResponse):
            choices_list = []
            for ch in getattr(response, "choices", []) or []:
                msg = getattr(ch, "message", None)
                msg_dict: dict[str, Any] = {}
                if msg is not None:
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

            return _ResponseEnvelope(
                content=content,
                headers={"content-type": "application/json"},
                status_code=200,
            )

        return response

    async def chat_completions(
        self, request: ChatRequest, **kwargs: Any
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        return await self.call_completion(request, stream=bool(request.stream))

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
            session_id = f"test-session-{len(self.sessions) + 1}"
        return await self.get_session(session_id)

    async def update_session(self, session: ISession) -> None:
        self.sessions[session.session_id] = session  # type: ignore

    async def update_session_backend_config(
        self, session_id: str, backend_type: str, model: str
    ) -> None:
        session = await self.get_session(session_id)
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

    async def resolve_session_id(self, context: RequestContext) -> str:
        return "sess"

    async def update_session_agent(self, session_id: str, agent_name: str) -> None:
        pass

    async def update_session_history(
        self,
        request_data: ChatRequest,
        backend_request: ChatRequest,
        backend_response: ResponseEnvelope | StreamingResponseEnvelope,
        session_id: str,
    ) -> None:
        pass

    async def record_command_in_session(
        self, request_data: ChatRequest, session_id: str
    ) -> None:
        pass


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
# Test Data Builder
#
class TestDataBuilder:
    """Helper for building test data objects."""

    @staticmethod
    def create_session(session_id: str = "test-session") -> Session:
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
        return SessionInteraction(
            prompt=prompt,
            handler="proxy",
            backend="openai",
            model="gpt-4",
            response=response,
        )

    @staticmethod
    def create_chat_request(messages: list[ChatMessage] | None = None) -> ChatRequest:
        if messages is None:
            messages = [ChatMessage(role="user", content="Hello")]
        return ChatRequest(messages=messages, model="gpt-4", stream=False)

    @staticmethod
    def create_chat_response(content: str = "Hello there!") -> ResponseEnvelope:
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
