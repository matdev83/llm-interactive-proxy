"""Integration tests for HTTP status codes in streaming error responses.

This test suite ensures that streaming responses return the proper HTTP status codes
when errors occur, rather than always returning 200 OK. This prevents clients from
stalling when they expect content but receive errors.

Regression test for issue where 429 rate limit errors were being returned with HTTP 200 status,
causing clients to wait indefinitely for content that would never arrive.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from src.core.common.exceptions import BackendError, RateLimitExceededError
from src.core.domain.responses import StreamingResponseEnvelope
from src.core.interfaces.response_processor_interface import ProcessedResponse


@pytest.fixture
def sample_app() -> FastAPI:
    """Create a minimal FastAPI app for testing."""
    from src.core.adapters.response_adapters import to_fastapi_streaming_response

    app = FastAPI()

    @app.get("/streaming-error-429")
    async def streaming_error_429():
        """Simulate a streaming response with 429 error."""

        async def error_stream():
            yield ProcessedResponse(
                content='data: {"error": {"message": "Rate limit exceeded", "type": "rate_limit_error", "code": 429}}\\n\\n'
            )

        envelope = StreamingResponseEnvelope(
            content=error_stream(),
            media_type="text/event-stream",
            status_code=429,  # CRITICAL: Must be 429, not 200
        )
        return to_fastapi_streaming_response(envelope)

    @app.get("/streaming-error-500")
    async def streaming_error_500():
        """Simulate a streaming response with 500 error."""

        async def error_stream():
            yield ProcessedResponse(
                content='data: {"error": {"message": "Internal server error", "type": "server_error", "code": 500}}\\n\\n'
            )

        envelope = StreamingResponseEnvelope(
            content=error_stream(),
            media_type="text/event-stream",
            status_code=500,
        )
        return to_fastapi_streaming_response(envelope)

    @app.get("/streaming-success")
    async def streaming_success():
        """Simulate a successful streaming response."""

        async def success_stream():
            yield ProcessedResponse(
                content='data: {"choices": [{"delta": {"content": "Hello"}}]}\\n\\n'
            )
            yield ProcessedResponse(content="data: [DONE]\\n\\n")

        envelope = StreamingResponseEnvelope(
            content=success_stream(),
            media_type="text/event-stream",
            status_code=200,
        )
        return to_fastapi_streaming_response(envelope)

    return app


def test_streaming_rate_limit_error_returns_429(sample_app: FastAPI) -> None:
    """Test that streaming responses with rate limit errors return HTTP 429.

    This is a regression test for an issue where all streaming responses returned 200 OK,
    even when containing error messages. This caused clients to stall waiting for content.
    """
    client = TestClient(sample_app)
    response = client.get("/streaming-error-429")

    # CRITICAL: Status code MUST be 429, not 200
    assert (
        response.status_code == 429
    ), "Rate limit streaming errors must return HTTP 429, not 200"

    # Verify error is also in the SSE stream content
    content = response.text
    assert "Rate limit exceeded" in content
    assert "rate_limit_error" in content


def test_streaming_server_error_returns_500(sample_app: FastAPI) -> None:
    """Test that streaming responses with server errors return HTTP 500."""
    client = TestClient(sample_app)
    response = client.get("/streaming-error-500")

    # Status code must be 500 for server errors
    assert (
        response.status_code == 500
    ), "Server error streaming responses must return HTTP 500, not 200"

    # Verify error is in the stream
    content = response.text
    assert "Internal server error" in content


def test_streaming_success_returns_200(sample_app: FastAPI) -> None:
    """Test that successful streaming responses return HTTP 200."""
    client = TestClient(sample_app)
    response = client.get("/streaming-success")

    # Successful streams should return 200
    assert response.status_code == 200

    # Verify content streams correctly
    content = response.text
    assert "Hello" in content
    assert "[DONE]" in content


def test_streaming_response_envelope_default_status() -> None:
    """Test that StreamingResponseEnvelope has correct default status code."""

    async def dummy_stream():
        yield ProcessedResponse(content="test")

    envelope = StreamingResponseEnvelope(
        content=dummy_stream(),
        media_type="text/event-stream",
    )

    # Default should be 200
    assert envelope.status_code == 200


def test_streaming_response_envelope_custom_status() -> None:
    """Test that StreamingResponseEnvelope accepts custom status codes."""

    async def dummy_stream():
        yield ProcessedResponse(content="error")

    envelope = StreamingResponseEnvelope(
        content=dummy_stream(),
        media_type="text/event-stream",
        status_code=429,
    )

    assert envelope.status_code == 429


def test_backend_error_status_code_preserved() -> None:
    """Test that BackendError status codes are available for streaming responses."""
    error = BackendError(
        message="Backend failed",
        backend_name="test",
        details={},
    )

    # BackendError should have status_code available
    assert hasattr(error, "status_code")
    assert error.status_code == 502  # Default for BackendError (Bad Gateway)


def test_rate_limit_error_status_code() -> None:
    """Test that RateLimitExceededError has correct status code."""
    error = RateLimitExceededError(
        message="Rate limit exceeded",
        details={},
    )

    # RateLimitExceededError should have 429 status
    assert error.status_code == 429
