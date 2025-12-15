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

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.processed_result import ProcessedResult
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ProcessedResponse, ResponseEnvelope
from src.core.domain.session import Session
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.interfaces.backend_request_manager_interface import IBackendRequestManager
from src.core.interfaces.command_processor_interface import ICommandProcessor
from src.core.interfaces.response_manager_interface import IResponseManager
from src.core.interfaces.session_manager_interface import ISessionManager
from src.core.services.request_processor_service import RequestProcessor
from src.core.services.tool_access_policy_service import ToolAccessPolicyService


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

    return mock


@pytest.fixture
def mock_backend_request_manager() -> IBackendRequestManager:
    """Create a mock backend request manager."""
    mock = AsyncMock(spec=IBackendRequestManager)

    # Default: return a backend request
    async def prepare_backend_request(request, processed_result):
        return request

    mock.prepare_backend_request.side_effect = prepare_backend_request

    # Mock backend response
    response = ResponseEnvelope(
        content=ProcessedResponse(
            content="test response",
            usage={"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        ),
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
    preparer.prepare = AsyncMock(side_effect=lambda ctx, sid, req, cmd: req)
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

    executor = AsyncMock()
    executor.execute = AsyncMock(return_value=MagicMock())
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


# Test Requirement 1.1: Type checking behavior
@pytest.mark.asyncio
async def test_rejects_non_chat_request_with_type_error(
    request_processor: RequestProcessor,
    request_context: RequestContext,
) -> None:
    """
    Requirement 1.1: When process_request is called with non-ChatRequest,
    the Request Processor Service shall raise TypeError.

    This is a fail-fast behavior that must be preserved.
    """
    invalid_request = {"model": "gpt-4", "messages": []}

    with pytest.raises(TypeError, match="request_data must be of type ChatRequest"):
        await request_processor.process_request(request_context, invalid_request)


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


# Test Requirement 5.2: Streaming tool registry is fail-open
@pytest.mark.skip(reason="Streaming tool registry now handled in RequestSideEffects")
@pytest.mark.asyncio
async def test_streaming_tool_registry_failure_does_not_block_request(
    request_processor: RequestProcessor,
    request_context: RequestContext,
) -> None:
    """
    Requirement 5.2: When tool name registration fails,
    the Request Processor Service shall log a warning and proceed
    without blocking request processing.

    This is a fail-open behavior.
    """
    request = ChatRequest(
        model="gpt-4",
        messages=[ChatMessage(role="user", content="Hello")],
        tools=[{"function": {"name": "test_tool"}}],
    )

    # Mock the registry to fail
    with patch(
        "src.core.services.streaming.stream_context_registry.get_global_streaming_context_registry"
    ) as mock_registry:
        mock_registry.side_effect = RuntimeError("Registry unavailable")

        # Should not raise, should proceed with request
        response = await request_processor.process_request(request_context, request)

        # Verify we got a response
        assert response is not None
        assert isinstance(response, ResponseEnvelope)


# Test Requirement 5.4: Context injection is fail-open
@pytest.mark.skip(reason="Context injection now handled in RequestSideEffects")
@pytest.mark.asyncio
async def test_context_injection_failure_does_not_block_request(
    request_processor: RequestProcessor,
    request_context: RequestContext,
) -> None:
    """
    Requirement 5.4: When memory context injection fails,
    the Request Processor Service shall log a warning and proceed
    without blocking request processing.

    This is a fail-open behavior.
    """
    request = ChatRequest(
        model="gpt-4",
        messages=[ChatMessage(role="user", content="Hello")],
    )

    # Create a failing context injector
    mock_injector = AsyncMock()
    mock_injector.maybe_inject_context.side_effect = RuntimeError("Injection failed")

    processor_with_injector = RequestProcessor(
        command_processor=request_processor._command_processor,
        session_manager=request_processor._session_manager,
        backend_request_manager=request_processor._backend_request_manager,
        response_manager=request_processor._response_manager,
        app_state=request_processor._app_state,
        context_injector=mock_injector,
    )

    # Should not raise, should proceed with request
    response = await processor_with_injector.process_request(request_context, request)

    # Verify we got a response
    assert response is not None
    assert isinstance(response, ResponseEnvelope)


# Test Requirement 5.6: Memory capture is fail-open
@pytest.mark.skip(reason="Memory capture now handled in RequestSideEffects")
@pytest.mark.asyncio
async def test_memory_capture_failure_does_not_block_request(
    request_processor: RequestProcessor,
    request_context: RequestContext,
) -> None:
    """
    Requirement 5.6: When memory capture fails,
    the Request Processor Service shall log a warning and proceed
    without blocking request processing.

    This is a fail-open behavior.
    """
    request = ChatRequest(
        model="gpt-4",
        messages=[ChatMessage(role="user", content="Hello")],
    )

    # Create a failing memory capture
    mock_capture = AsyncMock()
    mock_capture.capture_request.side_effect = RuntimeError("Capture failed")

    processor_with_capture = RequestProcessor(
        command_processor=request_processor._command_processor,
        session_manager=request_processor._session_manager,
        backend_request_manager=request_processor._backend_request_manager,
        response_manager=request_processor._response_manager,
        app_state=request_processor._app_state,
        memory_capture=mock_capture,
    )

    # Should not raise, should proceed with request
    response = await processor_with_capture.process_request(request_context, request)

    # Verify we got a response
    assert response is not None
    assert isinstance(response, ResponseEnvelope)


# Test Requirement 8.5: Token limit enforcement is fail-open for unexpected errors
@pytest.mark.skip(reason="Token limit enforcement now handled in BackendPreparer")
@pytest.mark.asyncio
async def test_token_limit_enforcement_unexpected_error_does_not_block_request(
    request_processor: RequestProcessor,
    request_context: RequestContext,
    mock_app_state: IApplicationState,
) -> None:
    """
    Requirement 8.5: When validation encounters unexpected errors,
    the Request Processor Service shall treat enforcement as best-effort
    and proceed without blocking.

    This is a fail-open behavior for unexpected errors only.
    Structured InvalidRequestError should still propagate.
    """
    request = ChatRequest(
        model="gpt-4",
        messages=[ChatMessage(role="user", content="Hello")],
    )

    # Mock app_state to provide model defaults that will cause an error
    # during token counting (not during structured validation)
    mock_app_state.get_model_defaults.return_value = {  # type: ignore[attr-defined]
        "gpt-4": {"limits": {"max_input_tokens": 1000}}
    }

    # Mock token counting to fail unexpectedly
    with patch("src.core.utils.token_count.count_tokens") as mock_count:
        mock_count.side_effect = RuntimeError("Unexpected token counting error")

        # Should not raise, should proceed with request
        response = await request_processor.process_request(request_context, request)

        # Verify we got a response
        assert response is not None
        assert isinstance(response, ResponseEnvelope)


# Test Requirement 9.7: Request transformations are fail-open
@pytest.mark.skip(reason="Redaction now handled in RequestTransformPipeline")
@pytest.mark.asyncio
async def test_redaction_unexpected_failure_does_not_block_request(
    request_processor: RequestProcessor,
    request_context: RequestContext,
) -> None:
    """
    Requirement 9.7: When any request transformation step fails unexpectedly,
    the Request Processor Service shall log and proceed without blocking
    request processing.

    This tests redaction middleware failure as a representative transformation.
    """
    request = ChatRequest(
        model="gpt-4",
        messages=[ChatMessage(role="user", content="Hello")],
    )

    # Mock RedactionMiddleware to fail
    with patch(
        "src.core.services.redaction_middleware.RedactionMiddleware"
    ) as mock_redaction_cls:
        mock_instance = AsyncMock()
        mock_instance.process.side_effect = RuntimeError("Redaction system error")
        mock_redaction_cls.return_value = mock_instance

        # Should not raise, should proceed with request
        response = await request_processor.process_request(request_context, request)

        # Verify we got a response
        assert response is not None
        assert isinstance(response, ResponseEnvelope)


# Test Requirement 9.8: Transformation ordering is preserved
@pytest.mark.asyncio
@pytest.mark.xfail(
    reason=(
        "Mocks internal transformation ordering via middleware patching; since the "
        "RequestTransformPipeline extraction this test is brittle and hard to express "
        "at the RequestProcessor level. Ordering is verified by "
        "tests/unit/core/services/test_request_transform_pipeline.py."
    )
)
async def test_transformation_ordering_redaction_before_edit_precision(
    mock_command_processor: ICommandProcessor,
    mock_session_manager: ISessionManager,
    mock_backend_request_manager: IBackendRequestManager,
    mock_response_manager: IResponseManager,
    request_context: RequestContext,
    mock_app_state: IApplicationState,
) -> None:
    """
    Requirement 9.8: The request transformation pipeline shall preserve
    the current execution order: redaction, then edit precision, then tool filtering.

    This test verifies that redaction happens before edit precision.
    """
    # Import pipeline classes
    from src.core.services.request_transform_pipeline import RequestTransformPipeline

    # Create processor with real pipeline
    transform_pipeline = RequestTransformPipeline(app_state=mock_app_state)
    request_processor = RequestProcessor(
        command_processor=mock_command_processor,
        session_manager=mock_session_manager,
        backend_request_manager=mock_backend_request_manager,
        response_manager=mock_response_manager,
        app_state=mock_app_state,
        transform_pipeline=transform_pipeline,
    )

    request = ChatRequest(
        model="gpt-4",
        messages=[ChatMessage(role="user", content="Hello OPENAI_API_KEY=sk-test")],
    )

    # Track order of transformations
    transformation_order = []

    # Mock redaction within the pipeline
    with patch(
        "src.core.services.request_transform_pipeline.RedactionMiddleware"
    ) as mock_redaction_cls:
        redaction_instance = AsyncMock()

        async def redaction_process(req, ctx):
            transformation_order.append("redaction")
            return req

        redaction_instance.process.side_effect = redaction_process
        mock_redaction_cls.return_value = redaction_instance

        # Mock edit precision within the pipeline
        with patch(
            "src.core.services.request_transform_pipeline.EditPrecisionTuningMiddleware"
        ) as mock_precision_cls:
            precision_instance = AsyncMock()

            async def precision_process(req, ctx):
                transformation_order.append("edit_precision")
                return req

            precision_instance.process.side_effect = precision_process
            mock_precision_cls.return_value = precision_instance

            # Enable edit precision in config
            mock_config = MagicMock()
            mock_config.edit_precision = MagicMock()
            mock_config.edit_precision.enabled = True
            mock_config.edit_precision.temperature = 0.1
            mock_config.auth = MagicMock()
            mock_config.auth.redact_api_keys_in_prompts = True

            # Use side_effect to return different values for different keys
            def get_setting_side_effect(key: str, default=None):
                if key == "app_config":
                    return mock_config
                if key in (
                    "edit_precision_pending",
                    "edit_precision_hybrid_reasoning_disabled",
                ):
                    return {}
                return default

            mock_app_state.get_setting.side_effect = get_setting_side_effect  # type: ignore[attr-defined]

            await request_processor.process_request(request_context, request)

            # Verify ordering: redaction must come before edit_precision
            assert transformation_order == ["redaction", "edit_precision"]


# Test Requirement 9.8: Tool filtering happens after edit precision
@pytest.mark.asyncio
@pytest.mark.xfail(
    reason=(
        "Mocks internal transformation ordering via middleware patching; since the "
        "RequestTransformPipeline extraction this test is brittle and hard to express "
        "at the RequestProcessor level. Ordering is verified by "
        "tests/unit/core/services/test_request_transform_pipeline.py."
    )
)
async def test_transformation_ordering_tool_filtering_last(
    mock_command_processor: ICommandProcessor,
    mock_session_manager: ISessionManager,
    mock_backend_request_manager: IBackendRequestManager,
    mock_response_manager: IResponseManager,
    request_context: RequestContext,
    mock_app_state: IApplicationState,
) -> None:
    """
    Requirement 9.8: The request transformation pipeline shall preserve
    the current execution order: redaction, then edit precision, then tool filtering.

    This test verifies that tool filtering happens after edit precision.
    """
    # Import pipeline classes
    from src.core.services.request_transform_pipeline import RequestTransformPipeline

    # Create processor with real pipeline
    transform_pipeline = RequestTransformPipeline(app_state=mock_app_state)
    request_processor = RequestProcessor(
        command_processor=mock_command_processor,
        session_manager=mock_session_manager,
        backend_request_manager=mock_backend_request_manager,
        response_manager=mock_response_manager,
        app_state=mock_app_state,
        transform_pipeline=transform_pipeline,
    )

    request = ChatRequest(
        model="gpt-4",
        messages=[ChatMessage(role="user", content="Hello")],
        tools=[{"function": {"name": "test_tool"}}],
    )

    # Track order of transformations
    transformation_order = []

    # Mock edit precision within the pipeline
    with patch(
        "src.core.services.request_transform_pipeline.EditPrecisionTuningMiddleware"
    ) as mock_precision_cls:
        precision_instance = AsyncMock()

        async def precision_process(req, ctx):
            transformation_order.append("edit_precision")
            return req

        precision_instance.process.side_effect = precision_process
        mock_precision_cls.return_value = precision_instance

        # Mock tool filtering by providing a policy service
        mock_policy_service = MagicMock()
        mock_policy_service.filter_tool_definitions.return_value = ([], {})
        mock_policy_service._extract_tool_name.return_value = "test_tool"

        mock_app_state.get_service.side_effect = (  # type: ignore[attr-defined]
            lambda service_type: (
                mock_policy_service if service_type is ToolAccessPolicyService else None
            )
        )

        # Enable edit precision in config
        mock_config = MagicMock()
        mock_config.edit_precision = MagicMock()
        mock_config.edit_precision.enabled = True
        mock_config.edit_precision.temperature = 0.1
        mock_config.auth = MagicMock()
        mock_config.auth.redact_api_keys_in_prompts = True

        # Use side_effect to return different values for different keys
        def get_setting_side_effect(key: str, default: Any | None = None) -> Any | None:
            if key == "app_config":
                return mock_config
            if key in (
                "edit_precision_pending",
                "edit_precision_hybrid_reasoning_disabled",
            ):
                return {}
            return default

        mock_app_state.get_setting.side_effect = get_setting_side_effect  # type: ignore[attr-defined]

        await request_processor.process_request(request_context, request)

        # Verify ordering: edit_precision must come before tool_filtering
        assert "edit_precision" in transformation_order
        assert "tool_filtering" in transformation_order
        ep_index = transformation_order.index("edit_precision")
        tf_index = transformation_order.index("tool_filtering")
        assert ep_index < tf_index, "edit_precision must come before tool_filtering"


# Test: Project directory resolution is fail-open
@pytest.mark.skip(
    reason="Project directory resolution now handled in RequestSideEffects"
)
@pytest.mark.asyncio
async def test_project_directory_resolution_failure_does_not_block_request(
    request_processor: RequestProcessor,
    request_context: RequestContext,
    mock_app_state: IApplicationState,
) -> None:
    """
    Requirement 4.8: When project directory auto-resolution is eligible,
    the Request Processor Service shall attempt project directory resolution
    and shall not block request processing when resolution fails.

    This is a fail-open behavior.
    """
    request = ChatRequest(
        model="gpt-4",
        messages=[ChatMessage(role="user", content="Hello")],
    )

    # Mock project directory service to fail
    mock_service = AsyncMock()
    mock_service.maybe_resolve_project_directory.side_effect = RuntimeError(
        "Directory resolution failed"
    )
    mock_app_state.get_service.return_value = mock_service  # type: ignore[attr-defined]

    # Should not raise, should proceed with request
    response = await request_processor.process_request(request_context, request)

    # Verify we got a response
    assert response is not None
    assert isinstance(response, ResponseEnvelope)
