"""
Tests for the RequestProcessor implementation.
"""

from unittest.mock import AsyncMock, MagicMock

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
    command_processor = MockCommandProcessor()
    session_manager = AsyncMock()
    backend_request_manager = AsyncMock()
    response_manager = AsyncMock()

    # Mock the session manager to return our test session
    session_manager.resolve_session_id.return_value = "test-session"
    session_manager.get_session.return_value = AsyncMock(id="test-session", agent=None)

    processor = RequestProcessor(
        command_processor,
        session_manager,
        backend_request_manager,
        response_manager,
    )

    # Create a request context and data
    context = MockRequestContext(headers={"x-session-id": "test-session"})
    request_data = create_mock_request()

    # Setup command processor to return no commands processed
    command_processor.add_result(
        ProcessedResult(
            modified_messages=request_data.messages,
            command_executed=False,
            command_results=[],
        )
    )

    # Setup backend request manager to return a response
    response = TestDataBuilder.create_chat_response("Hello there!")
    backend_request_manager.prepare_backend_request.return_value = request_data
    backend_request_manager.process_backend_request.return_value = response

    # Setup response manager to return the response
    response_manager.process_command_result.return_value = response

    # Act
    response_obj = await processor.process_request(context, request_data)

    # Assert - should be a ResponseEnvelope now
    assert isinstance(response_obj, ResponseEnvelope)
    assert response_obj.content["id"] == response.content["id"]
    assert response_obj.content["choices"][0]["message"]["content"] == "Hello there!"

    # Check that session manager methods were called
    session_manager.resolve_session_id.assert_called_once_with(context)
    session_manager.get_session.assert_called_once_with("test-session")
    session_manager.update_session_agent.assert_called_once()
    session_manager.update_session_history.assert_called_once()


@pytest.mark.asyncio
async def test_request_processor_applies_edit_precision_overrides_for_failed_edit_prompt() -> (
    None
):
    """Ensure edit-precision middleware lowers temperature/top_p for a single request when detection triggers."""
    # Arrange
    command_processor = MockCommandProcessor()
    session_manager = AsyncMock()
    backend_request_manager = AsyncMock()
    response_manager = AsyncMock()

    # Mock the session manager to return our test session (no special agent)
    session = AsyncMock(id="test-session", agent="someagent")
    session_manager.resolve_session_id.return_value = "test-session"
    session_manager.get_session.return_value = session

    # Provide AppConfig with edit_precision enabled and strict values
    from unittest.mock import MagicMock

    from src.core.config.app_config import AppConfig
    from src.core.interfaces.application_state_interface import IApplicationState

    app_config = AppConfig()
    app_config.edit_precision.enabled = True
    app_config.edit_precision.temperature = 0.05
    app_config.edit_precision.min_top_p = 0.2
    app_config.edit_precision.override_top_p = True

    mock_app_state = MagicMock(spec=IApplicationState)
    mock_app_state.get_setting.return_value = app_config

    processor = RequestProcessor(
        command_processor,
        session_manager,
        backend_request_manager,
        response_manager,
        app_state=mock_app_state,
    )

    # Create a request whose content includes a known failure phrase
    failure_text = "The SEARCH block ... does not match anything in the file"
    request_data = create_mock_request(
        stream=True, messages=[ChatMessage(role="user", content=failure_text)]
    )

    # No additional command modifications
    command_processor.add_result(
        ProcessedResult(
            modified_messages=request_data.messages,
            command_executed=False,
            command_results=[],
        )
    )

    # Backend manager returns same request on prepare and a dummy response on process
    response = TestDataBuilder.create_chat_response("OK")
    backend_request_manager.prepare_backend_request.return_value = request_data
    backend_request_manager.process_backend_request.return_value = response

    # Act
    await processor.process_request(MockRequestContext(), request_data)

    # Assert: backend was called once with lowered sampling params
    # For GPT models, the config sets temperature to 0.2
    assert backend_request_manager.process_backend_request.called
    sent_request = backend_request_manager.process_backend_request.call_args[0][0]
    assert sent_request.temperature == pytest.approx(0.2)
    assert sent_request.top_p == pytest.approx(0.2)


