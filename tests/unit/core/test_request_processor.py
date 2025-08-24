"""
Tests for the RequestProcessor implementation.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from src.core.common.exceptions import BackendError, LLMProxyError
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.commands import CommandResult
from src.core.domain.processed_result import ProcessedResult
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.interfaces.domain_entities_interface import ISessionState
from src.core.interfaces.session_resolver_interface import ISessionResolver
from src.core.services.request_processor_service import RequestProcessor

from tests.unit.core.test_doubles import (
    MockBackendService,
    MockCommandProcessor,
    MockSessionService,
    TestDataBuilder,
)


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


from collections.abc import AsyncGenerator
from typing import Any


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


@pytest.fixture
def session_service() -> MockSessionService:
    return MockSessionService()


class MockSessionResolver(ISessionResolver):
    """Mock implementation of ISessionResolver that always returns the test session ID."""

    def __init__(self, session_id: str = "test-session") -> None:
        self.session_id = session_id

    async def resolve_session_id(self, context: RequestContext) -> str:
        """Always returns the test session ID."""
        return self.session_id


@pytest.mark.asyncio
async def test_process_request_basic(session_service: MockSessionService) -> None:
    """Test basic request processing with no commands."""
    # Arrange
    command_service = MockCommandProcessor()
    backend_service = MockBackendService()
    session_resolver = MockSessionResolver("test-session")

    processor = RequestProcessor(
        command_service,
        backend_service,
        session_service,
        response_processor=AsyncMock(),
        session_resolver=session_resolver,
    )

    # Create a request context and data
    context = MockRequestContext(headers={"x-session-id": "test-session"})
    request_data = create_mock_request()

    # Setup command service to return no commands processed
    command_service.add_result(
        ProcessedResult(
            modified_messages=request_data.messages,
            command_executed=False,
            command_results=[],
        )
    )

    # Setup backend service to return a response
    response = TestDataBuilder.create_chat_response("Hello there!")
    backend_service.add_response(response)

    # Act
    response_obj = await processor.process_request(context, request_data)

    # Assert - should be a ResponseEnvelope now
    assert isinstance(response_obj, ResponseEnvelope)
    assert response_obj.content["id"] == response.content["id"]
    assert response_obj.content["choices"][0]["message"]["content"] == "Hello there!"

    # Check that session was retrieved and updated
    assert "test-session" in session_service.sessions
    session = session_service.sessions["test-session"]
    assert len(session.history) == 1
    assert session.history[0].prompt == "Hello"
    assert session.history[0].handler == "backend"


@pytest.mark.asyncio
async def test_process_request_with_commands(
    session_service: MockSessionService,
) -> None:
    """Test request processing with commands."""
    # Arrange
    command_service = MockCommandProcessor()
    backend_service = MockBackendService()
    session_resolver = MockSessionResolver("test-session")

    processor = RequestProcessor(
        command_service,
        backend_service,
        session_service,
        response_processor=AsyncMock(),
        session_resolver=session_resolver,
    )

    # Create a request context and data
    context = MockRequestContext(headers={"x-session-id": "test-session"})
    request_data = create_mock_request(
        messages=[ChatMessage(role="user", content="!/set(project=test) How are you?")]
    )

    # Setup command service to return command processed with remaining content
    processed_messages = [{"role": "user", "content": " How are you?"}]
    command_service.add_result(
        ProcessedResult(
            modified_messages=processed_messages,
            command_executed=True,
            command_results=[
                CommandResult(
                    success=True, message="Project set to test", data={"name": "set"}
                )
            ],
        )
    )

    # Mock the session service to return a session with project set
    session = await session_service.get_session("test-session")
    # Mock the state property to return a value with project set
    new_state = session.state.with_project("test")
    session.state = new_state
    session_service.sessions["test-session"] = session

    # Setup backend service to return a response
    response = TestDataBuilder.create_chat_response("I'm doing well, thanks!")
    backend_service.add_response(response)

    # Act
    response_obj = await processor.process_request(context, request_data)

    # Assert - should be a ResponseEnvelope now
    assert isinstance(response_obj, ResponseEnvelope)
    assert response_obj.content["id"] == response.content["id"]
    assert (
        response_obj.content["choices"][0]["message"]["content"]
        == "I'm doing well, thanks!"
    )

    # Check that session was updated
    assert "test-session" in session_service.sessions
    session = session_service.sessions["test-session"]
    assert len(session.history) == 1
    assert session.history[0].prompt == "!/set(project=test) How are you?"
    assert session.history[0].handler == "backend"


@pytest.mark.asyncio
async def test_process_command_only_request(
    session_service: MockSessionService,
) -> None:
    """Test processing a command-only request with no meaningful content."""
    # Arrange
    command_service = MockCommandProcessor()
    backend_service = MockBackendService()
    session_resolver = MockSessionResolver("test-session")

    processor = RequestProcessor(
        command_service,
        backend_service,
        session_service,
        response_processor=AsyncMock(),
        session_resolver=session_resolver,
    )

    # Create a request context and data
    context = MockRequestContext(headers={"x-session-id": "test-session"})
    request_data = create_mock_request(
        messages=[ChatMessage(role="user", content="!/hello")]
    )

    # Setup command service to return command processed with no remaining content
    processed_messages: list[dict[str, Any]] = []
    command_service.add_result(
        ProcessedResult(
            modified_messages=processed_messages,
            command_executed=True,
            command_results=[
                CommandResult(
                    success=True, message="Hello acknowledged", data={"name": "hello"}
                )
            ],
        )
    )

    # Add a response to the mock backend service
    response = TestDataBuilder.create_chat_response("Hello acknowledged")
    backend_service.add_response(response)

    # Act
    response_obj = await processor.process_request(context, request_data)

    # Assert - should be a ResponseEnvelope now
    assert isinstance(response_obj, ResponseEnvelope)
    assert response_obj.content["id"] == "proxy_cmd_processed"

    # Check that session was updated
    assert "test-session" in session_service.sessions
    session = session_service.sessions["test-session"]
    assert len(session.history) == 1
    assert session.history[0].prompt == "!/hello"
    assert session.history[0].handler == "proxy"


@pytest.mark.asyncio
async def test_process_streaming_request(session_service: MockSessionService) -> None:
    """Test processing a streaming request."""
    # Arrange
    command_service = MockCommandProcessor()
    backend_service = MockBackendService()
    session_resolver = MockSessionResolver("test-session")

    processor = RequestProcessor(
        command_service,
        backend_service,
        session_service,
        response_processor=AsyncMock(),
        session_resolver=session_resolver,
    )

    # Create a request context and data
    context = MockRequestContext(headers={"x-session-id": "test-session"})
    request_data = create_mock_request(stream=True)

    # Setup command service to return no commands processed
    command_service.add_result(
        ProcessedResult(
            modified_messages=request_data.messages,
            command_executed=False,
            command_results=[],
        )
    )

    # Setup backend service for streaming
    async def mock_stream_generator() -> AsyncGenerator[bytes, None]:
        yield b'data: {"choices":[{"delta":{"content":"Hello"},"index":0}]}\n\n'
        yield b'data: {"choices":[{"delta":{"content":" there!"},"index":0}]}\n\n'
        yield b"data: [DONE]\n\n"

    # Create StreamingResponseEnvelope to return
    streaming_envelope = StreamingResponseEnvelope(
        content=mock_stream_generator(),
        media_type="text/event-stream",
    )

    with patch.object(
        backend_service, "call_completion", return_value=streaming_envelope
    ):
        # Act
        response = await processor.process_request(context, request_data)

        # Assert
        assert isinstance(response, StreamingResponseEnvelope)
        assert response.media_type == "text/event-stream"

        # Collect the streamed chunks
        chunks = []
        async for chunk in response.content:
            chunks.append(chunk.decode("utf-8"))

        # Check the streamed content
        assert len(chunks) == 3  # 2 content chunks + [DONE]
        assert "Hello" in chunks[0]
        assert "there!" in chunks[1]
        assert chunks[2] == "data: [DONE]\n\n"


@pytest.mark.asyncio
async def test_backend_error_handling(session_service: MockSessionService) -> None:
    """Test handling of backend errors."""
    # Arrange
    command_service = MockCommandProcessor()
    backend_service = MockBackendService()
    session_resolver = MockSessionResolver("test-session")

    processor = RequestProcessor(
        command_service,
        backend_service,
        session_service,
        response_processor=AsyncMock(),
        session_resolver=session_resolver,
    )

    # Create a request context and data
    context = MockRequestContext(headers={"x-session-id": "test-session"})
    request_data = create_mock_request()

    # Setup command service to return no commands processed
    command_service.add_result(
        ProcessedResult(
            modified_messages=request_data.messages,
            command_executed=False,
            command_results=[],
        )
    )

    # Setup backend service to throw an error
    backend_error = BackendError("API unavailable")
    backend_service.add_response(backend_error)

    # Act & Assert
    with pytest.raises(LLMProxyError) as exc:
        await processor.process_request(context, request_data)

    assert "API unavailable" in str(exc.value.message)
