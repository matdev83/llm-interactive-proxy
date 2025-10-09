from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope
from src.core.services.backend_request_manager_service import BackendRequestManager
from src.core.services.empty_response_middleware import (
    EmptyResponseRetryError,
)


@pytest.fixture
def mock_backend_processor():
    return AsyncMock()


@pytest.fixture
def mock_response_processor():
    return AsyncMock()


@pytest.fixture
def backend_request_manager(mock_backend_processor, mock_response_processor):
    return BackendRequestManager(mock_backend_processor, mock_response_processor)


@pytest.mark.asyncio
async def test_empty_response_recovery(
    backend_request_manager: BackendRequestManager,
    mock_backend_processor: MagicMock,
    mock_response_processor: MagicMock,
):
    # Arrange
    session_id = "test_session"
    original_request = ChatRequest(
        model="test_model",
        messages=[ChatMessage(role="user", content="hello")],
    )
    context = RequestContext(
        headers={},
        cookies={},
        state={},
        app_state={},
        original_request=original_request,
        session_id=session_id,
    )

    # First, configure the backend processor to return a response with content
    # so that the response processing logic gets executed
    mock_backend_response = ResponseEnvelope(content="initial content")
    mock_backend_processor.process_backend_request.return_value = mock_backend_response

    # Simulate an empty response by having the response processor raise an exception
    mock_response_processor.process_response.side_effect = EmptyResponseRetryError(
        recovery_prompt="Please provide a valid response.",
        session_id=session_id,
        retry_count=1,
        original_request=original_request,
    )

    # Act
    await backend_request_manager.process_backend_request(
        backend_request=original_request,
        session_id=session_id,
        context=context,
    )

    # Assert
    assert mock_backend_processor.process_backend_request.call_count == 2
    retry_request = mock_backend_processor.process_backend_request.call_args[1][
        "request"
    ]
    assert len(retry_request.messages) == 2
    assert retry_request.messages[-1].content == "Please provide a valid response."
