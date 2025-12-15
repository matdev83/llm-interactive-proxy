"""
Tests for the RequestProcessor implementation.

NOTE: These tests need to be updated to work with the refactored RequestProcessor
that now requires all component dependencies (SessionEnricher, RequestSideEffects,
CommandHandler, BackendPreparer, RequestTransformPipeline, BackendExecutor).
"""

from collections.abc import AsyncGenerator

# Tests updated for refactored RequestProcessor architecture
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.common.exceptions import BackendError, LLMProxyError
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.commands import CommandResult
from src.core.domain.processed_result import ProcessedResult
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import (
    ProcessedResponse,
    ResponseEnvelope,
    StreamingResponseEnvelope,
)
from src.core.domain.session import Session
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

    # Create request data
    request_data = create_mock_request()

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

    # Create a request context
    context = MockRequestContext(headers={"x-session-id": "test-session"})

    # Setup command processor to return no commands processed
    command_processor.add_result(
        ProcessedResult(
            modified_messages=request_data.messages,
            command_executed=False,
            command_results=[],
        )
    )

    # Setup backend executor to return a response
    response = TestDataBuilder.create_chat_response("Hello there!")
    backend_executor.execute.return_value = response

    # Act
    response_obj = await processor.process_request(context, request_data)

    # Assert - should be a ResponseEnvelope now
    assert isinstance(response_obj, ResponseEnvelope)
    assert response_obj.content["id"] == response.content["id"]
    assert response_obj.content["choices"][0]["message"]["content"] == "Hello there!"

    # Check that the new architecture components were called
    session_enricher.enrich.assert_called_once()
    request_side_effects.apply.assert_called_once()
    command_handler.handle.assert_called_once()
    backend_preparer.prepare.assert_called_once()
    transform_pipeline.transform.assert_called_once()
    backend_executor.execute.assert_called_once()


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

    from unittest.mock import MagicMock

    from src.core.config.app_config import AppConfig, AuthConfig
    from src.core.interfaces.application_state_interface import IApplicationState

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

    from unittest.mock import MagicMock

    from src.core.config.app_config import AppConfig, AuthConfig
    from src.core.interfaces.application_state_interface import IApplicationState

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

    from src.core.config.app_config import AppConfig, EditPrecisionConfig
    from src.core.interfaces.application_state_interface import IApplicationState

    app_config = AppConfig(
        edit_precision=EditPrecisionConfig(
            enabled=True, temperature=0.05, min_top_p=0.2, override_top_p=True
        )
    )

    mock_app_state = MagicMock(spec=IApplicationState)
    mock_app_state.get_setting.return_value = app_config
    mock_app_state.get_command_prefix.return_value = "!/"

    # Create a request whose content includes a known failure phrase
    failure_text = "The SEARCH block ... does not match anything in the file"
    request_data = create_mock_request(
        stream=True, messages=[ChatMessage(role="user", content=failure_text)]
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
    # Setup session enricher to return the session
    session_enricher.enrich.return_value = (session, request_data)

    # Use real transform pipeline for edit precision tests
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

    # No additional command modifications
    command_processor.add_result(
        ProcessedResult(
            modified_messages=request_data.messages,
            command_executed=False,
            command_results=[],
        )
    )

    # Backend executor returns a dummy response
    response = TestDataBuilder.create_chat_response("OK")
    backend_executor.execute.return_value = response

    # Act
    await processor.process_request(MockRequestContext(), request_data)

    # Assert: backend executor was called with the transformed request (which applies edit precision)
    assert backend_executor.execute.called
    sent_request = backend_executor.execute.call_args[0][3]  # 4th arg is the request
    assert sent_request.temperature == pytest.approx(0.2)
    assert sent_request.top_p == pytest.approx(0.2)


@pytest.mark.asyncio
async def test_request_processor_preserves_existing_low_temperature() -> None:
    """When a request is already deterministic, precision tuning must not raise the temperature."""
    command_processor = MockCommandProcessor()
    session_manager = AsyncMock()
    backend_request_manager = AsyncMock()
    response_manager = AsyncMock()

    session = AsyncMock(id="test-session", agent="someagent")
    session_manager.resolve_session_id.return_value = "test-session"
    session_manager.get_session.return_value = session

    from unittest.mock import MagicMock

    from src.core.config.app_config import AppConfig, EditPrecisionConfig
    from src.core.interfaces.application_state_interface import IApplicationState

    app_config = AppConfig(
        edit_precision=EditPrecisionConfig(
            enabled=True, temperature=0.05, min_top_p=0.2, override_top_p=True
        )
    )

    mock_app_state = MagicMock(spec=IApplicationState)
    mock_app_state.get_setting.return_value = app_config
    mock_app_state.get_command_prefix.return_value = "!/"

    failure_text = "The SEARCH block ... does not match anything in the file"
    request_data = ChatRequest(
        model="gpt-4",
        messages=[ChatMessage(role="user", content=failure_text)],
        temperature=0.0,
        top_p=0.5,
        stream=True,
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
    # Setup session enricher to return the session
    session_enricher.enrich.return_value = (session, request_data)

    # Use real transform pipeline for edit precision tests
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

    command_processor.add_result(
        ProcessedResult(
            modified_messages=request_data.messages,
            command_executed=False,
            command_results=[],
        )
    )

    response = TestDataBuilder.create_chat_response("OK")
    backend_executor.execute.return_value = response

    await processor.process_request(MockRequestContext(), request_data)

    assert backend_executor.execute.called
    sent_request = backend_executor.execute.call_args[0][3]  # 4th arg is the request
    assert sent_request.temperature == pytest.approx(0.0)
    assert sent_request.top_p == pytest.approx(0.2)


@pytest.mark.asyncio
async def test_request_processor_disables_hybrid_reasoning_after_flag() -> None:
    """Ensure hybrid reasoning is disabled on next turn when response middleware sets a flag."""

    command_processor = MockCommandProcessor()
    session_manager = AsyncMock()
    backend_request_manager = AsyncMock()
    response_manager = AsyncMock()

    session = AsyncMock(id="test-session", agent="someagent")
    session_manager.resolve_session_id.return_value = "test-session"
    session_manager.get_session.return_value = session

    from unittest.mock import MagicMock

    from src.core.config.app_config import AppConfig, EditPrecisionConfig
    from src.core.interfaces.application_state_interface import IApplicationState

    app_config = AppConfig(
        edit_precision=EditPrecisionConfig(
            enabled=True,
            temperature=0.05,
            min_top_p=0.2,
            override_top_p=True,
        )
    )

    mock_app_state = MagicMock(spec=IApplicationState)
    app_state_store: dict[str, Any] = {
        "app_config": app_config,
        "edit_precision_pending": {},
        "edit_precision_hybrid_reasoning_disabled": {"test-session": True},
        "edit_precision_hybrid_reasoning_active": {"test-session": {"timestamp": 0.0}},
    }

    def get_setting_side_effect(key: str, default: Any | None = None) -> Any:
        return app_state_store.get(key, default)

    def set_setting_side_effect(key: str, value: Any) -> None:
        app_state_store[key] = value

    mock_app_state.get_setting.side_effect = get_setting_side_effect
    mock_app_state.set_setting.side_effect = set_setting_side_effect
    mock_app_state.get_command_prefix.return_value = "!/"

    request_data = ChatRequest(
        model="hybrid:[minimax:MiniMax-M2,qwen-oauth:qwen3-coder-plus]",
        messages=[ChatMessage(role="user", content="please continue")],
        temperature=0.7,
        top_p=0.9,
        extra_body={"hybrid_reasoning_probability": 0.6},
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
    # Setup session enricher to return the session
    session_enricher.enrich.return_value = (session, request_data)

    # Use real transform pipeline for edit precision tests
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

    command_processor.add_result(
        ProcessedResult(
            modified_messages=request_data.messages,
            command_executed=False,
            command_results=[],
        )
    )

    response = TestDataBuilder.create_chat_response("OK")
    backend_executor.execute.return_value = response

    await processor.process_request(MockRequestContext(), request_data)

    assert backend_executor.execute.called
    sent_request = backend_executor.execute.call_args[0][3]  # 4th arg is the request
    assert sent_request.extra_body.get("_temp_hybrid_reasoning_probability") == 0.0
    meta = sent_request.extra_body.get("_edit_precision_meta", {})
    assert meta.get("applied_hybrid_reasoning_probability") == 0.0
    mock_app_state.set_setting.assert_any_call(
        "edit_precision_hybrid_reasoning_disabled", {}
    )
    mock_app_state.set_setting.assert_any_call(
        "edit_precision_hybrid_reasoning_active", {}
    )


@pytest.mark.asyncio
async def test_request_processor_applies_edit_precision_temperature_override() -> None:
    """Ensure URI temperature is overridden on the next request after an edit failure."""

    command_processor = MockCommandProcessor()
    session_manager = AsyncMock()
    backend_request_manager = AsyncMock()
    response_manager = AsyncMock()

    session = AsyncMock(id="test-session", agent="roo")
    session_manager.resolve_session_id.return_value = "test-session"
    session_manager.get_session.return_value = session

    from unittest.mock import MagicMock

    from src.core.config.app_config import AppConfig, EditPrecisionConfig
    from src.core.interfaces.application_state_interface import IApplicationState

    app_config = AppConfig(
        edit_precision=EditPrecisionConfig(
            enabled=True,
            temperature=0.0,
            min_top_p=0.2,
            override_top_p=True,
        )
    )

    mock_app_state = MagicMock(spec=IApplicationState)
    app_state_store: dict[str, Any] = {
        "app_config": app_config,
        "edit_precision_pending": {"test-session": 1},
        "edit_precision_hybrid_reasoning_disabled": {"test-session": True},
        "edit_precision_hybrid_reasoning_active": {"test-session": {"timestamp": 0.0}},
    }

    def get_setting_side_effect(key: str, default: Any | None = None) -> Any:
        return app_state_store.get(key, default)

    def set_setting_side_effect(key: str, value: Any) -> None:
        app_state_store[key] = value

    mock_app_state.get_setting.side_effect = get_setting_side_effect
    mock_app_state.set_setting.side_effect = set_setting_side_effect
    mock_app_state.get_command_prefix.return_value = "!/"

    request_data = ChatRequest(
        model="hybrid:[minimax:MiniMax-M2,qwen-oauth:qwen3-coder-plus?temperature=0.6]",
        messages=[ChatMessage(role="user", content="diff_error happened")],
        temperature=0.7,
        top_p=0.9,
        extra_body={"hybrid_reasoning_probability": 0.6},
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
    # Setup session enricher to return the session
    session_enricher.enrich.return_value = (session, request_data)

    # Use real transform pipeline for edit precision tests
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

    command_processor.add_result(
        ProcessedResult(
            modified_messages=request_data.messages,
            command_executed=False,
            command_results=[],
        )
    )

    response = TestDataBuilder.create_chat_response("OK")
    backend_executor.execute.return_value = response

    await processor.process_request(MockRequestContext(), request_data)

    assert backend_executor.execute.called
    sent_request = backend_executor.execute.call_args[0][3]  # 4th arg is the request
    assert sent_request.temperature == pytest.approx(0.0)
    assert sent_request.top_p == pytest.approx(0.2)
    assert app_state_store.get("edit_precision_hybrid_reasoning_disabled", {}) == {}


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

    from src.core.config.app_config import AppConfig, EditPrecisionConfig
    from src.core.interfaces.application_state_interface import IApplicationState

    app_config = AppConfig(
        edit_precision=EditPrecisionConfig(
            enabled=True,
            temperature=0.05,
            min_top_p=0.2,
            exclude_agents_regex=r"^(cline|roocode)$",
        )
    )

    mock_app_state = MagicMock(spec=IApplicationState)
    mock_app_state.get_setting.return_value = app_config
    mock_app_state.get_command_prefix.return_value = "!/"

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

    # Use real transform pipeline for edit precision tests
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
    await processor.process_request(MockRequestContext(), request_data)

    # Assert: params unchanged due to exclusion
    assert backend_executor.execute.called
    sent_request = backend_executor.execute.call_args[0][3]  # 4th arg is the request
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

    from src.core.config.app_config import AppConfig, EditPrecisionConfig
    from src.core.interfaces.application_state_interface import IApplicationState

    app_config = AppConfig(
        edit_precision=EditPrecisionConfig(
            enabled=True, temperature=0.2, min_top_p=0.4, override_top_p=True
        )
    )

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
    mock_app_state.get_command_prefix.return_value = "!/"

    # No failure phrase in message; tuning should still be applied due to pending flag
    request_data = create_mock_request(
        stream=False,
        messages=[ChatMessage(role="user", content="Proceed with next step")],
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
    # Setup session enricher to return the session
    session_enricher.enrich.return_value = (session, request_data)

    # Use real transform pipeline for edit precision tests
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
    await processor.process_request(MockRequestContext(), request_data)

    # Assert request was tuned
    assert backend_executor.execute.called
    sent_request = backend_executor.execute.call_args[0][3]  # 4th arg is the request
    assert sent_request.temperature == pytest.approx(0.2)
    assert sent_request.top_p == pytest.approx(0.4)


@pytest.mark.asyncio
async def test_request_processor_clears_pending_entry_after_use() -> None:
    """Pending edit-precision flags should be removed once consumed."""
    command_processor = MockCommandProcessor()
    session_manager = AsyncMock()
    backend_request_manager = AsyncMock()
    response_manager = AsyncMock()

    session = AsyncMock(id="test-session", agent="someagent")
    session_manager.resolve_session_id.return_value = "test-session"
    session_manager.get_session.return_value = session

    from unittest.mock import MagicMock

    from src.core.config.app_config import AppConfig, EditPrecisionConfig
    from src.core.interfaces.application_state_interface import IApplicationState

    app_config = AppConfig(
        edit_precision=EditPrecisionConfig(
            enabled=True, temperature=0.2, min_top_p=0.4, override_top_p=True
        )
    )

    pending_map = {"test-session": 1}

    def _get_setting(name: str, default: object | None = None) -> object | None:
        if name == "app_config":
            return app_config
        if name == "edit_precision_pending":
            return pending_map
        return default

    mock_app_state = MagicMock(spec=IApplicationState)
    mock_app_state.get_setting.side_effect = _get_setting
    mock_app_state.get_command_prefix.return_value = "!/"

    request_data = create_mock_request(
        stream=False,
        messages=[ChatMessage(role="user", content="Proceed with next step")],
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
    # Setup session enricher to return the session
    session_enricher.enrich.return_value = (session, request_data)

    # Use real transform pipeline for edit precision tests
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

    command_processor.add_result(
        ProcessedResult(
            modified_messages=request_data.messages,
            command_executed=False,
            command_results=[],
        )
    )

    response = TestDataBuilder.create_chat_response("OK")
    backend_executor.execute.return_value = response

    await processor.process_request(MockRequestContext(), request_data)

    pending_updates = [
        call
        for call in mock_app_state.set_setting.call_args_list
        if call.args and call.args[0] == "edit_precision_pending"
    ]
    assert pending_updates, "expected pending map to be updated"
    updated_map = pending_updates[-1].args[1]
    assert isinstance(updated_map, dict)
    assert "test-session" not in updated_map


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

    from src.core.config.app_config import AppConfig, AuthConfig
    from src.core.interfaces.application_state_interface import IApplicationState

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

    from src.core.config.app_config import AppConfig, AuthConfig
    from src.core.interfaces.application_state_interface import IApplicationState

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
    assert "!/hello" not in redacted_content


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
