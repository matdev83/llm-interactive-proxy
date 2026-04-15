"""Basic RequestProcessor happy-path coverage."""

from unittest.mock import AsyncMock

import pytest
from src.core.domain.processed_result import ProcessedResult
from src.core.domain.responses import ResponseEnvelope
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
    session_manager.apply_openai_codex_history_compaction_gate = AsyncMock()

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
