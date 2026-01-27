"""Tests for replacement model error handling and fallback."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.processed_result import ProcessedResult
from src.core.domain.request_context import RequestContext
from src.core.interfaces.model_replacement_service_interface import (
    IModelReplacementService,
)
from src.core.services.request_processor_service import RequestProcessor


@pytest.mark.asyncio
async def test_fallback_to_original_on_replacement_error():
    """
    Test that if the replacement model fails (e.g. rate limit), the proxy
    catches the error, deactivates replacement, and retries with the original model.
    """
    # 1. Setup mocks
    mock_replacement = MagicMock(spec=IModelReplacementService)
    # Simulate active replacement
    mock_state = MagicMock()
    mock_state.active = True
    mock_state.original_backend = "original-backend"
    mock_state.original_model = "original-model"
    mock_state.replacement_backend = "replacement-backend"
    mock_state.replacement_model = "replacement-model"

    mock_replacement.should_replace.return_value = True
    mock_replacement.get_state.return_value = mock_state
    mock_replacement.activate_replacement = AsyncMock()
    mock_replacement.get_effective_backend_model.return_value = (
        "replacement-backend",
        "replacement-model",
    )

    # 2. Setup backend executor to fail on first call (replacement), succeed on second (fallback)
    mock_executor = AsyncMock()
    # First call raises Exception, second call returns success
    mock_executor.execute.side_effect = [
        Exception("Rate limit exceeded on replacement model"),
        MagicMock(spec="ResponseEnvelope"),  # Success
    ]

    request_data = ChatRequest(
        model="original-backend:original-model",
        messages=[ChatMessage(role="user", content="hi")],
    )

    mock_dependencies = {
        "command_processor": MagicMock(),
        "session_manager": MagicMock(),
        "backend_request_manager": MagicMock(),
        "response_manager": MagicMock(),
        "session_enricher": MagicMock(),
        "request_side_effects": MagicMock(),
        "command_handler": MagicMock(),
        "backend_preparer": MagicMock(),
        "transform_pipeline": MagicMock(),
        "backend_executor": mock_executor,
        "app_state": MagicMock(),
        "replacement_service": mock_replacement,
    }

    # Async setup
    mock_dependencies["session_enricher"].enrich = AsyncMock(
        return_value=(MagicMock(), request_data)
    )
    mock_dependencies["session_manager"].resolve_session_id = AsyncMock(
        return_value="test-session"
    )
    mock_dependencies["request_side_effects"].apply = AsyncMock(
        return_value=request_data
    )
    mock_dependencies["command_handler"].handle = AsyncMock(
        return_value=ProcessedResult(
            modified_messages=list(request_data.messages),
            command_executed=False,
            command_results=[],
        )
    )
    mock_dependencies["backend_preparer"].prepare = AsyncMock(return_value=request_data)
    mock_dependencies["transform_pipeline"].transform = AsyncMock(
        return_value=request_data
    )

    processor = RequestProcessor(**mock_dependencies)

    context = RequestContext(headers={}, cookies={}, state={}, app_state=None)

    # 3. Execute
    await processor.process_request(context, request_data)

    # 4. Verifications

    # Verify executor was called twice
    assert mock_executor.execute.call_count == 2

    # Verify fallback call happened
    assert mock_executor.execute.call_count == 2

    # The last call MUST be the fallback to original
    fallback_call = mock_executor.execute.call_args_list[1]
    # We expect the fallback request to have the original model
    assert fallback_call.args[3].model == "original-backend:original-model"

    # Verify replacement was deactivated
    mock_state.deactivate.assert_called_once()

    print(
        "Test passed: Automatically fell back to original model after replacement failure."
    )


if __name__ == "__main__":
    import asyncio

    asyncio.run(test_fallback_to_original_on_replacement_error())