@pytest.mark.asyncio
async def test_request_processor_respects_exclude_agents_regex() -> None:
    """Ensure exclusion regex disables precision overrides for matching agents."""
    # Arrange
    command_processor = MockCommandProcessor()
    session_manager = AsyncMock()
    backend_request_manager = AsyncMock()
    response_manager = AsyncMock()

    # Session agent matches exclusion
    session = AsyncMock(id="test-session", agent="cline")
    session_manager.resolve_session_id.return_value = "test-session"
    session_manager.get_session.return_value = session
    # Ensure update_session_agent preserves the agent value
    session_manager.update_session_agent.return_value = session

    from unittest.mock import MagicMock

    from src.core.config.app_config import AppConfig
    from src.core.interfaces.application_state_interface import IApplicationState

    app_config = AppConfig()
    app_config.edit_precision.enabled = True
    app_config.edit_precision.temperature = 0.05
    app_config.edit_precision.min_top_p = 0.2
    app_config.edit_precision.exclude_agents_regex = r"^(cline|roocode)$"

    mock_app_state = MagicMock(spec=IApplicationState)
    mock_app_state.get_setting.return_value = app_config

    processor = RequestProcessor(
        command_processor,
        session_manager,
        backend_request_manager,
        response_manager,
        app_state=mock_app_state,
    )

    # Request includes failure phrase but should be excluded due to agent
    failure_text = "UnifiedDiffNoMatch: hunk failed to apply"
    # Seed with explicit starting values to ensure they remain unchanged
    request_data = ChatRequest(
        model="gpt-4",
        messages=[ChatMessage(role="user", content=failure_text)],
        temperature=0.9,
        top_p=0.9,
        agent="cline",
    )

    command_processor.add_result(
        ProcessedResult(
            modified_messages=request_data.messages,
            command_executed=False,
            command_results=[],
        )
    )

    response = TestDataBuilder.create_chat_response("OK")
    backend_request_manager.prepare_backend_request.return_value = request_data
    backend_request_manager.process_backend_request.return_value = response

    # Act
    await processor.process_request(MockRequestContext(), request_data)

    # Assert: params unchanged due to exclusion
    assert backend_request_manager.process_backend_request.called
    sent_request = backend_request_manager.process_backend_request.call_args[0][0]
    assert sent_request.temperature == pytest.approx(0.9)
    assert sent_request.top_p == pytest.approx(0.9)


@pytest.mark.asyncio
async def test_request_processor_applies_overrides_when_pending_flag_set() -> None:
    """If response-side detection flagged a pending precision tune, the next request should be tuned even without prompt triggers."""
    # Arrange
    command_processor = MockCommandProcessor()
    session_manager = AsyncMock()
    backend_request_manager = AsyncMock()
    response_manager = AsyncMock()

    # Mock session
    session = AsyncMock(id="test-session", agent="someagent")
    session_manager.resolve_session_id.return_value = "test-session"
    session_manager.get_session.return_value = session

    from unittest.mock import MagicMock

    from src.core.config.app_config import AppConfig
    from src.core.interfaces.application_state_interface import IApplicationState

    app_config = AppConfig()
    app_config.edit_precision.enabled = True
    app_config.edit_precision.temperature = 0.2
    app_config.edit_precision.min_top_p = 0.4
    app_config.edit_precision.override_top_p = True

    # Build a mock app_state that returns app_config and a pending flag map
    pending_map = {"test-session": 1}

    def _get_setting(name: str, default: object | None = None) -> object | None:
        if name == "app_config":
            return app_config
        if name == "edit_precision_pending":
            return pending_map
        return default

    mock_app_state = MagicMock(spec=IApplicationState)
    mock_app_state.get_setting.side_effect = _get_setting

    processor = RequestProcessor(
        command_processor,
        session_manager,
        backend_request_manager,
        response_manager,
        app_state=mock_app_state,
    )

    # No failure phrase in message; tuning should still be applied due to pending flag
    request_data = create_mock_request(
        stream=False,
        messages=[ChatMessage(role="user", content="Proceed with next step")],
    )

    command_processor.add_result(
        ProcessedResult(
            modified_messages=request_data.messages,
            command_executed=False,
            command_results=[],
        )
    )

    response = TestDataBuilder.create_chat_response("OK")
    backend_request_manager.prepare_backend_request.return_value = request_data
    backend_request_manager.process_backend_request.return_value = response

    # Act
    await processor.process_request(MockRequestContext(), request_data)

    # Assert request was tuned
    assert backend_request_manager.process_backend_request.called
    sent_request = backend_request_manager.process_backend_request.call_args[0][0]
    assert sent_request.temperature == pytest.approx(0.2)
    assert sent_request.top_p == pytest.approx(0.4)


