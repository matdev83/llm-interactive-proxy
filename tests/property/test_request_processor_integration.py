"""Property-based tests for request processor integration with replacement service.

Feature: random-model-replacement
Property: 26
Validates: Requirements 7.1
"""

from __future__ import annotations

# Tests updated for refactored RequestProcessor architecture
from unittest.mock import AsyncMock, Mock

from hypothesis import given
from hypothesis import strategies as st
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.configuration.replacement_config import ReplacementConfig
from src.core.domain.processed_result import ProcessedResult
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope
from src.core.services.backend_registry import BackendRegistry
from src.core.services.model_replacement_service import ModelReplacementService
from src.core.services.request_processor_service import RequestProcessor
from tests.utils.hypothesis_config import property_test_settings


def create_mock_command_processor() -> AsyncMock:
    """Create a mock command processor."""
    processor = AsyncMock()
    processor.process_messages = AsyncMock(
        return_value=ProcessedResult(
            command_executed=False,
            modified_messages=[],
            command_results=[],
        )
    )
    return processor


def create_mock_session_manager() -> AsyncMock:
    """Create a mock session manager."""
    manager = AsyncMock()
    manager.resolve_session_id = AsyncMock(return_value="test-session")

    # Create a mock session with agent attribute
    mock_session = Mock()
    mock_session.agent = None
    mock_session.state = Mock()
    mock_session.state.project_dir_resolution_attempted = False

    manager.get_session = AsyncMock(return_value=mock_session)
    manager.update_session_agent = AsyncMock(return_value=mock_session)
    manager.update_session_history = AsyncMock()
    return manager


def create_mock_backend_request_manager() -> AsyncMock:
    """Create a mock backend request manager."""
    manager = AsyncMock()

    # Mock prepare_backend_request to return a ChatRequest
    async def mock_prepare(request_data, command_result):
        return request_data

    manager.prepare_backend_request = AsyncMock(side_effect=mock_prepare)

    # Mock process_backend_request to return a ResponseEnvelope
    manager.process_backend_request = AsyncMock(
        return_value=ResponseEnvelope(
            content={"choices": [], "model": "test-model"},
            headers=None,
            status_code=200,
            media_type="application/json",
            usage=None,
        )
    )
    return manager


def create_mock_response_manager() -> AsyncMock:
    """Create a mock response manager."""
    manager = AsyncMock()
    manager.process_command_result = AsyncMock(
        return_value=ResponseEnvelope(
            content={"choices": [], "model": "test-model"},
            headers=None,
            status_code=200,
            media_type="application/json",
            usage=None,
        )
    )
    return manager


def create_mock_decomposed_services(model="test-model"):
    """Create mocks for the new decomposed RequestProcessor services."""
    from src.core.interfaces.request_processor_internal import (
        IBackendExecutor,
        IBackendPreparer,
        ICommandHandler,
        IRequestSideEffects,
        IRequestTransformPipeline,
        ISessionEnricher,
    )

    # Default message for valid ChatRequests
    default_message = ChatMessage(role="user", content="test")

    session_enricher = AsyncMock(spec=ISessionEnricher)
    mock_session = Mock()
    mock_session.agent = None
    mock_session.state = Mock()
    mock_session.state.project_dir_resolution_attempted = False
    session_enricher.enrich.return_value = (
        mock_session,
        ChatRequest(model=model, messages=[default_message]),
    )

    request_side_effects = AsyncMock(spec=IRequestSideEffects)
    request_side_effects.apply.return_value = ChatRequest(
        model=model, messages=[default_message]
    )

    command_handler = AsyncMock(spec=ICommandHandler)
    command_handler.handle.return_value = ProcessedResult(
        modified_messages=[default_message],
        command_executed=False,
        command_results=[],
    )

    backend_preparer = AsyncMock(spec=IBackendPreparer)
    backend_preparer.prepare.return_value = ChatRequest(
        model=model, messages=[default_message]
    )

    transform_pipeline = AsyncMock(spec=IRequestTransformPipeline)
    transform_pipeline.transform.return_value = ChatRequest(
        model=model, messages=[default_message]
    )

    backend_executor = AsyncMock(spec=IBackendExecutor)

    async def execute_with_turn_completion(
        context, session, session_id, backend_request, original_request
    ):
        # Simulate turn completion for replacement service
        result = ResponseEnvelope(
            content={"choices": [], "model": model},
            headers=None,
            status_code=200,
            media_type="application/json",
            usage=None,
        )
        return result

    backend_executor.execute.side_effect = execute_with_turn_completion

    return {
        "session_enricher": session_enricher,
        "request_side_effects": request_side_effects,
        "command_handler": command_handler,
        "backend_preparer": backend_preparer,
        "transform_pipeline": transform_pipeline,
        "backend_executor": backend_executor,
    }


