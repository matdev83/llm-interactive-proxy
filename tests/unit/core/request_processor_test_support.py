"""
Shared helpers for RequestProcessor unit tests.

NOTE: These tests target the refactored RequestProcessor architecture that requires
all component dependencies (SessionEnricher, RequestSideEffects, CommandHandler,
BackendPreparer, RequestTransformPipeline, BackendExecutor).
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.processed_result import ProcessedResult
from src.core.domain.request_context import RequestContext
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.interfaces.domain_entities_interface import ISessionState
from src.core.interfaces.request_processor_internal import (
    IBackendExecutor,
    IBackendPreparer,
    ICommandHandler,
    IRequestSideEffects,
    IRequestTransformPipeline,
    ISessionEnricher,
)
from src.core.interfaces.session_resolver_interface import ISessionResolver

from tests.unit.core.test_doubles import TestDataBuilder


class MockRequestContext(RequestContext):
    """Mock RequestContext for testing."""

    def __init__(
        self,
        headers: dict[str, str] | None = None,
        cookies: dict[str, str] | None = None,
        session_id: str | None = None,
        disable_commands: bool = False,
        disable_interactive_commands: bool = False,
        is_cline_agent: bool = False,
    ) -> None:
        mock_app_state = MagicMock(spec=IApplicationState)
        mock_app_state.force_set_project = False
        mock_app_state.disable_commands = disable_commands
        mock_app_state.disable_interactive_commands = disable_interactive_commands
        mock_app_state.failover_routes = {}
        mock_app_state.is_cline_agent = is_cline_agent

        super().__init__(
            headers=headers or {},
            cookies=cookies or {},
            state=MagicMock(spec=ISessionState),
            app_state=mock_app_state,
            client_host="127.0.0.1",
            original_request=None,
        )
        self.session_id = session_id


def create_mock_request(
    stream: bool = False,
    messages: list[ChatMessage] | None = None,
    model: str = "gpt-4",
    session_id: str | None = None,
) -> ChatRequest:
    """Factory for creating ChatRequest objects for tests."""
    if messages is None:
        messages = [ChatMessage(role="user", content="Hello")]
    return ChatRequest(
        model=model,
        messages=messages,
        stream=stream,
        session_id=session_id,
    )


def create_request_processor_mocks(
    session_manager: Any,
    backend_request_manager: Any,
    response_manager: Any,
    command_processor: Any,
    request_data: ChatRequest | None = None,
) -> tuple[
    ISessionEnricher,
    IRequestSideEffects,
    ICommandHandler,
    IBackendPreparer,
    IRequestTransformPipeline,
    IBackendExecutor,
]:
    """Create mock instances for all required RequestProcessor dependencies."""
    # Mock SessionEnricher
    session_enricher = AsyncMock(spec=ISessionEnricher)
    mock_session = AsyncMock(id="test-session", agent=None)
    session_enricher.enrich.return_value = (
        mock_session,
        request_data or create_mock_request(),
    )

    # Mock RequestSideEffects
    request_side_effects = AsyncMock(spec=IRequestSideEffects)
    request_side_effects.apply.return_value = request_data or create_mock_request()

    # Mock CommandHandler
    command_handler = AsyncMock(spec=ICommandHandler)
    # Default behavior: return ProcessedResult for backend flow
    command_handler.handle.return_value = ProcessedResult(
        modified_messages=(request_data or create_mock_request()).messages,
        command_executed=False,
        command_results=[],
    )

    # Mock BackendPreparer
    backend_preparer = AsyncMock(spec=IBackendPreparer)
    backend_preparer.prepare.return_value = request_data or create_mock_request()

    # Mock RequestTransformPipeline
    transform_pipeline = AsyncMock(spec=IRequestTransformPipeline)
    transform_pipeline.transform.return_value = request_data or create_mock_request()

    # Mock BackendExecutor
    backend_executor = AsyncMock(spec=IBackendExecutor)
    response = TestDataBuilder.create_chat_response("OK")
    backend_executor.execute.return_value = response

    return (
        session_enricher,
        request_side_effects,
        command_handler,
        backend_preparer,
        transform_pipeline,
        backend_executor,
    )


class MockSessionResolver(ISessionResolver):
    """Mock implementation of ISessionResolver that always returns the test session ID."""

    def __init__(self, session_id: str = "test-session") -> None:
        self.session_id = session_id

    async def resolve_session_id(self, context: RequestContext) -> str:
        """Always returns the test session ID."""
        return self.session_id


__all__ = [
    "MockRequestContext",
    "MockSessionResolver",
    "create_mock_request",
    "create_request_processor_mocks",
]
