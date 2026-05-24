"""
Shared fixtures for RequestProcessor tests after refactoring.

These fixtures provide mocked component dependencies for testing RequestProcessor
with the new decomposed architecture.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.domain.processed_result import ProcessedResult
from src.core.domain.session import Session


@pytest.fixture
def mock_session_enricher():
    """Mock ISessionEnricher that returns a valid session and request."""
    enricher = AsyncMock()

    def enrich_side_effect(context, request_data):
        # Return a mock session and the request data
        mock_session = MagicMock(spec=Session)
        mock_session.id = "test-session-123"
        mock_session.agent = None
        mock_session.state = MagicMock()
        return (mock_session, request_data)

    enricher.enrich = AsyncMock(side_effect=enrich_side_effect)
    return enricher


@pytest.fixture
def mock_request_side_effects():
    """Mock IRequestSideEffects that passes through the request."""
    side_effects = AsyncMock()
    side_effects.apply = AsyncMock(side_effect=lambda ctx, sid, req: req)
    return side_effects


@pytest.fixture
def mock_command_handler():
    """Mock ICommandHandler that returns a ProcessedResult."""
    handler = AsyncMock()

    def handle_side_effect(context, session, session_id, request_data):
        # Return a ProcessedResult (not a response envelope) to continue to backend
        return ProcessedResult(
            command_executed=False,
            modified_messages=[],
            command_results=[],
        )

    handler.handle = AsyncMock(side_effect=handle_side_effect)
    return handler


@pytest.fixture
def mock_backend_preparer():
    """Mock IBackendPreparer that returns the request as backend request."""
    preparer = AsyncMock()
    preparer.prepare = AsyncMock(side_effect=lambda ctx, sid, req, cmd: req)
    return preparer


@pytest.fixture
def mock_transform_pipeline():
    """Mock IRequestTransformPipeline that passes through the request."""
    pipeline = AsyncMock()
    pipeline.transform = AsyncMock(side_effect=lambda ctx, sess, sid, req: req)
    return pipeline


@pytest.fixture
def mock_backend_executor():
    """Mock IBackendExecutor that returns a mock response."""
    executor = AsyncMock()
    executor.execute = AsyncMock(return_value=MagicMock())
    return executor


@pytest.fixture
def request_processor_with_mocks(
    mock_command_processor,
    mock_session_manager,
    mock_backend_request_manager,
    mock_response_manager,
    mock_session_enricher,
    mock_request_side_effects,
    mock_command_handler,
    mock_backend_preparer,
    mock_transform_pipeline,
    mock_backend_executor,
):
    """Create a fully-mocked RequestProcessor for testing."""
    from src.core.services.request_processor_service import RequestProcessor

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
    )