@pytest.mark.asyncio
async def test_request_processor_applies_redaction_before_backend_call(
    session_service: MockSessionService,
) -> None:
    """Ensure API key redaction and command filtering are applied to outbound request."""
    # Arrange
    command_processor = MockCommandProcessor()
    session_manager = AsyncMock()
    backend_request_manager = AsyncMock()
    response_manager = AsyncMock()

    # Mock the session manager to return our test session
    session_manager.resolve_session_id.return_value = "test-session"
    session_manager.get_session.return_value = AsyncMock(id="test-session", agent=None)

    # Provide an AppConfig via IApplicationState so redaction discovers API keys
    from unittest.mock import MagicMock

    from src.core.config.app_config import AppConfig
    from src.core.interfaces.application_state_interface import IApplicationState

    app_config = AppConfig()
    # Enable redaction and provide a known API key
    app_config.auth.redact_api_keys_in_prompts = True
    app_config.auth.api_keys = ["SECRET_API_KEY_123"]

    mock_app_state = MagicMock(spec=IApplicationState)
    # get_setting("app_config") should return our config
    mock_app_state.get_setting.return_value = app_config

    processor = RequestProcessor(
        command_processor,
        session_manager,
        backend_request_manager,
        response_manager,
        app_state=mock_app_state,
    )

    # Create a request containing both a secret and a proxy command
    original_text = "Please use SECRET_API_KEY_123 and !/hello to proceed"
    context = MockRequestContext(headers={"x-session-id": "test-session"})
    request_data = create_mock_request(
        messages=[ChatMessage(role="user", content=original_text)]
    )

    # Setup command processor to return no additional modifications
    command_processor.add_result(
        ProcessedResult(
            modified_messages=request_data.messages,
            command_executed=False,
            command_results=[],
        )
    )

    # Backend manager returns a trivial response
    response = TestDataBuilder.create_chat_response("OK")
    backend_request_manager.prepare_backend_request.return_value = request_data
    backend_request_manager.process_backend_request.return_value = response

    # Act
    await processor.process_request(context, request_data)

    # Assert that the request passed to the backend has been redacted and filtered
    assert backend_request_manager.process_backend_request.called
    called_args, _called_kwargs = (
        backend_request_manager.process_backend_request.call_args
    )
    # First positional arg is the redacted ChatRequest
    redacted_request: ChatRequest = called_args[0]
    assert isinstance(redacted_request, ChatRequest)
    # Extract user content
    redacted_content = next(
        (m.content for m in redacted_request.messages if m.role == "user"),
        "",
    )
    # API key should be replaced
    assert "SECRET_API_KEY_123" not in redacted_content
    assert "(API_KEY_HAS_BEEN_REDACTED)" in redacted_content
    # Proxy command should be removed
    assert "!/hello" not in redacted_content


@pytest.mark.asyncio
async def test_request_processor_redacts_command_modified_messages(
    session_service: MockSessionService,
) -> None:
    """Ensure redaction applies when commands modify messages before backend call."""
    # Arrange
    command_processor = MockCommandProcessor()
    session_manager = AsyncMock()
    backend_request_manager = AsyncMock()
    response_manager = AsyncMock()

    session_manager.resolve_session_id.return_value = "test-session"
    session_manager.get_session.return_value = AsyncMock(id="test-session", agent=None)

    from unittest.mock import MagicMock

    from src.core.config.app_config import AppConfig
    from src.core.interfaces.application_state_interface import IApplicationState

    app_config = AppConfig()
    app_config.auth.redact_api_keys_in_prompts = True
    app_config.auth.api_keys = ["ANOTHER_SECRET_KEY_456"]

    mock_app_state = MagicMock(spec=IApplicationState)
    mock_app_state.get_setting.return_value = app_config

    processor = RequestProcessor(
        command_processor,
        session_manager,
        backend_request_manager,
        response_manager,
        app_state=mock_app_state,
    )

    # Request starts with a command; command processing leaves behind text that includes secret and a command
    context = MockRequestContext(headers={"x-session-id": "test-session"})
    original = create_mock_request(
        messages=[ChatMessage(role="user", content="!/set(project=x)")]
    )

    modified_messages = [
        ChatMessage(
            role="user", content="Please use ANOTHER_SECRET_KEY_456 and !/hello"
        )
    ]
    command_processor.add_result(
        ProcessedResult(
            modified_messages=modified_messages,
            command_executed=True,
            command_results=[],
        )
    )

    # Create a request with the modified messages that contains the secret
    modified_request = create_mock_request(messages=modified_messages)

    response = TestDataBuilder.create_chat_response("OK")
    backend_request_manager.prepare_backend_request.return_value = modified_request
    backend_request_manager.process_backend_request.return_value = response

    # Act
    await processor.process_request(context, original)

    # Assert
    assert backend_request_manager.process_backend_request.called
    redacted_request: ChatRequest = (
        backend_request_manager.process_backend_request.call_args[0][0]
    )
    text = next((m.content for m in redacted_request.messages if m.role == "user"), "")
    assert "ANOTHER_SECRET_KEY_456" not in text
    assert "(API_KEY_HAS_BEEN_REDACTED)" in text
    assert "!/hello" not in text


