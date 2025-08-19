from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.responses import ResponseEnvelope
from src.core.interfaces.backend_processor_interface import IBackendProcessor
from src.core.interfaces.command_service_interface import ICommandService
from src.core.interfaces.response_processor_interface import IResponseProcessor
from src.core.interfaces.session_service_interface import ISessionService
from src.core.services.request_processor_service import RequestProcessor


@pytest.mark.asyncio
async def test_top_p_fix_with_actual_request() -> None:
    """Test that demonstrates our fix works with a real request that includes top_p."""

    # Create mocks for dependencies
    mock_command_processor = MagicMock(spec=ICommandService)
    mock_backend_processor = MagicMock(spec=IBackendProcessor)
    mock_session_service = MagicMock(spec=ISessionService)
    mock_response_processor = MagicMock(spec=IResponseProcessor)

    # Configure mock_command_processor to return messages unchanged and no command executed
    mock_command_processor.process_commands.return_value = AsyncMock(
        return_value=MagicMock(
            modified_messages=[ChatMessage(role="user", content="Hello")],
            command_executed=False,
            command_results=[],
        )
    ).return_value

    # Configure mock_backend_processor to capture the request it receives
    captured_request = None

    async def capture_request(*args, **kwargs):
        nonlocal captured_request
        captured_request = kwargs.get("request")
        # Return a dummy response envelope
        return ResponseEnvelope(content={}, headers={}, status_code=200, media_type="application/json")

    mock_backend_processor.process_backend_request.side_effect = capture_request

    processor = RequestProcessor(
        command_processor=mock_command_processor,
        backend_processor=mock_backend_processor,
        session_service=mock_session_service,
        response_processor=mock_response_processor,
    )

    # This is a request that would have triggered the original error
    # It includes top_p which would have been added to extra_body before our fix
    request_data = ChatRequest(
        model="anthropic:claude-3-haiku-20240229",
        max_tokens=128,
        top_p=0.9,  # This would have caused the error before our fix
        messages=[ChatMessage(role="user", content="Hello")],
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