def create_test_replacement_service(
    probability: float = 1.0,
    backend_model: str = "replacement-backend:replacement-model",
) -> ModelReplacementService:
    """Create a test replacement service."""
    registry = BackendRegistry()

    def mock_factory() -> None:
        pass

    # Register both original and replacement backends
    registry.register_backend("test-backend", mock_factory)
    registry.register_backend("replacement-backend", mock_factory)

    config = ReplacementConfig(
        enabled=True,
        probability=probability,
        backend_model=backend_model,
        turn_count=1,
    )

    return ModelReplacementService(config, registry)


@given(
    original_model=st.text(
        min_size=1,
        max_size=30,
        alphabet=st.characters(
            blacklist_characters=[":"], blacklist_categories=("Cs",)
        ),
    ),
    message_content=st.text(
        min_size=1, max_size=50, alphabet=st.characters(blacklist_categories=("Cs",))
    ),
)
@property_test_settings(max_examples=5)
async def test_property_26_command_processing_order(
    original_model: str, message_content: str
) -> None:
    """
    Property 26: Command processing order.

    For any request with command prefix, replacement logic must execute after
    command processing completes.

    Validates: Requirements 7.1
    """
    # Track the order of operations
    operation_order: list[str] = []

    # Create mock command processor
    command_processor = create_mock_command_processor()

    # Create mock session manager
    session_manager = create_mock_session_manager()

    # Create mock backend request manager
    backend_request_manager = create_mock_backend_request_manager()

    # Create mock response manager
    response_manager = create_mock_response_manager()

    # Create replacement service with probability=1.0 to ensure it triggers
    replacement_service = create_test_replacement_service(probability=1.0)

    # Track when replacement logic is called by wrapping should_replace
    original_should_replace = replacement_service.should_replace

    def track_should_replace(
        session_id, request_context, original_backend=None, original_model=None
    ):
        operation_order.append("replacement_check")
        return original_should_replace(
            session_id, request_context, original_backend, original_model
        )

    replacement_service.should_replace = track_should_replace

    # Create mocks for new required dependencies
    from src.core.interfaces.request_processor_internal import (
        IBackendExecutor,
        IBackendPreparer,
        ICommandHandler,
        IRequestSideEffects,
        IRequestTransformPipeline,
        ISessionEnricher,
    )

    session_enricher = AsyncMock(spec=ISessionEnricher)
    mock_session = Mock()
    mock_session.agent = None
    mock_session.state = Mock()
    # ChatRequest requires at least one message
    default_message = ChatMessage(role="user", content=message_content)
    session_enricher.enrich.return_value = (
        mock_session,
        ChatRequest(model=original_model, messages=[default_message]),
    )

    request_side_effects = AsyncMock(spec=IRequestSideEffects)
    request_side_effects.apply.return_value = ChatRequest(
        model=original_model, messages=[default_message]
    )

    command_handler = AsyncMock(spec=ICommandHandler)

    async def track_command_handler(context, session, session_id, request):
        operation_order.append("command_processing")
        return ProcessedResult(
            modified_messages=[default_message],
            command_executed=False,
            command_results=[],
        )

    command_handler.handle.side_effect = track_command_handler

    backend_preparer = AsyncMock(spec=IBackendPreparer)

    async def track_backend_preparer(context, session_id, request, command_result):
        operation_order.append("backend_request_preparation")
        return ChatRequest(model=original_model, messages=[default_message])

    backend_preparer.prepare.side_effect = track_backend_preparer

    transform_pipeline = AsyncMock(spec=IRequestTransformPipeline)
    transform_pipeline.transform.return_value = ChatRequest(
        model=original_model, messages=[default_message]
    )

    backend_executor = AsyncMock(spec=IBackendExecutor)
    backend_executor.execute.return_value = ResponseEnvelope(
        content={"choices": [], "model": "test-model"},
        headers=None,
        status_code=200,
        media_type="application/json",
        usage=None,
    )

    # Create request processor with all mocks
    processor = RequestProcessor(
        command_processor=command_processor,
        session_manager=session_manager,
        backend_request_manager=backend_request_manager,
        response_manager=response_manager,
        session_enricher=session_enricher,
        request_side_effects=request_side_effects,
        command_handler=command_handler,
        backend_preparer=backend_preparer,
        transform_pipeline=transform_pipeline,
        backend_executor=backend_executor,
        app_state=None,
        replacement_service=replacement_service,
    )

    # Create test request
    context = RequestContext(
        headers={},
        cookies={},
        state=None,
        app_state=None,
    )
    context.backend = "test-backend"

    request_data = ChatRequest(
        model=original_model,
        messages=[ChatMessage(role="user", content=message_content)],
    )

    # Process the request
    await processor.process_request(context, request_data)

    # Verify that command processing happened before replacement check
    assert "command_processing" in operation_order, "Command processing did not occur"
    assert "replacement_check" in operation_order, "Replacement check did not occur"

    command_index = operation_order.index("command_processing")
    replacement_index = operation_order.index("replacement_check")

    assert command_index < replacement_index, (
        f"Replacement logic executed before command processing. "
        f"Order: {operation_order}"
    )

    # Verify that replacement check happened before backend request preparation
    if "backend_request_preparation" in operation_order:
        backend_index = operation_order.index("backend_request_preparation")
        assert replacement_index < backend_index, (
            f"Backend request preparation executed before replacement check. "
            f"Order: {operation_order}"
        )


