"""
Characterization tests for RequestProcessor refactoring safety.

These tests lock down under-specified behaviors to ensure they are preserved
during the refactoring process. Focus areas:
- Fail-open behavior for enrichments and side effects
- Ordering guarantees for transformations
- TypeError enforcement for non-ChatRequest inputs
- Domain request attachment to context
"""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.processed_result import ProcessedResult
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope
from src.core.domain.session import Session
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.interfaces.backend_request_manager_interface import IBackendRequestManager
from src.core.interfaces.command_processor_interface import ICommandProcessor
from src.core.interfaces.response_manager_interface import IResponseManager
from src.core.interfaces.session_manager_interface import ISessionManager
from src.core.services.request_processor_service import RequestProcessor


@pytest.fixture
def mock_command_processor() -> ICommandProcessor:
    """Create a mock command processor."""
    mock = AsyncMock(spec=ICommandProcessor)
    # Default: no commands executed
    mock.process_messages.return_value = ProcessedResult(
        modified_messages=[ChatMessage(role="user", content="Hello")],
        command_executed=False,
        command_results=[],
    )
    return mock


@pytest.fixture
def mock_session_manager() -> ISessionManager:
    """Create a mock session manager."""
    mock = AsyncMock(spec=ISessionManager)
    mock.resolve_session_id.return_value = "test-session-123"

    # Mock session with state
    session = MagicMock(spec=Session)
    session.agent = "test-agent"
    session.state = MagicMock()
    session.state.client_os = None
    session.state.vtc_enabled = False
    session.state.project_dir_resolution_attempted = False
    session.state.api_key_redaction_enabled = None
    session.state.command_prefix_override = None
    session.update_state = MagicMock()

    mock.get_session.return_value = session
    mock.update_session_agent.return_value = session
    mock.update_session_history.return_value = None
    mock.record_command_in_session.return_value = None
    mock.apply_openai_codex_history_compaction_gate = AsyncMock(
        side_effect=lambda s, _b: s
    )

    return mock


@pytest.fixture
def mock_backend_request_manager() -> IBackendRequestManager:
    """Create a mock backend request manager."""
    mock = AsyncMock(spec=IBackendRequestManager)

    # Default: return a backend request
    async def prepare_backend_request(request, processed_result, **_kwargs):
        return request

    mock.prepare_backend_request.side_effect = prepare_backend_request

    # Mock backend response
    response = ResponseEnvelope(
        content={"message": "test response"},
        status_code=200,
    )
    mock.process_backend_request.return_value = response

    return mock


@pytest.fixture
def mock_response_manager() -> IResponseManager:
    """Create a mock response manager."""
    mock = AsyncMock(spec=IResponseManager)
    return mock


@pytest.fixture
def mock_app_state() -> IApplicationState:
    """Create a mock application state."""
    mock = MagicMock(spec=IApplicationState)
    mock.get_setting.return_value = None
    mock.get_service.return_value = None
    mock.get_model_defaults.return_value = {}
    mock.get_command_prefix.return_value = "!/"
    mock.get_disable_commands.return_value = False
    return mock


@pytest.fixture
def request_context() -> RequestContext:
    """Create a minimal request context."""
    mock_app_state = MagicMock(spec=IApplicationState)
    return RequestContext(
        headers={},
        cookies={},
        state=MagicMock(),
        app_state=mock_app_state,
        client_host="127.0.0.1",
        original_request=None,
    )


@pytest.fixture
def mock_session_enricher():
    from unittest.mock import AsyncMock

    enricher = AsyncMock()
    enricher.enrich = AsyncMock(
        return_value=(
            MagicMock(),
            ChatRequest(
                model="gpt-4", messages=[ChatMessage(role="user", content="test")]
            ),
        )
    )
    return enricher


@pytest.fixture
def mock_request_side_effects():
    from unittest.mock import AsyncMock

    side_effects = AsyncMock()
    side_effects.apply = AsyncMock(side_effect=lambda ctx, sid, req: req)
    return side_effects


@pytest.fixture
def mock_command_handler():
    from unittest.mock import AsyncMock

    from src.core.domain.processed_result import ProcessedResult

    handler = AsyncMock()
    handler.handle = AsyncMock(
        return_value=ProcessedResult(
            command_executed=False,
            modified_messages=[],
            command_results=[],
        )
    )
    return handler


