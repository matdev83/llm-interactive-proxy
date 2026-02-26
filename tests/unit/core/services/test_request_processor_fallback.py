"""
Dedicated regression tests for RequestProcessor fallback error propagation.

Ensures that when both original and replacement models fail, the resulting 
errors are strongly typed (AuthenticationError, RoutingError, BackendError)
and surface upstream metadata properly instead of throwing generic Exceptions.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.common.exceptions import AuthenticationError, BackendError, RoutingError
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
def base_request_processor() -> tuple[RequestProcessor, MagicMock, AsyncMock]:
    """Provides a RequestProcessor with minimal mocks to focus on execution fallback."""
    mock_command_processor = AsyncMock(spec=ICommandProcessor)
    mock_command_processor.process_messages.return_value = ProcessedResult(
        modified_messages=[ChatMessage(role="user", content="Test")],
        command_executed=False,
        command_results=[],
    )

    mock_session_manager = AsyncMock(spec=ISessionManager)
    session = MagicMock(spec=Session)
    session.state = MagicMock()
    mock_session_manager.get_session.return_value = session
    mock_session_manager.resolve_session_id.return_value = "session-123"
    mock_session_manager.update_session_agent.return_value = session

    mock_backend_request_manager = AsyncMock(spec=IBackendRequestManager)
    mock_backend_request_manager.prepare_backend_request.return_value = MagicMock()

    mock_response_manager = AsyncMock(spec=IResponseManager)

    mock_app_state = MagicMock(spec=IApplicationState)

    mock_session_enricher = AsyncMock()
    request = ChatRequest(model="test_model", messages=[ChatMessage(role="user", content="Hello")])
    mock_session_enricher.enrich.return_value = (session, request)

    mock_request_side_effects = AsyncMock()
    mock_request_side_effects.apply.side_effect = lambda ctx, sid, req: req

    mock_command_handler = AsyncMock()
    mock_command_handler.handle.return_value = ProcessedResult(command_executed=False, modified_messages=[], command_results=[])

    mock_backend_preparer = AsyncMock()
    mock_backend_preparer.prepare.side_effect = lambda ctx, sid, req, cmd: req

    mock_transform_pipeline = AsyncMock()
    mock_transform_pipeline.transform.side_effect = lambda ctx, sess, sid, req: req

    mock_backend_executor = AsyncMock()

    processor = RequestProcessor(
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
    
    # Inject a mock replacement service directly to bypass initialization
    mock_replacement_service = MagicMock()
    processor._replacement_service = mock_replacement_service

    return processor, mock_replacement_service, mock_backend_executor


@pytest.fixture
def request_context() -> RequestContext:
    app_state = MagicMock(spec=IApplicationState)
    return RequestContext(
        headers={},
        cookies={},
        state=MagicMock(),
        app_state=app_state,
        client_host="127.0.0.1",
        original_request=None,
    )


@pytest.mark.asyncio
async def test_fallback_returns_400_raises_routing_error(
    base_request_processor: tuple[RequestProcessor, MagicMock, AsyncMock],
    request_context: RequestContext,
) -> None:
    processor, mock_replacement, mock_executor = base_request_processor
    
    request_context.backend = "repl_backend"
    request_context.effective_model = "repl_model"
    
    # Setup replacement state matching context
    mock_state = MagicMock()
    mock_state.active = True
    mock_state.replacement_backend = "repl_backend"
    mock_state.replacement_model = "repl_model"
    mock_state.original_backend = "orig_backend"
    mock_state.original_model = "orig_model"
    mock_replacement.get_state.return_value = mock_state
    mock_replacement.get_effective_backend_model.return_value = ("repl_backend", "repl_model")

    # 1. Primary execution raises generic Exception (fallback trigger)
    # 2. Fallback execution returns a 400 ResponseEnvelope
    mock_executor.execute.side_effect = [
        Exception("Primary model API failed"),
        ResponseEnvelope(
            content={},
            status_code=400,
            metadata={"error_message": "Invalid request parameters", "error_code": "unsupported_on_instance", "error_type": "RoutingError"}
        )
    ]

    request = ChatRequest(model="test_model", messages=[ChatMessage(role="user", content="Hello")])

    with pytest.raises(RoutingError) as exc_info:
        await processor.process_request(request_context, request)

    # Note: RoutingError hardcodes 403 on initialization.
    # The HTTP mapper translates it to 400 based on 'unsupported_on_instance' code.
    assert exc_info.value.status_code == 403
    assert "Invalid request parameters" in exc_info.value.message
    assert exc_info.value.details == {"code": "unsupported_on_instance"}


@pytest.mark.asyncio
async def test_fallback_returns_401_raises_authentication_error(
    base_request_processor: tuple[RequestProcessor, MagicMock, AsyncMock],
    request_context: RequestContext,
) -> None:
    processor, mock_replacement, mock_executor = base_request_processor
    
    request_context.backend = "repl_backend"
    request_context.effective_model = "repl_model"
    
    mock_state = MagicMock()
    mock_state.active = True
    mock_state.replacement_backend = "repl_backend"
    mock_state.replacement_model = "repl_model"
    mock_state.original_backend = "orig_backend"
    mock_state.original_model = "orig_model"
    mock_replacement.get_state.return_value = mock_state
    mock_replacement.get_effective_backend_model.return_value = ("repl_backend", "repl_model")

    # 1. Primary execution raises generic Exception (fallback trigger)
    # 2. Fallback execution returns a 401 ResponseEnvelope
    mock_executor.execute.side_effect = [
        Exception("Primary model API failed"),
        ResponseEnvelope(
            content={},
            status_code=401,
            metadata={"error_message": "Unauthenticated user"}
        )
    ]

    request = ChatRequest(model="test_model", messages=[ChatMessage(role="user", content="Hello")])

    with pytest.raises(AuthenticationError) as exc_info:
        await processor.process_request(request_context, request)

    assert exc_info.value.status_code == 401
    assert "Unauthenticated user" in exc_info.value.message


@pytest.mark.asyncio
async def test_fallback_returns_500_raises_backend_error(
    base_request_processor: tuple[RequestProcessor, MagicMock, AsyncMock],
    request_context: RequestContext,
) -> None:
    processor, mock_replacement, mock_executor = base_request_processor
    
    request_context.backend = "repl_backend"
    request_context.effective_model = "repl_model"
    
    mock_state = MagicMock()
    mock_state.active = True
    mock_state.replacement_backend = "repl_backend"
    mock_state.replacement_model = "repl_model"
    mock_state.original_backend = "orig_backend"
    mock_state.original_model = "orig_model"
    mock_replacement.get_state.return_value = mock_state
    mock_replacement.get_effective_backend_model.return_value = ("repl_backend", "repl_model")

    # 1. Primary execution raises generic Exception (fallback trigger)
    # 2. Fallback execution returns a 503 ResponseEnvelope
    mock_executor.execute.side_effect = [
        Exception("Primary model API failed"),
        ResponseEnvelope(
            content={},
            status_code=503,
            metadata={"error_message": "Service unavailable", "error_type": "api_error"}
        )
    ]

    request = ChatRequest(model="test_model", messages=[ChatMessage(role="user", content="Hello")])

    with pytest.raises(BackendError) as exc_info:
        await processor.process_request(request_context, request)

    assert exc_info.value.status_code == 503
    assert "Service unavailable" in exc_info.value.message
