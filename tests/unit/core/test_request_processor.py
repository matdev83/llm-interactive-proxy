"""
Tests for the RequestProcessor implementation.
"""

from unittest.mock import MagicMock, patch

import pytest
from src.core.common.exceptions import BackendError, LLMProxyError
from src.core.domain.commands import CommandResult
from src.core.domain.processed_result import ProcessedResult
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.session_resolver_interface import ISessionResolver
from src.core.services.request_processor_service import RequestProcessor

from tests.unit.core.test_doubles import (
    MockBackendService,
    MockCommandProcessor,
    MockSessionService,
    TestDataBuilder,
)


class MockState:
    """Mock state for testing."""
    
    def __init__(self) -> None:
        self.project = None
        self.backend_config = MagicMock()
        self.backend_config.backend_type = None
        self.backend_config.model = None
        self.backend_config.failover_routes = {}
        self.disable_commands = False


class MockRequestContext:
    """Mock RequestContext for testing."""

    def __init__(
        self, 
        headers: dict[str, str] | None = None, 
        cookies: dict[str, str] | None = None,
        session_id: str | None = None,
        disable_commands: bool = False,
        disable_interactive_commands: bool = False,
    ) -> None:
        self.headers = headers or {}
        self.cookies = cookies or {}
        self.state = MagicMock()
        self.state.disable_commands = disable_commands
        
        self.app_state = MagicMock()
        self.app_state.force_set_project = False
        self.app_state.disable_interactive_commands = disable_interactive_commands
        self.app_state.failover_routes = {}
        
        self.client_host = "127.0.0.1"
        self.original_request = None
        self.session_id = session_id


class MockRequestData:
    """Mock request data for testing."""

    def __init__(
        self, stream=False, messages=None, model="gpt-4", session_id=None
    ) -> None:
        self.stream = stream
        self.messages = messages or [{"role": "user", "content": "Hello"}]
        self.model = model
        self.temperature = None
        self.top_p = None
        self.max_tokens = None
        self.tools = None
        self.tool_choice = None
        self.user = None
        self.session_id = session_id
        self.extra_body = None


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
        response_processor=MagicMock(),
        session_resolver=session_resolver
    )

    # Create a request context and data
    context = MockRequestContext(headers={"x-session-id": "test-session"})
    request_data = MockRequestData()

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
    assert response_obj.content["id"] == response.id
    assert response_obj.content["choices"][0]["message"]["content"] == "Hello there!"

    # Check that session was retrieved and updated
    assert "test-session" in session_service.sessions
    session = session_service.sessions["test-session"]
    assert len(session.history) == 1
    assert session.history[0].prompt == "Hello"
    assert session.history[0].handler == "backend"


@pytest.mark.asyncio
async def test_process_request_with_commands(session_service: MockSessionService) -> None:
    """Test request processing with commands."""
    # Arrange
    command_service = MockCommandProcessor()
    backend_service = MockBackendService()
    session_resolver = MockSessionResolver("test-session")

    processor = RequestProcessor(
        command_service, 
        backend_service, 
        session_service,
        response_processor=MagicMock(),
        session_resolver=session_resolver
    )

    # Create a request context and data
    context = MockRequestContext(headers={"x-session-id": "test-session"})
    request_data = MockRequestData(
        messages=[{"role": "user", "content": "!/set(project=test) How are you?"}]
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
    session_service.sessions["test-session"].state.project = "test"

    # Setup backend service to return a response
    response = TestDataBuilder.create_chat_response("I'm doing well, thanks!")
    backend_service.add_response(response)

    # Act
    response_obj = await processor.process_request(context, request_data)
    
    # Assert - should be a ResponseEnvelope now
    assert isinstance(response_obj, ResponseEnvelope)
    assert response_obj.content["id"] == response.id
    assert response_obj.content["choices"][0]["message"]["content"] == "I'm doing well, thanks!"

    # Check that session was updated
    assert "test-session" in session_service.sessions
    session = session_service.sessions["test-session"]
    assert len(session.history) == 1
    assert session.history[0].prompt == "!/set(project=test) How are you?"
    assert session.history[0].handler == "backend"


@pytest.mark.asyncio
async def test_process_command_only_request(session_service: MockSessionService) -> None:
    """Test processing a command-only request with no meaningful content."""
    # Arrange
    command_service = MockCommandProcessor()
    backend_service = MockBackendService()
    session_resolver = MockSessionResolver("test-session")

    processor = RequestProcessor(
        command_service, 
        backend_service, 
        session_service,
        response_processor=MagicMock(),
        session_resolver=session_resolver
    )

    # Create a request context and data
    context = MockRequestContext(headers={"x-session-id": "test-session"})
    request_data = MockRequestData(messages=[{"role": "user", "content": "!/hello"}])

    # Setup command service to return command processed with no remaining content
    processed_messages = []
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
        response_processor=MagicMock(),
        session_resolver=session_resolver
    )

    # Create a request context and data
    context = MockRequestContext(headers={"x-session-id": "test-session"})
    request_data = MockRequestData(stream=True)

    # Setup command service to return no commands processed
    command_service.add_result(
        ProcessedResult(
            modified_messages=request_data.messages,
            command_executed=False,
            command_results=[],
        )
    )

    # Setup backend service for streaming
    async def mock_stream_generator():
        yield b"data: {\"choices\":[{\"delta\":{\"content\":\"Hello\"},\"index\":0}]}\n\n"
        yield b"data: {\"choices\":[{\"delta\":{\"content\":\" there!\"},\"index\":0}]}\n\n"
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
        response_processor=MagicMock(),
        session_resolver=session_resolver
    )

    # Create a request context and data
    context = MockRequestContext(headers={"x-session-id": "test-session"})
    request_data = MockRequestData()

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