@pytest.fixture
def mock_backend_preparer():
    from unittest.mock import AsyncMock

    preparer = AsyncMock()
    preparer.prepare = AsyncMock(side_effect=lambda ctx, sid, req, cmd, **kw: req)
    return preparer


@pytest.fixture
def mock_transform_pipeline():
    from unittest.mock import AsyncMock

    pipeline = AsyncMock()
    pipeline.transform = AsyncMock(side_effect=lambda ctx, sess, sid, req: req)
    return pipeline


@pytest.fixture
def mock_backend_executor():
    from unittest.mock import AsyncMock, MagicMock

    from src.core.domain.responses import ResponseEnvelope

    executor = AsyncMock()
    executor.execute = AsyncMock(return_value=ResponseEnvelope(content=MagicMock()))
    return executor


@pytest.fixture
def request_processor(
    mock_command_processor: ICommandProcessor,
    mock_session_manager: ISessionManager,
    mock_backend_request_manager: IBackendRequestManager,
    mock_response_manager: IResponseManager,
    mock_app_state: IApplicationState,
    mock_session_enricher,
    mock_request_side_effects,
    mock_command_handler,
    mock_backend_preparer,
    mock_transform_pipeline,
    mock_backend_executor,
) -> RequestProcessor:
    """Create a RequestProcessor with mocked dependencies."""
    return RequestProcessor(
        command_processor=mock_command_processor,
        session_manager=mock_session_manager,
        backend_request_manager=mock_backend_request_manager,
        response_manager=mock_response_manager,
        session_enricher=mock_session_enricher,
        request_side_effects=mock_request_side_effects,
        command_handler=mock_command_handler,
        backend_preparer=mock_backend_preparer,
        transform_pipeline=mock_transform_pipeline,
        backend_executor=mock_backend_executor,
        app_state=mock_app_state,
    )


# Test Requirement 1.1: input normalization behavior
@pytest.mark.asyncio
async def test_allows_non_chat_request_when_session_enricher_normalizes(
    request_processor: RequestProcessor,
    request_context: RequestContext,
    mock_session_enricher,
) -> None:
    """
    RequestProcessor delegates request normalization to SessionEnricher.
    Non-ChatRequest payloads should be accepted when the enricher returns ChatRequest.
    """
    invalid_request: Any = {"model": "gpt-4", "messages": []}

    await request_processor.process_request(request_context, invalid_request)

    mock_session_enricher.enrich.assert_called_once()
    assert mock_session_enricher.enrich.call_args[0][1] == invalid_request


# Test Requirement 1.2: Session enrichment delegation
@pytest.mark.asyncio
async def test_delegates_to_session_enricher(
    request_processor: RequestProcessor,
    request_context: RequestContext,
    mock_session_enricher,
) -> None:
    """
    Requirement 1.2: When process_request is called with a ChatRequest,
    the Request Processor Service shall delegate to SessionEnricher
    for session resolution and enrichment.
    """
    request = ChatRequest(
        model="gpt-4",
        messages=[ChatMessage(role="user", content="Hello")],
    )

    await request_processor.process_request(request_context, request)

    # Verify session enricher was called
    mock_session_enricher.enrich.assert_called_once()
    call_args = mock_session_enricher.enrich.call_args
    assert call_args[0][0] == request_context
    assert call_args[0][1] == request


@pytest.mark.asyncio
async def test_explicit_backend_prefix_overrides_context_backend(
    request_processor: RequestProcessor,
    request_context: RequestContext,
    mock_session_enricher,
) -> None:
    """Regression: explicit '<backend>:<model>' must win over stale context.backend."""

    request_context.backend = "gemini-oauth-auto"
    request = ChatRequest(
        model="kimi-code:kimi/kimi-for-coding",
        messages=[ChatMessage(role="user", content="Hello")],
    )
    mock_session_enricher.enrich.return_value = (MagicMock(), request)

    await request_processor.process_request(request_context, request)

    assert request_context.backend == "kimi-code"


@pytest.mark.asyncio
async def test_model_only_colon_suffix_does_not_override_context_backend(
    request_processor: RequestProcessor,
    request_context: RequestContext,
    mock_session_enricher,
) -> None:
    """Regression: `vendor/model:free` is model-only, not explicit backend."""

    request_context.backend = "gemini-oauth-auto"
    request = ChatRequest(
        model="openrouter/anthropic/claude-3-haiku:free",
        messages=[ChatMessage(role="user", content="Hello")],
    )
    mock_session_enricher.enrich.return_value = (MagicMock(), request)

    await request_processor.process_request(request_context, request)

    assert request_context.backend == "gemini-oauth-auto"


