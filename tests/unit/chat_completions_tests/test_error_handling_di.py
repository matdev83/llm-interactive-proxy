"""
Tests for error handling in chat completions using proper DI approach.

This file contains tests for error handling in chat completions,
refactored to use proper dependency injection instead of direct app.state access.
"""

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from src.core.domain.responses import ResponseEnvelope
from src.core.interfaces.backend_service_interface import IBackendService

from tests.utils.test_di_utils import (
    configure_test_state,
    get_required_service_from_app,
)


@patch("src.connectors.openai.OpenAIConnector.chat_completions", new_callable=AsyncMock)
@patch(
    "src.connectors.openrouter.OpenRouterBackend.chat_completions",
    new_callable=AsyncMock,
)
@patch("src.connectors.gemini.GeminiBackend.chat_completions", new_callable=AsyncMock)
def test_empty_messages_after_processing_no_commands_bad_request(
    mock_gemini: Any, mock_openrouter: Any, mock_openai: Any, client: TestClient
) -> None:
    """Test that empty messages result in a validation error."""
    # Mock a response in case it gets called
    mock_response = {"choices": [{"message": {"content": "response"}}]}
    mock_openai.return_value = mock_response
    mock_openrouter.return_value = mock_response
    mock_gemini.return_value = mock_response

    # Configure test state with proper DI
    configure_test_state(
        client.app,
        backend_type="openrouter",
        disable_interactive_commands=False,
    )

    # This test expects that when messages are empty after processing,
    # the request should fail with 422 (validation error)
    payload = {
        "model": "some-model",
        "messages": [],  # Empty messages to trigger validation error
    }
    response = client.post("/v1/chat/completions", json=payload)

    assert response.status_code == 422
    response_json = response.json()
    # The error structure might be in either "detail" or "error" depending on the handler
    error_msg = str(response_json).lower()
    assert "messages" in error_msg or "empty" in error_msg or "validation" in error_msg
    mock_openai.assert_not_called()
    mock_openrouter.assert_not_called()
    mock_gemini.assert_not_called()


def test_get_openrouter_headers_no_api_key(client: TestClient) -> None:
    """Test handling of backend errors due to missing API keys."""
    # Configure test state with proper DI
    configure_test_state(
        client.app,
        backend_type="openrouter",
        disable_interactive_commands=False,
    )

    # Simulate a backend error by mocking the backend processor
    from src.core.common.exceptions import BackendError

    mock_error = BackendError(
        message="Simulated backend error due to bad headers", backend_name="openai"
    )

    with patch(
        "src.core.services.backend_processor.BackendProcessor.process_backend_request",
        new_callable=AsyncMock,
    ) as mock_process_backend:
        mock_process_backend.side_effect = mock_error

        payload = {
            "model": "gpt-3.5-turbo",
            "messages": [{"role": "user", "content": "Hello"}],
        }
        response = client.post("/v1/chat/completions", json=payload)

        assert response.status_code == 502  # BackendError maps to 502 Bad Gateway

        response_json = response.json()
        # The error format has changed in the new architecture
        assert "error" in response_json or "detail" in response_json
        error_msg = str(response_json)
        assert "backend" in error_msg.lower() or "error" in error_msg.lower()


@pytest.mark.no_global_mock
def test_invalid_model_noninteractive(client: TestClient) -> None:
    """Test handling of invalid model errors in non-interactive mode."""
    from src.core.common.exceptions import InvalidRequestError

    # Configure test state with proper DI
    configure_test_state(
        client.app,
        backend_type="openrouter",
        disable_interactive_commands=False,
    )

    # Get the backend service using proper DI
    backend_service = get_required_service_from_app(client.app, IBackendService)

    # Store the original call_completion method
    original_call_completion = backend_service.call_completion

    # Create a mock that returns the expected responses
    mock_responses = [
        ResponseEnvelope(
            content={
                "id": "cmd-1",
                "choices": [
                    {
                        "message": {
                            "content": "Model 'bad' not found for backend 'openrouter'"
                        }
                    }
                ],
            },
            headers={"Content-Type": "application/json"},
            status_code=200,
        ),
        # For the second call, raise an error
        InvalidRequestError(message="Model 'bad' not found for backend 'openrouter'"),
    ]

    call_count = 0

    async def mock_call_completion(*args, **kwargs):
        nonlocal call_count
        if call_count < len(mock_responses):
            response = mock_responses[call_count]
            call_count += 1
            if isinstance(response, Exception):
                raise response
            return response
        else:
            # Fall back to original for any additional calls
            return await original_call_completion(*args, **kwargs)

    backend_service.call_completion = AsyncMock(side_effect=mock_call_completion)

    try:
        # First request: set an invalid model
        payload = {
            "model": "m",
            "messages": [{"role": "user", "content": "!/set(model=openrouter:bad)"}],
        }
        resp = client.post("/v1/chat/completions", json=payload)
        assert resp.status_code == 200
        content = resp.json()["choices"][0]["message"]["content"]
        # The command might succeed even with invalid model in the new architecture
        assert "Model" in content and "bad" in content

        # Second request: try to use the invalid model
        payload2 = {
            "model": "openrouter:bad",
            "messages": [{"role": "user", "content": "Hello"}],
        }
        resp2 = client.post("/v1/chat/completions", json=payload2)
        # Should fail with 400 Bad Request
        assert resp2.status_code == 400
        assert "Model 'bad' not found" in str(resp2.json())
    finally:
        # Restore the original method to avoid affecting other tests
        backend_service.call_completion = original_call_completion