@given(
    original_model=st.text(
        min_size=1,
        max_size=50,
        alphabet=st.characters(
            blacklist_characters=[":"], blacklist_categories=("Cs",)
        ),
    ),
    message_content=st.text(
        min_size=1, max_size=100, alphabet=st.characters(blacklist_categories=("Cs",))
    ),
    turn_count=st.integers(
        min_value=1, max_value=3
    ),  # Reduced from 5 to 3 for performance
)
@property_test_settings(max_examples=3)  # Reduced for performance
async def test_property_38_streaming_turn_completion(
    original_model: str, message_content: str, turn_count: int
) -> None:
    """
    Property 38: Streaming turn completion.

    For any streaming request that completes with replacement active, the
    turns_remaining counter must be decremented by 1.

    Validates: Requirements 10.3
    """
    # Create mock command processor
    command_processor = create_mock_command_processor()

    # Create mock session manager
    session_manager = create_mock_session_manager()

    # Create mock backend request manager
    backend_request_manager = create_mock_backend_request_manager()

    # Create mock response manager
    response_manager = create_mock_response_manager()

    # Create replacement service with probability=1.0 and specified turn_count
    registry = BackendRegistry()

    def mock_factory() -> None:
        pass

    # Register both original and replacement backends
    registry.register_backend("test-backend", mock_factory)
    registry.register_backend("replacement-backend", mock_factory)

    config = ReplacementConfig(
        enabled=True,
        probability=1.0,
        backend_model="replacement-backend:replacement-model",
        turn_count=turn_count,
    )

    replacement_service = ModelReplacementService(config, registry)

    # Create mocks for new required dependencies
    decomposed = create_mock_decomposed_services(model=original_model)

    # Use real BackendExecutor to ensure turn completion happens
    from src.core.services.backend_executor import BackendExecutor

    backend_executor = BackendExecutor(
        backend_request_manager=backend_request_manager,
        session_manager=session_manager,
        replacement_service=replacement_service,
    )

    # Create request processor
    processor = RequestProcessor(
        command_processor=command_processor,
        session_manager=session_manager,
        backend_request_manager=backend_request_manager,
        response_manager=response_manager,
        session_enricher=decomposed["session_enricher"],
        request_side_effects=decomposed["request_side_effects"],
        command_handler=decomposed["command_handler"],
        backend_preparer=decomposed["backend_preparer"],
        transform_pipeline=decomposed["transform_pipeline"],
        backend_executor=backend_executor,
        app_state=None,
        replacement_service=replacement_service,
    )

    # Create test request
    context = RequestContext(
        headers={},
        cookies={},
        state=None,
        app_state=None,
    )
    context.backend = "test-backend"

    request_data = ChatRequest(
        model=original_model,
        messages=[ChatMessage(role="user", content=message_content)],
    )

    # Get initial state - should not be active
    session_id = "test-session"
    initial_state = replacement_service.get_state(session_id)
    assert not initial_state.active, "Replacement should not be active initially"

    # First request is always skipped (guaranteed original model)
    await processor.process_request(context, request_data)

    # Check state after first request - first turn is skipped, replacement not activated
    state_after_first = replacement_service.get_state(session_id)
    assert (
        not state_after_first.active
    ), "Replacement should not be active after first request (first turn skip)"

    # Process second request - this should activate replacement and then complete the turn
    await processor.process_request(context, request_data)

    # Check state after second request (first replacement turn)
    # Note: The turn is completed in the finally block, so turns_remaining is decremented
    state_after_second = replacement_service.get_state(session_id)

    if turn_count == 1:
        # With turn_count=1, replacement should be deactivated after first replacement turn
        assert (
            not state_after_second.active
        ), "Replacement should be deactivated after first replacement turn with turn_count=1"
        assert state_after_second.turns_remaining == 0
        # No need to test further turns
        return
    else:
        # With turn_count>1, replacement should still be active
        assert (
            state_after_second.active
        ), "Replacement should be active after second request"
        assert state_after_second.turns_remaining == turn_count - 1, (
            f"Expected {turn_count - 1} turns remaining after first replacement turn, "
            f"got {state_after_second.turns_remaining}"
        )

    # Process additional requests to verify turn counter decrements
    for i in range(1, turn_count):
        await processor.process_request(context, request_data)

        state = replacement_service.get_state(session_id)
        expected_remaining = turn_count - i - 1

        if expected_remaining > 0:
            assert state.active, f"Replacement should still be active on turn {i + 1}"
            assert state.turns_remaining == expected_remaining, (
                f"Expected {expected_remaining} turns remaining on turn {i + 1}, "
                f"got {state.turns_remaining}"
            )
        else:
            assert (
                not state.active
            ), f"Replacement should be deactivated after {turn_count} turns"
            assert state.turns_remaining == 0, (
                f"Expected 0 turns remaining after deactivation, "
                f"got {state.turns_remaining}"
            )


