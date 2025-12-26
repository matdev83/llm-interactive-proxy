"""Tests for 400 Bad Request error handling in streaming responses.

Verifies that HTTP 400 errors (including "Prompt is too long") are handled
gracefully by yielding error chunks instead of raising exceptions.
"""

import time
from typing import Any
from unittest.mock import MagicMock

import pytest
import requests
from src.connectors.gemini_base.chat_request_preparer import PreparedChatRequest
from src.connectors.gemini_base.streaming_executor import (
    ProcessedResponse,
    SSELineProcessor,
    StreamingExecutor,
)


@pytest.fixture
def mock_processor() -> MagicMock:
    """Create a mock SSELineProcessor."""
    processor = MagicMock(spec=SSELineProcessor)
    processor.build_error_chunk.return_value = {
        "id": f"chatcmpl-error-{int(time.time())}",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": "test-model",
        "choices": [{"index": 0, "delta": {}, "finish_reason": "error"}],
        "error": {
            "message": "Prompt is too long",
            "type": "invalid_request_error",
            "code": 400,
        },
    }
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
    async def test_400_error_yields_chunk_not_exception(
        self,
        executor: StreamingExecutor,
        mock_processor: MagicMock,
        mock_prepared_request: MagicMock,
        mock_400_response: MagicMock,
    ) -> None:
        """400 errors should yield error chunks instead of raising exceptions."""
        chunks: list[ProcessedResponse] = []

        # Call _handle_error_response directly
        async for chunk in executor._handle_error_response(
            response=mock_400_response,
            processor=mock_processor,
            prepared=mock_prepared_request,
            url="https://example.com/test",
            prompt_tokens=50000,
        ):
            chunks.append(chunk)

        # Should yield exactly one error chunk
        assert len(chunks) == 1

        # Verify the chunk contains error information
        chunk = chunks[0]
        assert isinstance(chunk, ProcessedResponse)
        assert "error" in chunk.content
        assert chunk.content["error"]["code"] == 400

        # Verify the response was closed
        mock_400_response.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_prompt_too_long_message_preserved(
        self,
        executor: StreamingExecutor,
        mock_processor: MagicMock,
        mock_prepared_request: MagicMock,
        mock_400_response: MagicMock,
    ) -> None:
        """The 'Prompt is too long' message should be preserved in the error chunk."""
        # Set up the processor to capture the message
        captured_message: list[str] = []

        def capture_build_error_chunk(
            message: str, code: int, error_type: str
        ) -> dict[str, Any]:
            captured_message.append(message)
            return {
                "id": "test-id",
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": "test-model",
                "choices": [{"index": 0, "delta": {}, "finish_reason": "error"}],
                "error": {
                    "message": message,
                    "type": error_type,
                    "code": code,
                },
            }

        mock_processor.build_error_chunk.side_effect = capture_build_error_chunk

        # Call the handler
        async for _ in executor._handle_error_response(
            response=mock_400_response,
            processor=mock_processor,
            prepared=mock_prepared_request,
            url="https://example.com/test",
            prompt_tokens=50000,
        ):
            pass

        # Verify the message was captured
        assert len(captured_message) == 1
        assert "Prompt is too long" in captured_message[0]

    @pytest.mark.asyncio
    async def test_error_chunk_metadata_populated(
        self,
        executor: StreamingExecutor,
        mock_processor: MagicMock,
        mock_prepared_request: MagicMock,
        mock_400_response: MagicMock,
    ) -> None:
        """Error chunks should have properly populated metadata."""
        chunks: list[ProcessedResponse] = []

        async for chunk in executor._handle_error_response(
            response=mock_400_response,
            processor=mock_processor,
            prepared=mock_prepared_request,
            url="https://example.com/test",
            prompt_tokens=50000,
        ):
            chunks.append(chunk)

        assert len(chunks) == 1
        metadata = chunks[0].metadata

        # Verify required metadata fields
        # metadata is a dict (ErrorMetadata.to_metadata() returns dict)
        assert metadata["finish_reason"] == "error"
        assert "error" in metadata
        assert "id" in metadata
        assert "model" in metadata
        assert "created" in metadata

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

        from src.core.common.exceptions import BackendError

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
