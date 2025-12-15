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

from unittest.mock import AsyncMock, MagicMock

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


# NOTE: Skipped tests removed - covered by component-level tests:
# - test_streaming_tool_registry_failure_does_not_block_request -> test_request_side_effects.py
# - test_context_injection_failure_does_not_block_request -> test_request_side_effects.py
# - test_memory_capture_failure_does_not_block_request -> test_request_side_effects.py
# - test_token_limit_enforcement_unexpected_error_does_not_block_request -> test_backend_preparer.py
# - test_redaction_unexpected_failure_does_not_block_request -> test_request_transform_pipeline.py
# - test_project_directory_resolution_failure_does_not_block_request -> test_session_enricher.py


# NOTE: xfail tests removed - transformation ordering is an internal implementation
# detail of RequestTransformPipeline and is properly tested at the component level:
# - test_transformation_ordering_redaction_before_edit_precision -> test_request_transform_pipeline.py::test_transform_pipeline_preserves_ordering
# - test_transformation_ordering_tool_filtering_last -> test_request_transform_pipeline.py::test_transform_pipeline_preserves_ordering