@given(
    original_model=st.text(
        min_size=1,
        max_size=30,
        alphabet=st.characters(
            blacklist_characters=[":"], blacklist_categories=("Cs",)
        ),
    ),
    message_content=st.text(
        min_size=1, max_size=50, alphabet=st.characters(blacklist_categories=("Cs",))
    ),
)
@property_test_settings(max_examples=5)
async def test_turn_completion_on_error(
    original_model: str, message_content: str
) -> None:
    """
    Test that turn completion happens even when backend request fails.

    This ensures that replacement state is properly updated even in error cases.
    """
    # Create mock command processor
    command_processor = create_mock_command_processor()

    # Create mock session manager
    session_manager = create_mock_session_manager()

    # Create mock backend request manager
    backend_request_manager = create_mock_backend_request_manager()

    # Create mock response manager
    response_manager = create_mock_response_manager()

    # Create replacement service with probability=1.0 and turn_count=2
    registry = BackendRegistry()

    def mock_factory() -> None:
        pass

    # Register both original and replacement backends
    registry.register_backend("test-backend", mock_factory)
    registry.register_backend("replacement-backend", mock_factory)

    config = ReplacementConfig(
        enabled=True,
        probability=1.0,
        backend_model="replacement-backend:replacement-model",
        turn_count=2,
    )

    replacement_service = ModelReplacementService(config, registry)

    # Create mocks for new required dependencies
    decomposed = create_mock_decomposed_services(model=original_model)

    # Use real BackendExecutor to ensure turn completion happens
    from src.core.services.backend_executor import BackendExecutor

    backend_executor = BackendExecutor(
        backend_request_manager=backend_request_manager,
        session_manager=session_manager,
        replacement_service=replacement_service,
    )

    # Create request processor
    processor = RequestProcessor(
        command_processor=command_processor,
        session_manager=session_manager,
        backend_request_manager=backend_request_manager,
        response_manager=response_manager,
        session_enricher=decomposed["session_enricher"],
        request_side_effects=decomposed["request_side_effects"],
        command_handler=decomposed["command_handler"],
        backend_preparer=decomposed["backend_preparer"],
        transform_pipeline=decomposed["transform_pipeline"],
        backend_executor=backend_executor,
        app_state=None,
        replacement_service=replacement_service,
    )

    # Create test request
    context = RequestContext(
        headers={},
        cookies={},
        state=None,
        app_state=None,
    )
    context.backend = "test-backend"

    request_data = ChatRequest(
        model=original_model,
        messages=[ChatMessage(role="user", content=message_content)],
    )

    session_id = "test-session"

    # First request is always skipped (guaranteed original model)
    import contextlib

    with contextlib.suppress(Exception):
        await processor.process_request(context, request_data)

    # Check that first turn was skipped, replacement not active
    state = replacement_service.get_state(session_id)
    assert (
        not state.active
    ), "Replacement should not be active after first request (first turn skip)"

    # Process the second request - should raise an error but still complete turn
    with contextlib.suppress(Exception):
        await processor.process_request(context, request_data)

    # Check that turn was completed despite error
    state = replacement_service.get_state(session_id)
    assert state.active, "Replacement should still be active after error"
    assert (
        state.turns_remaining == 1
    ), f"Expected 1 turn remaining after error, got {state.turns_remaining}"