@pytest.mark.asyncio
async def test_request_processor_delegates_auxiliary_routing_to_preparer(
    request_processor: RequestProcessor,
    request_context: RequestContext,
    mock_app_state: IApplicationState,
    mock_session_enricher,
    mock_backend_executor,
) -> None:
    """RequestProcessor delegates auxiliary routing to BackendRequestPreparer."""

    # Enable auxiliary routing (route to a lightweight backend:model).
    cast(Any, mock_app_state).get_setting.return_value = MagicMock(
        auxiliary_routing=MagicMock(
            enabled=True,
            backend=None,
            model="openai:gpt-4o-mini",
            detection_patterns=[r"Generate a title"],
            max_message_count=3,
        )
    )

    request = ChatRequest(
        model="google/gemini-3-flash-preview",
        messages=[
            ChatMessage(role="system", content="You are a title generator."),
            ChatMessage(role="user", content="Generate a title for the session"),
        ],
    )
    mock_session_enricher.enrich.return_value = (MagicMock(), request)

    await request_processor.process_request(request_context, request)

    # The backend executor should receive the rewritten model.
    call_args = mock_backend_executor.execute.call_args
    assert call_args is not None
    called_request = call_args.args[3]
    assert called_request.model == "google/gemini-3-flash-preview"
    assert request_context.extensions.get("auxiliary_request") is None


@pytest.mark.asyncio
async def test_request_processor_does_not_override_explicit_backend_before_preparer(
    request_processor: RequestProcessor,
    request_context: RequestContext,
    mock_app_state: IApplicationState,
    mock_session_enricher,
    mock_backend_executor,
) -> None:
    """Regression: OpenCode title requests already carry qwen-oauth:model selectors."""

    cast(Any, mock_app_state).get_setting.return_value = MagicMock(
        auxiliary_routing=MagicMock(
            enabled=True,
            backend="openrouter",
            model="openrouter/free",
            detection_patterns=[r"Generate a title"],
            max_message_count=3,
        )
    )

    request = ChatRequest(
        model="qwen-oauth:qwen/coder-model",
        messages=[
            ChatMessage(role="system", content="You are a title generator."),
            ChatMessage(role="user", content="Generate a title for this conversation:"),
            ChatMessage(
                role="user",
                content="What are the recent commits in this repo all about?",
            ),
        ],
    )
    mock_session_enricher.enrich.return_value = (MagicMock(), request)

    await request_processor.process_request(request_context, request)

    call_args = mock_backend_executor.execute.call_args
    assert call_args is not None
    called_request = call_args.args[3]
    assert called_request.model == "qwen-oauth:qwen/coder-model"
    assert request_context.extensions.get("auxiliary_request") is None


@pytest.mark.asyncio
async def test_tool_title_requests_are_not_rewritten_before_preparer(
    request_processor: RequestProcessor,
    request_context: RequestContext,
    mock_app_state: IApplicationState,
    mock_session_enricher,
    mock_backend_executor,
) -> None:
    """Tool-generated titles should route even when assistant/tool messages are present."""

    cast(Any, mock_app_state).get_setting.return_value = MagicMock(
        auxiliary_routing=MagicMock(
            enabled=True,
            backend="openrouter",
            model="openrouter/free",
            detection_patterns=[
                r"Generate a (?:short |brief )?(?:title|summary|heading)"
            ],
            max_message_count=3,
        )
    )

    request = ChatRequest(
        model="qwen-oauth:qwen/coder-model",
        messages=[
            ChatMessage(role="system", content="You are a title generator."),
            ChatMessage(
                role="user", content="Generate a title for this tool execution:"
            ),
            ChatMessage(role="assistant", content="I'll run git status."),
            ChatMessage(role="tool", content="On branch dev\nmodified: src/app.py"),
            ChatMessage(role="user", content="Show working tree status"),
        ],
    )
    mock_session_enricher.enrich.return_value = (MagicMock(), request)

    await request_processor.process_request(request_context, request)

    call_args = mock_backend_executor.execute.call_args
    assert call_args is not None
    called_request = call_args.args[3]
    assert called_request.model == "qwen-oauth:qwen/coder-model"
    assert request_context.extensions.get("auxiliary_request") is None


