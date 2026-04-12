"""Commands, streaming, model defaults, and error paths for RequestProcessor."""

from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.common.exceptions import BackendError, LLMProxyError
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.commands import CommandResult
from src.core.domain.processed_result import ProcessedResult
from src.core.domain.responses import (
    ProcessedResponse,
    ResponseEnvelope,
    StreamingResponseEnvelope,
)
from src.core.domain.session import Session
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.services.request_processor_service import RequestProcessor

from tests.unit.core.request_processor_test_support import (
    MockRequestContext,
    create_mock_request,
    create_request_processor_mocks,
)
from tests.unit.core.test_doubles import (
    MockCommandProcessor,
    MockSessionService,
    TestDataBuilder,
)


@pytest.mark.asyncio
async def test_request_processor_handles_plain_dict_model_defaults() -> None:
    """Ensure model default lookup accepts plain dictionaries without errors."""
    command_processor = MockCommandProcessor()
    session_manager = AsyncMock()
    backend_request_manager = AsyncMock()
    response_manager = AsyncMock()

    session = AsyncMock(id="test-session", agent=None)
    session_manager.resolve_session_id.return_value = "test-session"
    session_manager.get_session.return_value = session
    session_manager.update_session_agent.return_value = session

    request_data = create_mock_request(
        messages=[ChatMessage(role="user", content="Hello there")],
        model="gpt-4",
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

    mock_app_state = MagicMock(spec=IApplicationState)
    mock_app_state.get_disable_commands.return_value = False
    mock_app_state.get_backend_type.return_value = "openai"
    mock_app_state.get_model_defaults.return_value = {
        "gpt-4": {
            "limits": {
                "max_input_tokens": 1000,
                "context_window": 2000,
            }
        }
    }

    def _get_setting(name: str, default: object | None = None) -> object | None:
        if name == "app_config":
            return None
        if name == "edit_precision_pending":
            return {}
        return default

    mock_app_state.get_setting.side_effect = _get_setting
    mock_app_state.get_command_prefix.return_value = "!/"

    # Create required mocks
    (
        session_enricher,
        request_side_effects,
        command_handler,
        backend_preparer,
        transform_pipeline,
        backend_executor,
    ) = create_request_processor_mocks(
        session_manager,
        backend_request_manager,
        response_manager,
        command_processor,
        request_data,
    )
    session_enricher.enrich.return_value = (session, request_data)

    processor = RequestProcessor(
        command_processor,
        session_manager,
        backend_request_manager,
        response_manager,
        session_enricher,
        request_side_effects,
        command_handler,
        backend_preparer,
        transform_pipeline,
        backend_executor,
        app_state=mock_app_state,
    )

    backend_executor.execute.return_value = response

    await processor.process_request(MockRequestContext(), request_data)

    backend_executor.execute.assert_called_once()


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

    from src.core.config.app_config import AppConfig, AuthConfig
    from src.core.interfaces.application_state_interface import IApplicationState

    app_config = AppConfig(
        auth=AuthConfig(redact_api_keys_in_prompts=False, api_keys=["NO_REDACT_789"])
    )

    mock_app_state = MagicMock(spec=IApplicationState)
    mock_app_state.get_setting.return_value = app_config
    mock_app_state.get_command_prefix.return_value = "!/"

    context = MockRequestContext(headers={"x-session-id": "test-session"})
    text = "Keep NO_REDACT_789 and !/hello"
    request_data = create_mock_request(
        messages=[ChatMessage(role="user", content=text)]
    )

    # Create required mocks
    (
        session_enricher,
        request_side_effects,
        command_handler,
        backend_preparer,
        transform_pipeline,
        backend_executor,
    ) = create_request_processor_mocks(
        session_manager,
        backend_request_manager,
        response_manager,
        command_processor,
        request_data,
    )
    mock_session = AsyncMock(id="test-session", agent=None)
    session_enricher.enrich.return_value = (mock_session, request_data)

    processor = RequestProcessor(
        command_processor,
        session_manager,
        backend_request_manager,
        response_manager,
        session_enricher,
        request_side_effects,
        command_handler,
        backend_preparer,
        transform_pipeline,
        backend_executor,
        app_state=mock_app_state,
    )

    command_processor.add_result(
        ProcessedResult(
            modified_messages=request_data.messages,
            command_executed=False,
            command_results=[],
        )
    )

    response = TestDataBuilder.create_chat_response("OK")
    backend_executor.execute.return_value = response

    # Act
    await processor.process_request(context, request_data)

    # Assert: content passed to backend executor should be unchanged when flag is disabled
    assert backend_executor.execute.called
    redacted_request: ChatRequest = backend_executor.execute.call_args[0][
        3
    ]  # 4th arg is the request
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

    # Create required mocks
    (
        session_enricher,
        request_side_effects,
        command_handler,
        backend_preparer,
        transform_pipeline,
        backend_executor,
    ) = create_request_processor_mocks(
        session_manager,
        backend_request_manager,
        response_manager,
        command_processor,
        request_data,
    )
    mock_session = AsyncMock(id="test-session", agent=None)
    session_enricher.enrich.return_value = (mock_session, request_data)

    # Setup backend executor to return a response
    response = TestDataBuilder.create_chat_response("I'm doing well, thanks!")
    backend_executor.execute.return_value = response

    processor = RequestProcessor(
        command_processor,
        session_manager,
        backend_request_manager,
        response_manager,
        session_enricher,
        request_side_effects,
        command_handler,
        backend_preparer,
        transform_pipeline,
        backend_executor,
    )

    # Act
    response_obj = await processor.process_request(context, request_data)

    # Assert - should be a ResponseEnvelope now
    assert isinstance(response_obj, ResponseEnvelope)
    assert response_obj.content["id"] == response.content["id"]
    assert (
        response_obj.content["choices"][0]["message"]["content"]
        == "I'm doing well, thanks!"
    )

    # Check that session enricher was called (session resolution happens there)
    session_enricher.enrich.assert_called_once()
    # Command handler processes commands
    command_handler.handle.assert_called_once()
    # Backend executor executes the backend request
    backend_executor.execute.assert_called_once()


@pytest.mark.asyncio
async def test_command_only_path_records_full_prompt() -> None:
    """Command-only responses should log full prompts in session history (no sanitization)."""

    command_processor = MockCommandProcessor()
    session_manager = AsyncMock()
    backend_request_manager = AsyncMock()
    response_manager = AsyncMock()

    session = Session(session_id="test-session")
    session_manager.resolve_session_id.return_value = "test-session"
    session_manager.get_session.return_value = session
    session_manager.update_session_agent.return_value = session

    full_prompt = "<environment_details>dbg</environment_details>\nActual task"
    request_data = create_mock_request(
        messages=[ChatMessage(role="user", content=full_prompt)]
    )

    command_processor.add_result(
        ProcessedResult(
            modified_messages=[],
            command_executed=True,
            command_results=[],
        )
    )

    response_manager.process_command_result.return_value = ResponseEnvelope(
        content={"result": "ok"}
    )

    # Create required mocks
    (
        session_enricher,
        request_side_effects,
        command_handler,
        backend_preparer,
        transform_pipeline,
        backend_executor,
    ) = create_request_processor_mocks(
        session_manager,
        backend_request_manager,
        response_manager,
        command_processor,
        request_data,
    )
    session_enricher.enrich.return_value = (session, request_data)
    # For command-only path, command_handler should return ResponseEnvelope
    # CommandHandler internally calls record_command_in_session for command-only paths
    command_handler.handle.return_value = ResponseEnvelope(content={"result": "ok"})

    processor = RequestProcessor(
        command_processor,
        session_manager,
        backend_request_manager,
        response_manager,
        session_enricher,
        request_side_effects,
        command_handler,
        backend_preparer,
        transform_pipeline,
        backend_executor,
    )

    context = MockRequestContext(headers={"x-session-id": "test-session"})

    await processor.process_request(context, request_data)

    # CommandHandler calls record_command_in_session internally for command-only paths
    # We need to check that command_handler was called, which handles the recording
    command_handler.handle.assert_called_once()
    # Verify the command handler received the full prompt (no sanitization)
    call_args = command_handler.handle.call_args
    handler_request: ChatRequest = call_args[0][3]  # 4th arg is the request
    recorded_content = handler_request.messages[0].content
    # Full prompt should be preserved (no sanitization)
    assert recorded_content == full_prompt


@pytest.mark.asyncio
async def test_backend_request_receives_full_messages() -> None:
    """Backend requests should be prepared with full user prompts (no sanitization)."""

    command_processor = MockCommandProcessor()
    session_manager = AsyncMock()
    backend_request_manager = AsyncMock()
    response_manager = AsyncMock()

    session = Session(session_id="test-session")
    session_manager.resolve_session_id.return_value = "test-session"
    session_manager.get_session.return_value = session
    session_manager.update_session_agent.return_value = session

    full_prompt = "<environment_details>dbg</environment_details>\nActual task"
    request_data = create_mock_request(
        messages=[ChatMessage(role="user", content=full_prompt)]
    )

    command_processor.add_result(
        ProcessedResult(
            modified_messages=request_data.messages,
            command_executed=False,
            command_results=[],
        )
    )

    # Create required mocks
    (
        session_enricher,
        request_side_effects,
        command_handler,
        backend_preparer,
        transform_pipeline,
        backend_executor,
    ) = create_request_processor_mocks(
        session_manager,
        backend_request_manager,
        response_manager,
        command_processor,
        request_data,
    )
    session_enricher.enrich.return_value = (session, request_data)
    backend_preparer.prepare.return_value = request_data
    response = TestDataBuilder.create_chat_response("ok")
    backend_executor.execute.return_value = response

    processor = RequestProcessor(
        command_processor,
        session_manager,
        backend_request_manager,
        response_manager,
        session_enricher,
        request_side_effects,
        command_handler,
        backend_preparer,
        transform_pipeline,
        backend_executor,
    )

    context = MockRequestContext(headers={"x-session-id": "test-session"})

    await processor.process_request(context, request_data)

    prepared_request = backend_preparer.prepare.call_args[0][
        2
    ]  # 3rd arg is the request
    prepared_content = prepared_request.messages[0].content
    # Full prompt should be preserved (no sanitization)
    assert prepared_content == full_prompt


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
    response_manager.process_command_result.return_value = response

    # Create required mocks
    (
        session_enricher,
        request_side_effects,
        command_handler,
        backend_preparer,
        transform_pipeline,
        backend_executor,
    ) = create_request_processor_mocks(
        session_manager,
        backend_request_manager,
        response_manager,
        command_processor,
        request_data,
    )
    mock_session = AsyncMock(id="test-session", agent=None)
    session_enricher.enrich.return_value = (mock_session, request_data)
    # For command-only path, command_handler should return ResponseEnvelope
    command_handler.handle.return_value = response

    processor = RequestProcessor(
        command_processor,
        session_manager,
        backend_request_manager,
        response_manager,
        session_enricher,
        request_side_effects,
        command_handler,
        backend_preparer,
        transform_pipeline,
        backend_executor,
    )

    # Act
    response_obj = await processor.process_request(context, request_data)

    # Assert - should be a ResponseEnvelope now
    assert isinstance(response_obj, ResponseEnvelope)
    # This mock is using a different ID but we just need to make sure it's a valid response
    assert "id" in response_obj.content

    # Check that session enricher was called (session resolution happens there)
    session_enricher.enrich.assert_called_once()
    # Command handler processes commands
    command_handler.handle.assert_called_once()
    # For command-only paths, command_handler returns ResponseEnvelope directly
    assert isinstance(response_obj, ResponseEnvelope)


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
    async def mock_stream_generator() -> AsyncGenerator[ProcessedResponse, None]:
        yield ProcessedResponse(
            content=b'data: {"choices":[{"delta":{"content":"Hello"},"index":0}]}\n\n'
        )
        yield ProcessedResponse(
            content=b'data: {"choices":[{"delta":{"content":" there!"},"index":0}]}\n\n'
        )
        yield ProcessedResponse(content=b"data: [DONE]\n\n")

    # Create StreamingResponseEnvelope to return
    streaming_generator = mock_stream_generator()

    streaming_envelope = StreamingResponseEnvelope(
        content=streaming_generator,
        media_type="text/event-stream",
    )

    # Create required mocks
    (
        session_enricher,
        request_side_effects,
        command_handler,
        backend_preparer,
        transform_pipeline,
        backend_executor,
    ) = create_request_processor_mocks(
        session_manager,
        backend_request_manager,
        response_manager,
        command_processor,
        request_data,
    )
    mock_session = AsyncMock(id="test-session", agent=None)
    session_enricher.enrich.return_value = (mock_session, request_data)
    backend_preparer.prepare.return_value = request_data
    backend_executor.execute.return_value = streaming_envelope

    processor = RequestProcessor(
        command_processor,
        session_manager,
        backend_request_manager,
        response_manager,
        session_enricher,
        request_side_effects,
        command_handler,
        backend_preparer,
        transform_pipeline,
        backend_executor,
    )

    # Act
    response = await processor.process_request(context, request_data)

    # Assert
    assert isinstance(response, StreamingResponseEnvelope)
    assert response.media_type == "text/event-stream"

    # Collect the streamed chunks
    chunks: list[str] = []
    assert response.content is not None

    async for chunk in response.content:
        chunks.append((chunk.content or b"").decode("utf-8"))

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

    # Create required mocks
    (
        session_enricher,
        request_side_effects,
        command_handler,
        backend_preparer,
        transform_pipeline,
        backend_executor,
    ) = create_request_processor_mocks(
        session_manager,
        backend_request_manager,
        response_manager,
        command_processor,
        request_data,
    )
    mock_session = AsyncMock(id="test-session", agent=None)
    session_enricher.enrich.return_value = (mock_session, request_data)

    # Setup backend executor to throw an error
    backend_error = BackendError("API unavailable")
    backend_preparer.prepare.return_value = request_data
    backend_executor.execute.side_effect = backend_error

    processor = RequestProcessor(
        command_processor,
        session_manager,
        backend_request_manager,
        response_manager,
        session_enricher,
        request_side_effects,
        command_handler,
        backend_preparer,
        transform_pipeline,
        backend_executor,
    )

    # Act & Assert
    with pytest.raises(LLMProxyError) as exc:
        await processor.process_request(context, request_data)

    assert "API unavailable" in str(exc.value.message)