@pytest.mark.asyncio
async def test_request_processor_respects_redaction_feature_flag_disabled(
    session_service: MockSessionService,
) -> None:
    """When redaction flag is disabled, processor should not alter content."""
    # Arrange
    command_processor = MockCommandProcessor()
    session_manager = AsyncMock()
    backend_request_manager = AsyncMock()
    response_manager = AsyncMock()

    session_manager.resolve_session_id.return_value = "test-session"
    session_manager.get_session.return_value = AsyncMock(id="test-session", agent=None)

    from unittest.mock import MagicMock

    from src.core.config.app_config import AppConfig
    from src.core.interfaces.application_state_interface import IApplicationState

    app_config = AppConfig()
    app_config.auth.redact_api_keys_in_prompts = False  # disabled
    app_config.auth.api_keys = ["NO_REDACT_789"]

    mock_app_state = MagicMock(spec=IApplicationState)
    mock_app_state.get_setting.return_value = app_config

    processor = RequestProcessor(
        command_processor,
        session_manager,
        backend_request_manager,
        response_manager,
        app_state=mock_app_state,
    )

    context = MockRequestContext(headers={"x-session-id": "test-session"})
    text = "Keep NO_REDACT_789 and !/hello"
    request_data = create_mock_request(
        messages=[ChatMessage(role="user", content=text)]
    )

    command_processor.add_result(
        ProcessedResult(
            modified_messages=request_data.messages,
            command_executed=False,
            command_results=[],
        )
    )

    response = TestDataBuilder.create_chat_response("OK")
    backend_request_manager.prepare_backend_request.return_value = request_data
    backend_request_manager.process_backend_request.return_value = response

    # Act
    await processor.process_request(context, request_data)

    # Assert: content passed to backend should be unchanged when flag is disabled
    redacted_request: ChatRequest = (
        backend_request_manager.process_backend_request.call_args[0][0]
    )
    out_text = next(
        (m.content for m in redacted_request.messages if m.role == "user"), ""
    )
    assert out_text == text