@pytest.mark.asyncio
async def test_system_prompt_title_requests_are_not_rewritten_before_preparer(
    request_processor: RequestProcessor,
    request_context: RequestContext,
    mock_app_state: IApplicationState,
    mock_session_enricher,
    mock_backend_executor,
) -> None:
    """OpenCode may send only the topic as user content for generated titles."""

    cast(Any, mock_app_state).get_setting.return_value = MagicMock(
        auxiliary_routing=MagicMock(
            enabled=True,
            backend="openrouter",
            model="openrouter/free",
            detection_patterns=[
                r"Generate a (?:short |brief )?(?:title|summary|heading)",
                r"\btitle generator\b",
            ],
            max_message_count=3,
        )
    )

    request = ChatRequest(
        model="qwen-oauth:qwen/coder-model",
        messages=[
            ChatMessage(role="system", content="You are a title generator."),
            ChatMessage(role="user", content="Show working tree status"),
        ],
    )
    mock_session_enricher.enrich.return_value = (MagicMock(), request)

    await request_processor.process_request(request_context, request)

    call_args = mock_backend_executor.execute.call_args
    assert call_args is not None
    called_request = call_args.args[3]
    assert called_request.model == "qwen-oauth:qwen/coder-model"
    assert request_context.extensions.get("auxiliary_request") is None


@pytest.mark.asyncio
async def test_streaming_tool_registry_failure_does_not_block_request(
    mock_command_processor: ICommandProcessor,
    mock_session_manager: ISessionManager,
    mock_backend_request_manager: IBackendRequestManager,
    mock_response_manager: IResponseManager,
    mock_app_state: IApplicationState,
    mock_session_enricher,
    mock_command_handler,
    mock_backend_preparer,
    mock_transform_pipeline,
    mock_backend_executor,
    request_context: RequestContext,
) -> None:
    request = ChatRequest(
        model="gpt-4",
        messages=[ChatMessage(role="user", content="Hello")],
        tools=[{"function": {"name": "test_tool"}}],
    )

    from unittest.mock import patch

    from src.core.services.request_side_effects import RequestSideEffects

    side_effects = RequestSideEffects()
    processor = RequestProcessor(
        command_processor=mock_command_processor,
        session_manager=mock_session_manager,
        backend_request_manager=mock_backend_request_manager,
        response_manager=mock_response_manager,
        session_enricher=mock_session_enricher,
        request_side_effects=side_effects,
        command_handler=mock_command_handler,
        backend_preparer=mock_backend_preparer,
        transform_pipeline=mock_transform_pipeline,
        backend_executor=mock_backend_executor,
        app_state=mock_app_state,
    )

    with patch(
        "src.core.services.streaming.stream_context_registry.get_global_streaming_context_registry",
        side_effect=RuntimeError("Registry unavailable"),
    ):
        response = await processor.process_request(request_context, request)

    assert response is not None
    assert isinstance(response, ResponseEnvelope)


@pytest.mark.asyncio
async def test_context_injection_failure_does_not_block_request(
    mock_command_processor: ICommandProcessor,
    mock_session_manager: ISessionManager,
    mock_backend_request_manager: IBackendRequestManager,
    mock_response_manager: IResponseManager,
    mock_app_state: IApplicationState,
    mock_session_enricher,
    mock_command_handler,
    mock_backend_preparer,
    mock_transform_pipeline,
    mock_backend_executor,
    request_context: RequestContext,
) -> None:
    request = ChatRequest(
        model="gpt-4", messages=[ChatMessage(role="user", content="Hello")]
    )

    from src.core.memory.injection_middleware import ContextInjectionMiddleware
    from src.core.services.request_side_effects import RequestSideEffects

    failing_injector = AsyncMock(spec=ContextInjectionMiddleware)
    failing_injector.maybe_inject_context.side_effect = RuntimeError("Injection failed")

    side_effects = RequestSideEffects(context_injector=failing_injector)
    processor = RequestProcessor(
        command_processor=mock_command_processor,
        session_manager=mock_session_manager,
        backend_request_manager=mock_backend_request_manager,
        response_manager=mock_response_manager,
        session_enricher=mock_session_enricher,
        request_side_effects=side_effects,
        command_handler=mock_command_handler,
        backend_preparer=mock_backend_preparer,
        transform_pipeline=mock_transform_pipeline,
        backend_executor=mock_backend_executor,
        app_state=mock_app_state,
    )

    response = await processor.process_request(request_context, request)
    assert response is not None
    assert isinstance(response, ResponseEnvelope)


