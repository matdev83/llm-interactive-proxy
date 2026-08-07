"""
Tests for requested_model tracking in RequestProcessor and RequestContext.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.processed_result import ProcessedResult
from src.core.domain.replacement_state import ReplacementState
from src.core.domain.request_context import RequestContext
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.interfaces.domain_entities_interface import ISessionState
from src.core.interfaces.model_replacement_service_interface import (
    IModelReplacementService,
)
from src.core.interfaces.request_processor_internal import (
    IBackendExecutor,
    IBackendPreparer,
    ICommandHandler,
    IRequestSideEffects,
    IRequestTransformPipeline,
    ISessionEnricher,
)
from src.core.services.request_processor_service import RequestProcessor

from tests.unit.core.test_doubles import (
    MockCommandProcessor,
    TestDataBuilder,
)


class MockRequestContext(RequestContext):
    """Mock RequestContext for testing."""

    def __init__(
        self,
        headers: dict[str, str] | None = None,
        cookies: dict[str, str] | None = None,
        session_id: str | None = None,
        backend: str | None = None,
        effective_model: str | None = None,
        requested_model: str | None = None,
    ) -> None:
        mock_app_state = MagicMock(spec=IApplicationState)
        mock_app_state.force_set_project = False
        mock_app_state.disable_commands = False
        mock_app_state.disable_interactive_commands = False
        mock_app_state.failover_routes = {}
        mock_app_state.is_cline_agent = False

        super().__init__(
            headers=headers or {},
            cookies=cookies or {},
            state=MagicMock(spec=ISessionState),
            app_state=mock_app_state,
            client_host="127.0.0.1",
            original_request=None,
            backend=backend,
            effective_model=effective_model,
            requested_model=requested_model,
        )
        self.session_id = session_id


def create_mock_request(
    model: str = "gpt-4",
    messages: list[ChatMessage] | None = None,
) -> ChatRequest:
    if messages is None:
        messages = [ChatMessage(role="user", content="Hello")]
    return ChatRequest(
        model=model,
        messages=messages,
    )


def create_request_processor_mocks(
    request_data: ChatRequest | None = None,
) -> tuple[
    ISessionEnricher,
    IRequestSideEffects,
    ICommandHandler,
    IBackendPreparer,
    IRequestTransformPipeline,
    IBackendExecutor,
]:
    request = request_data or create_mock_request()

    session_enricher = AsyncMock(spec=ISessionEnricher)
    mock_session = AsyncMock(id="test-session", agent=None)
    session_enricher.enrich.return_value = (mock_session, request)

    request_side_effects = AsyncMock(spec=IRequestSideEffects)
    request_side_effects.apply.return_value = request

    command_handler = AsyncMock(spec=ICommandHandler)
    command_handler.handle.return_value = ProcessedResult(
        modified_messages=request.messages,
        command_executed=False,
        command_results=[],
    )

    backend_preparer = AsyncMock(spec=IBackendPreparer)
    backend_preparer.prepare.return_value = request

    transform_pipeline = AsyncMock(spec=IRequestTransformPipeline)
    transform_pipeline.transform.return_value = request

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


@pytest.mark.asyncio
async def test_request_processor_populates_requested_model() -> None:
    """Test that RequestProcessor populates requested_model in context."""
    # Arrange
    command_processor = MockCommandProcessor()
    session_manager = AsyncMock()
    backend_request_manager = AsyncMock()
    response_manager = AsyncMock()

    session_manager.resolve_session_id.return_value = "test-session"
    session_manager.get_session.return_value = AsyncMock(id="test-session")

    original_model = "original-model"
    # Use explicit backend prefix to ensure original_backend is resolved
    request_data = create_mock_request(model=f"backend:{original_model}")

    (
        session_enricher,
        request_side_effects,
        command_handler,
        backend_preparer,
        transform_pipeline,
        backend_executor,
    ) = create_request_processor_mocks(request_data)

    # Mock replacement service to simulate active replacement
    replacement_service = AsyncMock(spec=IModelReplacementService)
    replacement_service.should_replace.return_value = True
    replacement_service.get_state.return_value = ReplacementState(active=True)
    replacement_service.get_effective_backend_model.return_value = (
        "replacement-backend",
        "replacement-model",
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
        replacement_service=replacement_service,
    )

    # Use a context where requested_model is initially None
    context = MockRequestContext(session_id="test-session")
    assert context.requested_model is None

    # Act
    await processor.process_request(context, request_data)

    # Assert
    # 1. requested_model should correspond to the original request
    assert context.requested_model == original_model

    # 2. effective_model should correspond to the replacement
    assert context.effective_model == "replacement-model"
    assert context.backend == "replacement-backend"

    # 3. Context propagation check (ensure with_processing_context copies it)
    new_context = context.with_processing_context(foo="bar")
    assert new_context.requested_model == original_model


@pytest.mark.asyncio
async def test_request_processor_populates_requested_model_without_replacement() -> (
    None
):
    """Test that requested_model is populated even when no replacement occurs."""
    command_processor = MockCommandProcessor()
    session_manager = AsyncMock()
    backend_request_manager = AsyncMock()
    response_manager = AsyncMock()

    session_manager.resolve_session_id.return_value = "test-session"
    session_manager.get_session.return_value = AsyncMock(id="test-session")

    original_model = "original-model"
    request_data = create_mock_request(model=original_model)

    (
        session_enricher,
        request_side_effects,
        command_handler,
        backend_preparer,
        transform_pipeline,
        backend_executor,
    ) = create_request_processor_mocks(request_data)

    # No replacement service
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
        replacement_service=None,
    )

    context = MockRequestContext(session_id="test-session")
    assert context.requested_model is None

    await processor.process_request(context, request_data)

    assert context.requested_model == original_model
    assert context.effective_model == original_model
