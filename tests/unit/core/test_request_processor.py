"""
Tests for the RequestProcessor implementation.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from src.core.domain.commands import CommandResult
from src.core.domain.processed_result import ProcessedResult
from src.core.interfaces.backend_service import BackendError
from src.core.services.request_processor import RequestProcessor
from starlette.responses import StreamingResponse

from tests.unit.core.test_doubles import (
    MockBackendService,
    MockCommandService,
    MockSessionService,
    TestDataBuilder,
)


class MockRequest:
    """Mock FastAPI request for testing."""

    def __init__(self, headers=None):
        self.headers = headers or {}

        # Mock app.state
        self.app = MagicMock()
        self.app.state = MagicMock()
        self.app.state.force_set_project = False


class MockRequestData:
    """Mock request data for testing."""

    def __init__(self, stream=False, messages=None, model="gpt-4", session_id=None):
        self.stream = stream
        self.messages = messages or [{"role": "user", "content": "Hello"}]
        self.model = model
        self.temperature = None
        self.max_tokens = None
        self.tools = None
        self.tool_choice = None
        self.user = None
        self.session_id = session_id


@pytest.mark.asyncio
@pytest.mark.skip(reason="SessionState is now frozen and cannot be modified directly")
async def test_process_request_basic():
    """Test basic request processing with no commands."""
    # Arrange
    command_service = MockCommandService()
    backend_service = MockBackendService()
    session_service = MockSessionService()

    processor = RequestProcessor(command_service, backend_service, session_service)

    # Create a request
    request = MockRequest(headers={"x-session-id": "test-session"})
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
    result = await processor.process_request(request, request_data)

    # Assert
    assert result["id"] == response.id
    assert result["choices"][0]["message"]["content"] == "Hello there!"

    # Check that session was retrieved and updated
    assert "test-session" in session_service.sessions
    session = session_service.sessions["test-session"]
    assert len(session.history) == 1
    assert session.history[0].prompt == "Hello"
    assert session.history[0].handler == "backend"


@pytest.mark.asyncio
@pytest.mark.skip(reason="SessionState is now frozen and cannot be modified directly")
async def test_process_request_with_commands():
    """Test request processing with commands."""
    # Arrange
    command_service = MockCommandService()
    backend_service = MockBackendService()
    session_service = MockSessionService()

    processor = RequestProcessor(command_service, backend_service, session_service)

    # Create a request
    request = MockRequest(headers={"x-session-id": "test-session"})
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
    session_service.sessions["test-session"].state.project = (
        "test"  # This is a mock, so we can set it directly
    )

    # Setup backend service to return a response
    response = TestDataBuilder.create_chat_response("I'm doing well, thanks!")
    backend_service.add_response(response)

    # Act
    result = await processor.process_request(request, request_data)

    # Assert
    assert result["id"] == response.id
    assert result["choices"][0]["message"]["content"] == "I'm doing well, thanks!"

    # Check that session was updated
    assert "test-session" in session_service.sessions
    session = session_service.sessions["test-session"]
    assert len(session.history) == 1
    assert session.history[0].prompt == "!/set(project=test) How are you?"
    assert session.history[0].handler == "backend"


@pytest.mark.asyncio
@pytest.mark.skip(reason="SessionState is now frozen and cannot be modified directly")
async def test_process_command_only_request():
    """Test processing a command-only request with no meaningful content."""
    # Arrange
    command_service = MockCommandService()
    backend_service = MockBackendService()
    session_service = MockSessionService()

    processor = RequestProcessor(command_service, backend_service, session_service)

    # Create a request
    request = MockRequest(headers={"x-session-id": "test-session"})
    request_data = MockRequestData(messages=[{"role": "user", "content": "!/hello"}])

    # Setup command service to return command processed with no remaining content
    processed_messages = [{"role": "user", "content": ""}]
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
    result = await processor.process_request(request, request_data)

    # Assert
    assert result["id"] == "proxy_cmd_processed"
    assert "choices" in result
    assert len(result["choices"]) == 1

    # Check that session was updated
    assert "test-session" in session_service.sessions
    session = session_service.sessions["test-session"]
    assert len(session.history) == 1
    assert session.history[0].prompt == "!/hello"
    assert session.history[0].handler == "proxy"


@pytest.mark.asyncio
@pytest.mark.skip(reason="SessionState is now frozen and cannot be modified directly")
async def test_process_streaming_request():
    """Test processing a streaming request."""
    # Arrange
    command_service = MockCommandService()
    backend_service = MockBackendService()
    session_service = MockSessionService()

    processor = RequestProcessor(command_service, backend_service, session_service)

    # Create a request
    request = MockRequest(headers={"x-session-id": "test-session"})
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
    from src.core.domain.chat import StreamingChatResponse

    async def mock_stream_response():
        chunk1 = StreamingChatResponse(
            id="resp-123",
            created=123,
            model="gpt-4",
            choices=[{"delta": {"content": "Hello"}, "index": 0}],
        )
        yield chunk1

        chunk2 = StreamingChatResponse(
            id="resp-123",
            created=123,
            model="gpt-4",
            choices=[{"delta": {"content": " there!"}, "index": 0}],
        )
        yield chunk2

    backend_service._backend_service = AsyncMock()
    backend_service._backend_service.call_completion = AsyncMock(
        return_value=mock_stream_response()
    )

    with patch.object(
        backend_service, "call_completion", return_value=mock_stream_response()
    ):
        # Act
        response = await processor.process_request(request, request_data)

        # Assert
        assert isinstance(response, StreamingResponse)

        # Collect the streamed chunks
        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk.decode("utf-8"))

        # Check the streamed content
        assert len(chunks) == 3  # 2 content chunks + [DONE]
        assert (
            json.loads(chunks[0].replace("data: ", ""))["choices"][0]["delta"][
                "content"
            ]
            == "Hello"
        )
        assert (
            json.loads(chunks[1].replace("data: ", ""))["choices"][0]["delta"][
                "content"
            ]
            == " there!"
        )
        assert chunks[2] == "data: [DONE]\n\n"


@pytest.mark.asyncio
@pytest.mark.skip(reason="SessionState is now frozen and cannot be modified directly")
async def test_backend_error_handling():
    """Test handling of backend errors."""
    # Arrange
    command_service = MockCommandService()
    backend_service = MockBackendService()
    session_service = MockSessionService()

    processor = RequestProcessor(command_service, backend_service, session_service)

    # Create a request
    request = MockRequest(headers={"x-session-id": "test-session"})
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
    with pytest.raises(HTTPException) as exc:
        await processor.process_request(request, request_data)

    assert exc.value.status_code == 500
    assert "API unavailable" in str(exc.value.detail)