@pytest.mark.asyncio
async def test_memory_capture_failure_does_not_block_request(
    mock_command_processor: ICommandProcessor,
    mock_session_manager: ISessionManager,
    mock_backend_request_manager: IBackendRequestManager,
    mock_response_manager: IResponseManager,
    mock_app_state: IApplicationState,
    mock_session_enricher,
    mock_command_handler,
    mock_backend_preparer,
    mock_transform_pipeline,
    mock_backend_executor,
    request_context: RequestContext,
) -> None:
    request = ChatRequest(
        model="gpt-4", messages=[ChatMessage(role="user", content="Hello")]
    )

    from src.core.memory.capture_middleware import MemoryCaptureMiddleware
    from src.core.services.request_side_effects import RequestSideEffects

    failing_capture = AsyncMock(spec=MemoryCaptureMiddleware)
    failing_capture.capture_request.side_effect = RuntimeError("Capture failed")

    side_effects = RequestSideEffects(memory_capture=failing_capture)
    processor = RequestProcessor(
        command_processor=mock_command_processor,
        session_manager=mock_session_manager,
        backend_request_manager=mock_backend_request_manager,
        response_manager=mock_response_manager,
        session_enricher=mock_session_enricher,
        request_side_effects=side_effects,
        command_handler=mock_command_handler,
        backend_preparer=mock_backend_preparer,
        transform_pipeline=mock_transform_pipeline,
        backend_executor=mock_backend_executor,
        app_state=mock_app_state,
    )

    response = await processor.process_request(request_context, request)
    assert response is not None
    assert isinstance(response, ResponseEnvelope)


@pytest.mark.asyncio
async def test_token_limit_enforcement_unexpected_error_does_not_block_request(
    mock_command_processor: ICommandProcessor,
    mock_session_manager: ISessionManager,
    mock_backend_request_manager: IBackendRequestManager,
    mock_response_manager: IResponseManager,
    mock_session_enricher,
    mock_request_side_effects,
    mock_command_handler,
    mock_transform_pipeline,
    mock_backend_executor,
    request_context: RequestContext,
) -> None:
    request = ChatRequest(
        model="gpt-4", messages=[ChatMessage(role="user", content="Hello")]
    )

    from unittest.mock import patch

    from src.core.services.backend_preparer import BackendPreparer

    app_state = MagicMock()
    app_state.get_model_defaults.return_value = {
        "gpt-4": {"context_window": 10, "max_input_tokens": 10}
    }
    app_state.get_backend_type.return_value = ""

    backend_preparer = BackendPreparer(
        backend_request_manager=mock_backend_request_manager, app_state=app_state
    )

    processor = RequestProcessor(
        command_processor=mock_command_processor,
        session_manager=mock_session_manager,
        backend_request_manager=mock_backend_request_manager,
        response_manager=mock_response_manager,
        session_enricher=mock_session_enricher,
        request_side_effects=mock_request_side_effects,
        command_handler=mock_command_handler,
        backend_preparer=backend_preparer,
        transform_pipeline=mock_transform_pipeline,
        backend_executor=mock_backend_executor,
        app_state=app_state,
    )

    with patch(
        "src.core.services.backend_preparer.count_tokens",
        side_effect=RuntimeError("Tokenizer failed"),
    ):
        response = await processor.process_request(request_context, request)

    assert response is not None
    assert isinstance(response, ResponseEnvelope)


@pytest.mark.asyncio
async def test_redaction_unexpected_failure_does_not_block_request(
    request_context: RequestContext,
) -> None:
    request = ChatRequest(
        model="gpt-4",
        messages=[ChatMessage(role="user", content="Hello")],
    )

    session = MagicMock()
    session.state = MagicMock()
    session.state.api_key_redaction_enabled = None
    session.state.command_prefix_override = None

    app_config = MagicMock()
    app_config.auth = MagicMock()
    app_config.auth.redact_api_keys_in_prompts = True
    app_config.command_prefix = "!/"

    app_state = MagicMock()

    def get_setting_side_effect(key: str, default: Any | None = None) -> Any | None:
        if key == "app_config":
            return app_config
        return default

    app_state.get_setting.side_effect = get_setting_side_effect
    app_state.get_command_prefix.return_value = "!/"
    app_state.get_disable_commands.return_value = False

    from unittest.mock import patch

    from src.core.services.request_transform_pipeline import RequestTransformPipeline

    pipeline = RequestTransformPipeline(app_state=app_state)

    with patch(
        "src.core.services.redaction_middleware.RedactionMiddleware.process",
        side_effect=RuntimeError("Redaction blew up"),
    ):
        pipeline._apply_edit_precision = AsyncMock(  # type: ignore[method-assign]
            side_effect=lambda *_args, **_kwargs: request
        )
        pipeline._apply_tool_filtering = AsyncMock(  # type: ignore[method-assign]
            side_effect=lambda *_args, **_kwargs: request
        )
        transformed = await pipeline.transform(
            request_context, session, "test-session", request
        )

    assert transformed == request


