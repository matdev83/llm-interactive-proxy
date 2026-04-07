"""
Regression test for Gemini capacity error handling.
Ensures that 'No capacity available' errors are treated as retryable rate limit errors.
"""

import json
from unittest.mock import AsyncMock, Mock, patch

import pytest
from src.connectors.gemini_base.streaming_executor import StreamingExecutor
from src.core.common.exceptions import BackendError


@pytest.mark.asyncio
async def test_capacity_error_is_treated_as_retryable_rate_limit():
    """
    Test that 'No capacity available' errors from Gemini (RESOURCE_EXHAUSTED without retry hint)
    are mapped to 'rate_limit_exceeded' with a default retry delay.
    """
    # Mock dependencies
    translation_service = Mock()
    token_estimator = Mock()
    google_auth_provider = Mock()
    retry_delay_extractor = Mock()
    retry_delay_extractor.extract_retry_delay.return_value = None

    executor = StreamingExecutor(
        translation_service=translation_service,
        token_estimator=token_estimator,
        google_auth_provider=google_auth_provider,
        retry_delay_extractor=retry_delay_extractor,
    )

    # Mock prepared request
    prepared = Mock()
    prepared.effective_model = "gemini-3-flash-preview"
    prepared.prompt_tokens_estimate = 10
    prepared.auth_session = Mock()
    prepared.build_request_body.return_value = {"request": {}}
    prepared.session_id = "test-session"
    prepared.code_assist_request = {}

    # Mock response for "No capacity available"
    # Status 429, RESOURCE_EXHAUSTED, no retry-after headers, no retry delay in body
    mock_response = Mock()
    mock_response.status_code = 429
    mock_response.json.return_value = {
        "error": {
            "code": 429,
            "message": "No capacity available for model gemini-3-flash-preview on the server",
            "status": "RESOURCE_EXHAUSTED",
        }
    }
    mock_response.headers = {}
    mock_response.text = json.dumps(mock_response.json.return_value)

    # Patch asyncio.to_thread to return our mock response
    async def passthrough_execute(operation, **kwargs):
        return await operation()

    with (
        patch.object(executor._shared_retry_executor, "execute", passthrough_execute),
        patch(
            "src.connectors.gemini_base.streaming_executor.asyncio.to_thread",
            AsyncMock(return_value=mock_response),
        ),
    ):
        try:
            async for _ in executor.execute(prepared, "http://example.com/stream"):
                pass
        except BackendError as e:
            assert e.code == "rate_limit_exceeded"
            assert e.status_code == 429
            assert e.details.get("retry_after") == 5.0
            return

    pytest.fail("Should have raised BackendError with rate_limit_exceeded code")
