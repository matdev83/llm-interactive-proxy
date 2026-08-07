"""Tests for 400 Bad Request error handling in streaming responses.

Verifies that HTTP 400 errors (including "Prompt is too long") are handled
by raising BackendError, which allows proper HTTP 400 responses to clients.

Note: Previously 400 errors yielded error chunks, but this caused clients
to receive HTTP 200 with an error chunk they didn't understand, leading
to infinite retry loops. Now 400 errors raise BackendError to return
proper HTTP 400 responses to clients.
"""

from unittest.mock import MagicMock

import pytest
import requests  # type: ignore[import-untyped]
from src.connectors.gemini_base.chat_request_preparer import PreparedChatRequest
from src.connectors.gemini_base.streaming_executor import (
    SSELineProcessor,
    StreamingExecutor,
)
from src.core.common.exceptions import BackendError


@pytest.fixture
def mock_processor() -> MagicMock:
    """Create a mock SSELineProcessor."""
    processor = MagicMock(spec=SSELineProcessor)
    return processor


@pytest.fixture
def mock_prepared_request() -> MagicMock:
    """Create a mock PreparedChatRequest."""
    prepared = MagicMock(spec=PreparedChatRequest)
    prepared.body = {"model": "test-model"}
    prepared.headers = {}
    prepared.max_tokens = 1000
    return prepared


@pytest.fixture
def mock_400_response() -> MagicMock:
    """Create a mock 400 Bad Request response."""
    response = MagicMock(spec=requests.Response)
    response.status_code = 400
    response.json.return_value = {
        "error": {
            "message": "Prompt is too long",
            "type": "invalid_request_error",
        }
    }
    response.close = MagicMock()
    return response


@pytest.fixture
def executor() -> StreamingExecutor:
    """Create a StreamingExecutor instance."""
    mock_translation_service = MagicMock()
    return StreamingExecutor(
        translation_service=mock_translation_service,
        backend_type="gemini-test",
    )


class TestPromptTooLongErrorHandling:
    """Test suite for 400 'Prompt is too long' error handling."""

    @pytest.mark.asyncio
    async def test_400_error_raises_backend_error(
        self,
        executor: StreamingExecutor,
        mock_processor: MagicMock,
        mock_prepared_request: MagicMock,
        mock_400_response: MagicMock,
    ) -> None:
        """400 errors should raise BackendError to return proper HTTP 400 to clients.

        This prevents the infinite retry loop that occurred when yielding error
        chunks (clients received 200 with an error chunk they didn't understand).
        """
        with pytest.raises(BackendError) as exc_info:
            async for _ in executor._handle_error_response(
                response=mock_400_response,
                processor=mock_processor,
                prepared=mock_prepared_request,
                url="https://example.com/test",
                prompt_tokens=50000,
            ):
                pass

        # Verify the BackendError has correct properties
        error = exc_info.value
        assert error.status_code == 400
        assert "Prompt is too long" in error.message

        # Verify the response was closed
        mock_400_response.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_prompt_too_long_message_preserved_in_exception(
        self,
        executor: StreamingExecutor,
        mock_processor: MagicMock,
        mock_prepared_request: MagicMock,
        mock_400_response: MagicMock,
    ) -> None:
        """The 'Prompt is too long' message should be preserved in the BackendError."""
        with pytest.raises(BackendError) as exc_info:
            async for _ in executor._handle_error_response(
                response=mock_400_response,
                processor=mock_processor,
                prepared=mock_prepared_request,
                url="https://example.com/test",
                prompt_tokens=50000,
            ):
                pass

        # Verify the message was preserved
        assert "Prompt is too long" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_400_error_details_populated(
        self,
        executor: StreamingExecutor,
        mock_processor: MagicMock,
        mock_prepared_request: MagicMock,
        mock_400_response: MagicMock,
    ) -> None:
        """BackendError should have properly populated details for 400 errors."""
        with pytest.raises(BackendError) as exc_info:
            async for _ in executor._handle_error_response(
                response=mock_400_response,
                processor=mock_processor,
                prepared=mock_prepared_request,
                url="https://example.com/test",
                prompt_tokens=50000,
            ):
                pass

        error = exc_info.value

        # Verify required properties
        assert error.status_code == 400
        assert error.backend_name == "gemini-test"
        assert error.details is not None
        # Details should contain the raw error from the API
        assert "error" in error.details

    @pytest.mark.asyncio
    async def test_non_400_errors_still_raise(
        self,
        executor: StreamingExecutor,
        mock_processor: MagicMock,
        mock_prepared_request: MagicMock,
    ) -> None:
        """Non-400 errors should still raise BackendError (unless otherwise handled)."""
        # Create a 500 error response
        mock_response = MagicMock(spec=requests.Response)
        mock_response.status_code = 500
        mock_response.json.return_value = {
            "error": {"message": "Internal server error"}
        }
        mock_response.close = MagicMock()

        with pytest.raises(BackendError) as exc_info:
            async for _ in executor._handle_error_response(
                response=mock_response,
                processor=mock_processor,
                prepared=mock_prepared_request,
                url="https://example.com/test",
                prompt_tokens=50000,
            ):
                pass

        assert exc_info.value.status_code == 500