@pytest.mark.asyncio
async def test_transformation_ordering_redaction_before_edit_precision(
    request_context: RequestContext,
) -> None:
    from src.core.services.request_transform_pipeline import RequestTransformPipeline

    pipeline = RequestTransformPipeline(app_state=MagicMock())
    request = ChatRequest(
        model="gpt-4",
        messages=[ChatMessage(role="user", content="Hello")],
    )

    order: list[str] = []

    async def redaction(ctx, sess, sid, req):
        order.append("redaction")
        return req

    async def edit_precision(ctx, sess, sid, req):
        order.append("edit_precision")
        return req

    async def tool_filtering(ctx, sess, sid, req):
        order.append("tool_filtering")
        return req

    pipeline._apply_redaction = AsyncMock(side_effect=redaction)  # type: ignore[method-assign]
    pipeline._apply_edit_precision = AsyncMock(  # type: ignore[method-assign]
        side_effect=edit_precision
    )
    pipeline._apply_tool_filtering = AsyncMock(  # type: ignore[method-assign]
        side_effect=tool_filtering
    )

    await pipeline.transform(request_context, MagicMock(), "sid", request)
    assert order == ["redaction", "edit_precision", "tool_filtering"]


@pytest.mark.asyncio
async def test_transformation_ordering_tool_filtering_last(
    request_context: RequestContext,
) -> None:
    from src.core.services.request_transform_pipeline import RequestTransformPipeline

    pipeline = RequestTransformPipeline(app_state=MagicMock())
    request = ChatRequest(
        model="gpt-4",
        messages=[ChatMessage(role="user", content="Hello")],
    )

    order: list[str] = []

    async def redaction(ctx, sess, sid, req):
        order.append("redaction")
        return req

    async def edit_precision(ctx, sess, sid, req):
        order.append("edit_precision")
        return req

    async def tool_filtering(ctx, sess, sid, req):
        order.append("tool_filtering")
        return req

    pipeline._apply_redaction = AsyncMock(side_effect=redaction)  # type: ignore[method-assign]
    pipeline._apply_edit_precision = AsyncMock(  # type: ignore[method-assign]
        side_effect=edit_precision
    )
    pipeline._apply_tool_filtering = AsyncMock(  # type: ignore[method-assign]
        side_effect=tool_filtering
    )

    await pipeline.transform(request_context, MagicMock(), "sid", request)
    assert order[-1] == "tool_filtering"


@pytest.mark.asyncio
async def test_project_directory_resolution_failure_does_not_block_request() -> None:
    from src.core.services.session_enricher import SessionEnricher

    session_manager = AsyncMock(spec=ISessionManager)
    session_manager.resolve_session_id.return_value = "sid"

    session = MagicMock(spec=Session)
    session.agent = None
    session.state = MagicMock()
    session.state.client_os = None
    session.state.vtc_enabled = True
    session.state.project_dir_resolution_attempted = False
    session.update_state = MagicMock()

    session_manager.get_session.return_value = session
    session_manager.update_session_agent.return_value = session

    project_dir_service = AsyncMock()
    project_dir_service.maybe_resolve_project_directory.side_effect = RuntimeError(
        "Directory resolution failed"
    )

    app_state = MagicMock()
    app_state.get_service.return_value = project_dir_service

    enricher = SessionEnricher(session_manager=session_manager, app_state=app_state)

    context = RequestContext(headers={}, cookies={}, state={}, app_state=MagicMock())
    request = ChatRequest(
        model="gpt-4", messages=[ChatMessage(role="user", content="Hello")]
    )

    session_out, request_out = await enricher.enrich(context, request)

    assert session_out is session
    assert isinstance(request_out, ChatRequest)
    assert request_out.model == request.model
    assert list(request_out.messages) == list(request.messages)
