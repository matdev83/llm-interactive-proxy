from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.responses import ResponseEnvelope
from src.core.services.request_processor_service import RequestProcessor

from tests.helpers.backend_request_manager_fixtures import (
    create_backend_request_manager,
)


@pytest.mark.asyncio
async def test_top_p_fix_with_actual_request() -> None:
    """Test that demonstrates our fix works with a real request that includes top_p."""

    # Create mocks for dependencies
    from src.core.interfaces.command_processor_interface import ICommandProcessor

    mock_command_processor = MagicMock(spec=ICommandProcessor)
    mock_session_manager = AsyncMock()
    mock_backend_processor = MagicMock()
    mock_backend_processor.process_backend_request = AsyncMock()
    mock_response_processor = AsyncMock()
    from src.core.interfaces.response_processor_interface import ProcessedResponse

    mock_response_processor.process_response = AsyncMock(
        return_value=ProcessedResponse(content=None, metadata={})
    )
    backend_request_manager = create_backend_request_manager(
        backend_processor=mock_backend_processor,
        response_processor=mock_response_processor,
    )
    mock_response_manager = AsyncMock()

    # Configure session manager to return a real session object
    from src.core.domain.session import Session

    test_session = Session(session_id="test_session")
    mock_session_manager.resolve_session_id.return_value = "test_session"
    mock_session_manager.get_session.return_value = test_session
    mock_session_manager.update_session_agent.return_value = test_session

    # Configure mock_command_processor.process_messages as an AsyncMock
    mock_command_processor.process_messages = AsyncMock(
        return_value=MagicMock(
            modified_messages=[ChatMessage(role="user", content="Hello")],
            command_executed=False,
            command_results=[],
        )
    )

    # Configure mock_backend_request_manager to capture the request it receives
    captured_request: ChatRequest | None = None

    async def capture_request(*args: Any, **kwargs: Any) -> ResponseEnvelope:
        nonlocal captured_request
        captured_request = kwargs.get("request")
        if captured_request is None and args:
            captured_request = args[0]
        return ResponseEnvelope(
            content=None, headers={}, status_code=200, media_type="application/json"
        )

    mock_backend_processor.process_backend_request.side_effect = capture_request

    # This is a request that would have triggered the original error
    # It includes top_p which would have been added to extra_body before our fix
    request_data = ChatRequest(
        model="anthropic:claude-3-haiku-20240229",
        max_tokens=128,
        top_p=0.9,  # This would have caused the error before our fix
        messages=[ChatMessage(role="user", content="Hello")],
    )

    # Create mocks for decomposed RequestProcessor services
    from src.core.domain.processed_result import ProcessedResult
    from src.core.interfaces.request_processor_internal import (
        IBackendExecutor,
        IBackendPreparer,
        ICommandHandler,
        IRequestSideEffects,
        IRequestTransformPipeline,
        ISessionEnricher,
    )

    session_enricher = AsyncMock(spec=ISessionEnricher)
    session_enricher.enrich.side_effect = lambda ctx, req: (MagicMock(), req)

    request_side_effects = AsyncMock(spec=IRequestSideEffects)
    request_side_effects.apply.side_effect = lambda ctx, sid, req: req

    command_handler = AsyncMock(spec=ICommandHandler)
    command_handler.handle.return_value = ProcessedResult(
        modified_messages=[], command_executed=False, command_results=[]
    )

    backend_preparer = AsyncMock(spec=IBackendPreparer)
    backend_preparer.prepare.side_effect = lambda ctx, sid, req, cmd: req

    transform_pipeline = AsyncMock(spec=IRequestTransformPipeline)
    transform_pipeline.transform.side_effect = lambda ctx, sess, sid, req: req

    backend_executor = AsyncMock(spec=IBackendExecutor)

    async def execute_backend(
        context, session, session_id, backend_request, original_request
    ):
        # Actually call backend_request_manager to test the full flow
        return await backend_request_manager.process_backend_request(
            backend_request, session_id, context
        )

    backend_executor.execute.side_effect = execute_backend

    processor = RequestProcessor(
        mock_command_processor,
        mock_session_manager,
        backend_request_manager,
        mock_response_manager,
        session_enricher=session_enricher,
        request_side_effects=request_side_effects,
        command_handler=command_handler,
        backend_preparer=backend_preparer,
        transform_pipeline=transform_pipeline,
        backend_executor=backend_executor,
    )

    # Call the process_request method
    await processor.process_request(MagicMock(), request_data)

    # Verify that the backend_processor received the correct ChatRequest
    assert captured_request is not None
    assert isinstance(captured_request, ChatRequest)

    # Verify that top_p is in the main ChatRequest fields
    assert captured_request.top_p == 0.9

    # Most importantly, verify that top_p is NOT in extra_body
    # This is the key fix that prevents the duplicate keyword argument error
    assert "top_p" not in (captured_request.extra_body or {})

    # Verify other parameters are correctly handled
    assert captured_request.model == "anthropic:claude-3-haiku-20240229"
    assert captured_request.max_tokens == 128