@pytest.mark.asyncio
async def test_process_request_with_commands(
    session_service: MockSessionService,
) -> None:
    """Test request processing with commands."""
    # Arrange
    command_processor = MockCommandProcessor()
    session_manager = AsyncMock()
    backend_request_manager = AsyncMock()
    response_manager = AsyncMock()

    # Mock the session manager to return our test session
    session_manager.resolve_session_id.return_value = "test-session"
    session_manager.get_session.return_value = AsyncMock(id="test-session", agent=None)

    processor = RequestProcessor(
        command_processor,
        session_manager,
        backend_request_manager,
        response_manager,
    )

    # Create a request context and data
    context = MockRequestContext(headers={"x-session-id": "test-session"})
    request_data = create_mock_request(
        messages=[ChatMessage(role="user", content="!/set(project=test) How are you?")]
    )

    # Setup command processor to return command processed with remaining content
    processed_messages = [{"role": "user", "content": " How are you?"}]
    command_processor.add_result(
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

    # Setup backend request manager to return a response
    response = TestDataBuilder.create_chat_response("I'm doing well, thanks!")
    backend_request_manager.prepare_backend_request.return_value = request_data
    backend_request_manager.process_backend_request.return_value = response

    # Setup response manager to return the response
    response_manager.process_command_result.return_value = response

    # Act
    response_obj = await processor.process_request(context, request_data)

    # Assert - should be a ResponseEnvelope now
    assert isinstance(response_obj, ResponseEnvelope)
    assert response_obj.content["id"] == response.content["id"]
    assert (
        response_obj.content["choices"][0]["message"]["content"]
        == "I'm doing well, thanks!"
    )

    # Check that session manager methods were called
    session_manager.resolve_session_id.assert_called_once_with(context)
    session_manager.get_session.assert_called_once_with("test-session")
    session_manager.update_session_agent.assert_called_once()
    session_manager.update_session_history.assert_called_once()


@pytest.mark.asyncio
async def test_process_command_only_request(
    session_service: MockSessionService,
) -> None:
    """Test processing a command-only request with no meaningful content."""
    # Arrange
    command_processor = MockCommandProcessor()
    session_manager = AsyncMock()
    backend_request_manager = AsyncMock()
    response_manager = AsyncMock()

    # Mock the session manager to return our test session
    session_manager.resolve_session_id.return_value = "test-session"
    session_manager.get_session.return_value = AsyncMock(id="test-session", agent=None)

    processor = RequestProcessor(
        command_processor,
        session_manager,
        backend_request_manager,
        response_manager,
    )

    # Create a request context and data
    context = MockRequestContext(headers={"x-session-id": "test-session"})
    request_data = create_mock_request(
        messages=[ChatMessage(role="user", content="!/hello")]
    )

    # Setup command service to return command processed with no remaining content
    processed_messages: list[dict[str, Any]] = []
    command_processor.add_result(
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
    backend_request_manager.prepare_backend_request.return_value = request_data
    backend_request_manager.process_backend_request.return_value = response
    response_manager.process_command_result.return_value = response

    # Act
    response_obj = await processor.process_request(context, request_data)

    # Assert - should be a ResponseEnvelope now
    assert isinstance(response_obj, ResponseEnvelope)
    # This mock is using a different ID but we just need to make sure it's a valid response
    assert "id" in response_obj.content

    # Check that session manager methods were called
    session_manager.resolve_session_id.assert_called_once_with(context)
    session_manager.get_session.assert_called_once_with("test-session")
    session_manager.update_session_agent.assert_called_once()
    # record_command_in_session may or may not be called depending on the exact command result structure


@pytest.mark.asyncio
async def test_process_streaming_request(session_service: MockSessionService) -> None:
    """Test processing a streaming request."""
    # Arrange
    command_processor = MockCommandProcessor()
    session_manager = AsyncMock()
    backend_request_manager = AsyncMock()
    response_manager = AsyncMock()

    # Mock the session manager to return our test session
    session_manager.resolve_session_id.return_value = "test-session"
    session_manager.get_session.return_value = AsyncMock(id="test-session", agent=None)

    processor = RequestProcessor(
        command_processor,
        session_manager,
        backend_request_manager,
        response_manager,
    )

    # Create a request context and data
    context = MockRequestContext(headers={"x-session-id": "test-session"})
    request_data = create_mock_request(stream=True)

    # Setup command service to return no commands processed
    command_processor.add_result(
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

    backend_request_manager.prepare_backend_request.return_value = request_data
    backend_request_manager.process_backend_request.return_value = streaming_envelope

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
    command_processor = MockCommandProcessor()
    session_manager = AsyncMock()
    backend_request_manager = AsyncMock()
    response_manager = AsyncMock()

    # Mock the session manager to return our test session
    session_manager.resolve_session_id.return_value = "test-session"
    session_manager.get_session.return_value = AsyncMock(id="test-session", agent=None)

    processor = RequestProcessor(
        command_processor,
        session_manager,
        backend_request_manager,
        response_manager,
    )

    # Create a request context and data
    context = MockRequestContext(headers={"x-session-id": "test-session"})
    request_data = create_mock_request()

    # Setup command service to return no commands processed
    command_processor.add_result(
        ProcessedResult(
            modified_messages=request_data.messages,
            command_executed=False,
            command_results=[],
        )
    )

    # Setup backend request manager to throw an error
    backend_error = BackendError("API unavailable")
    backend_request_manager.prepare_backend_request.return_value = request_data
    backend_request_manager.process_backend_request.side_effect = backend_error

    # Act & Assert
    with pytest.raises(LLMProxyError) as exc:
        await processor.process_request(context, request_data)

    assert "API unavailable" in str(exc.value.message)


import pytest

pytestmark = pytest.mark.filterwarnings(
    "ignore:unclosed event loop <ProactorEventLoop.*:ResourceWarning"
)
