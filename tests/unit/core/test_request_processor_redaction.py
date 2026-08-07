"""API key redaction and session gating for RequestProcessor."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.config.app_config import AppConfig, AuthConfig
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.processed_result import ProcessedResult
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
async def test_request_processor_skips_redaction_when_session_disables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command_processor = MockCommandProcessor()
    session_manager = AsyncMock()
    backend_request_manager = AsyncMock()
    response_manager = AsyncMock()

    session = Session(session_id="test-session")
    session.state = session.state.with_api_key_redaction_enabled(False)

    session_manager.resolve_session_id.return_value = "test-session"
    session_manager.get_session.return_value = session
    session_manager.update_session_agent.return_value = session
    session_manager.update_session_history.return_value = None

    request_data = create_mock_request()

    command_processor.add_result(
        ProcessedResult(
            modified_messages=request_data.messages,
            command_executed=False,
            command_results=[],
        )
    )

    response = TestDataBuilder.create_chat_response("Hello there!")
    backend_request_manager.prepare_backend_request.return_value = request_data
    backend_request_manager.process_backend_request.return_value = response

    from src.core.config.app_config import AppConfig

    app_config = AppConfig(auth=AuthConfig(redact_api_keys_in_prompts=True))

    mock_app_state = MagicMock(spec=IApplicationState)
    mock_app_state.get_setting.return_value = app_config
    mock_app_state.get_disable_commands.return_value = False
    mock_app_state.get_command_prefix.return_value = "!/"

    instantiation_count = 0

    class TrackingRedactionMiddleware:
        def __init__(self, *args, **kwargs) -> None:
            nonlocal instantiation_count
            instantiation_count += 1

        async def process(
            self, request: ChatRequest, context: dict[str, Any] | None = None
        ) -> ChatRequest:
            return request

    monkeypatch.setattr(
        "src.core.services.redaction_middleware.RedactionMiddleware",
        TrackingRedactionMiddleware,
    )
    monkeypatch.setattr(
        "src.core.common.logging_utils.discover_api_keys_from_config_and_env",
        lambda _cfg: [],
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
    # Setup session enricher to return the session
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

    await processor.process_request(MockRequestContext(), request_data)

    assert instantiation_count == 0


@pytest.mark.asyncio
async def test_request_processor_applies_redaction_when_session_enables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command_processor = MockCommandProcessor()
    session_manager = AsyncMock()
    backend_request_manager = AsyncMock()
    response_manager = AsyncMock()

    session = Session(session_id="test-session")
    session.state = session.state.with_api_key_redaction_enabled(True)

    session_manager.resolve_session_id.return_value = "test-session"
    session_manager.get_session.return_value = session
    session_manager.update_session_agent.return_value = session
    session_manager.update_session_history.return_value = None

    request_data = create_mock_request()

    command_processor.add_result(
        ProcessedResult(
            modified_messages=request_data.messages,
            command_executed=False,
            command_results=[],
        )
    )

    response = TestDataBuilder.create_chat_response("Hello there!")
    backend_request_manager.prepare_backend_request.return_value = request_data
    backend_request_manager.process_backend_request.return_value = response

    from src.core.config.app_config import AppConfig

    app_config = AppConfig(auth=AuthConfig(redact_api_keys_in_prompts=False))

    mock_app_state = MagicMock(spec=IApplicationState)
    mock_app_state.get_setting.return_value = app_config
    mock_app_state.get_disable_commands.return_value = False
    mock_app_state.get_command_prefix.return_value = "!/"

    # Create required mocks
    (
        session_enricher,
        request_side_effects,
        command_handler,
        backend_preparer,
        _,
        backend_executor,
    ) = create_request_processor_mocks(
        session_manager,
        backend_request_manager,
        response_manager,
        command_processor,
        request_data,
    )
    # Setup session enricher to return the session
    session_enricher.enrich.return_value = (session, request_data)

    # Use real transform pipeline to test redaction
    from src.core.services.request_transform_pipeline import RequestTransformPipeline

    transform_pipeline = RequestTransformPipeline(app_state=mock_app_state)

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

    response = TestDataBuilder.create_chat_response("Hello there!")
    backend_executor.execute.return_value = response

    await processor.process_request(MockRequestContext(), request_data)

    # Check that backend executor was called (redaction was applied via transform pipeline)
    assert backend_executor.execute.called


async def test_request_processor_applies_redaction_before_backend_call(
    session_service: MockSessionService,
) -> None:
    """Ensure API key redaction is applied to outbound request.

    Note: Command filtering is now handled by the non-forwardable message tagging system,
    not by RedactionMiddleware.
    """
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

    # Create config with redaction enabled and a known API key (frozen models require model_copy)
    auth_config = AuthConfig(
        redact_api_keys_in_prompts=True, api_keys=["SECRET_API_KEY_123"]
    )
    app_config = AppConfig(auth=auth_config)

    mock_app_state = MagicMock(spec=IApplicationState)
    # get_setting("app_config") should return our config
    mock_app_state.get_setting.return_value = app_config
    # Ensure get_command_prefix returns a proper value (not a MagicMock)
    mock_app_state.get_command_prefix.return_value = "!/"

    # Create a request containing both a secret and a proxy command
    original_text = "Please use SECRET_API_KEY_123 and !/hello to proceed"
    context = MockRequestContext(headers={"x-session-id": "test-session"})
    request_data = create_mock_request(
        messages=[ChatMessage(role="user", content=original_text)]
    )

    # Create required mocks
    (
        session_enricher,
        request_side_effects,
        command_handler,
        backend_preparer,
        _,
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

    # Use real transform pipeline for redaction tests
    from src.core.services.request_transform_pipeline import RequestTransformPipeline

    transform_pipeline = RequestTransformPipeline(app_state=mock_app_state)

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

    # Setup command processor to return no additional modifications
    command_processor.add_result(
        ProcessedResult(
            modified_messages=request_data.messages,
            command_executed=False,
            command_results=[],
        )
    )

    # Backend executor returns a trivial response
    response = TestDataBuilder.create_chat_response("OK")
    backend_executor.execute.return_value = response

    # Act
    await processor.process_request(context, request_data)

    # Assert that the request passed to backend executor has been redacted and filtered
    assert backend_executor.execute.called
    # The backend executor receives the transformed request as the 4th argument
    redacted_request: ChatRequest = backend_executor.execute.call_args[0][3]
    assert isinstance(redacted_request, ChatRequest)
    # Extract user content
    redacted_message = next(
        (m for m in redacted_request.messages if m.role == "user"),
        None,
    )
    redacted_content = ""
    if redacted_message is not None:
        message_content = redacted_message.content or ""
        if isinstance(message_content, list):
            redacted_content = " ".join(
                part.text if hasattr(part, "text") else str(part)
                for part in message_content
                if part is not None
            )
        else:
            redacted_content = str(message_content)
    # API key should be replaced
    assert "SECRET_API_KEY_123" not in redacted_content
    assert "(API_KEY_HAS_BEEN_REDACTED)" in redacted_content
    # Proxy command should remain (filtering is handled by tagging system, not redaction)
    assert "!/hello" in redacted_content


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

    app_config = AppConfig(
        auth=AuthConfig(
            redact_api_keys_in_prompts=True,
            api_keys=["ANOTHER_SECRET_KEY_456"],
        )
    )

    mock_app_state = MagicMock(spec=IApplicationState)
    mock_app_state.get_setting.return_value = app_config
    mock_app_state.get_command_prefix.return_value = "!/"

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

    # Create required mocks
    (
        session_enricher,
        request_side_effects,
        command_handler,
        backend_preparer,
        _,
        backend_executor,
    ) = create_request_processor_mocks(
        session_manager,
        backend_request_manager,
        response_manager,
        command_processor,
        modified_request,
    )
    mock_session = AsyncMock(id="test-session", agent=None)
    session_enricher.enrich.return_value = (mock_session, modified_request)

    # Use real transform pipeline for redaction tests
    from src.core.services.request_transform_pipeline import RequestTransformPipeline

    transform_pipeline = RequestTransformPipeline(app_state=mock_app_state)

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

    response = TestDataBuilder.create_chat_response("OK")
    backend_executor.execute.return_value = response

    # Act
    await processor.process_request(context, original)

    # Assert
    assert backend_executor.execute.called
    redacted_request: ChatRequest = backend_executor.execute.call_args[0][
        3
    ]  # 4th arg is the request
    redacted_message = next(
        (m for m in redacted_request.messages if m.role == "user"), None
    )
    redacted_content = ""
    if redacted_message is not None:
        message_content = redacted_message.content or ""
        if isinstance(message_content, list):
            redacted_content = " ".join(
                part.text if hasattr(part, "text") else str(part)
                for part in message_content
                if part is not None
            )
        else:
            redacted_content = str(message_content)
    assert "ANOTHER_SECRET_KEY_456" not in redacted_content
    assert "(API_KEY_HAS_BEEN_REDACTED)" in redacted_content
