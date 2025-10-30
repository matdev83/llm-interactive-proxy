"""
Tests for Qwen OAuth streaming chunk deduplication.

This module tests the fix for the Qwen API bug where duplicate SSE chunks
are sent, causing text repetition in the client.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from src.connectors.openai import OpenAIConnector
from src.connectors.qwen_oauth import QwenOAuthConnector
from src.core.config.app_config import AppConfig
from src.core.interfaces.response_processor_interface import ProcessedResponse


@pytest.fixture
def mock_config():
    """Create a mock AppConfig for testing."""
    config = MagicMock(spec=AppConfig)
    config.logging = MagicMock()
    config.logging.capture_file = None
    return config


@pytest.fixture
def mock_client():
    """Create a mock HTTP client."""
    return AsyncMock()


@pytest.fixture
def qwen_connector(mock_client, mock_config):
    """Create a QwenOAuthConnector instance for testing."""
    connector = QwenOAuthConnector(
        client=mock_client, config=mock_config, translation_service=None
    )
    # Mock credentials to make connector functional
    connector._oauth_credentials = {
        "access_token": "test_token",
        "refresh_token": "test_refresh",
        "expiry_date": 9999999999999,  # Far future
    }
    connector.is_functional = True
    return connector


@pytest.mark.asyncio
async def test_deduplication_removes_duplicate_chunks(qwen_connector):
    """Test that duplicate chunks are removed from the stream."""

    # Create mock chunks with duplicates (simulating Qwen API bug)
    duplicate_chunks = [
        ProcessedResponse(content={"delta": {"content": "Now"}, "id": "1"}),
        ProcessedResponse(
            content={"delta": {"content": "Now"}, "id": "1"}
        ),  # Duplicate
        ProcessedResponse(
            content={"delta": {"content": "Now"}, "id": "1"}
        ),  # Duplicate
        ProcessedResponse(content={"delta": {"content": " let"}, "id": "1"}),
        ProcessedResponse(content={"delta": {"content": " me"}, "id": "1"}),
    ]

    async def mock_iterator():
        for chunk in duplicate_chunks:
            yield chunk

    # Create a mock streaming handle
    from src.core.domain.responses import StreamingResponseHandle

    mock_handle = StreamingResponseHandle(
        iterator=mock_iterator(), cancel_callback=AsyncMock()
    )

    # Mock the parent's _handle_streaming_response
    with patch.object(
        OpenAIConnector,
        "_handle_streaming_response",
        return_value=mock_handle,
    ):
        # Call the overridden method
        result_handle = await qwen_connector._handle_streaming_response(
            url="https://test.com",
            payload={},
            headers={"Authorization": "Bearer test"},
            session_id="test_session",
            stream_format="openai",
        )

        # Collect chunks from the deduplicated iterator
        collected_chunks = []
        async for chunk in result_handle.iterator:
            collected_chunks.append(chunk)

        # Verify that duplicates were removed
        assert (
            len(collected_chunks) == 3
        ), "Should have 3 unique chunks (removed 2 duplicates)"

        # Verify content is correct
        assert collected_chunks[0].content["delta"]["content"] == "Now"
        assert collected_chunks[1].content["delta"]["content"] == " let"
        assert collected_chunks[2].content["delta"]["content"] == " me"


@pytest.mark.asyncio
async def test_deduplication_preserves_unique_chunks(qwen_connector):
    """Test that unique chunks are preserved."""

    unique_chunks = [
        ProcessedResponse(content={"delta": {"content": "Hello"}, "id": "1"}),
        ProcessedResponse(content={"delta": {"content": " world"}, "id": "1"}),
        ProcessedResponse(content={"delta": {"content": "!"}, "id": "1"}),
    ]

    async def mock_iterator():
        for chunk in unique_chunks:
            yield chunk

    from src.core.domain.responses import StreamingResponseHandle

    mock_handle = StreamingResponseHandle(
        iterator=mock_iterator(), cancel_callback=AsyncMock()
    )

    with patch.object(
        OpenAIConnector,
        "_handle_streaming_response",
        return_value=mock_handle,
    ):
        result_handle = await qwen_connector._handle_streaming_response(
            url="https://test.com",
            payload={},
            headers={"Authorization": "Bearer test"},
            session_id="test_session",
            stream_format="openai",
        )

        collected_chunks = []
        async for chunk in result_handle.iterator:
            collected_chunks.append(chunk)

        # All unique chunks should be preserved
        assert len(collected_chunks) == 3
        assert collected_chunks[0].content["delta"]["content"] == "Hello"
        assert collected_chunks[1].content["delta"]["content"] == " world"
        assert collected_chunks[2].content["delta"]["content"] == "!"


@pytest.mark.asyncio
async def test_deduplication_handles_json_key_ordering(qwen_connector):
    """Test that chunks with different JSON key ordering are detected as duplicates."""

    # Same content, different key ordering (simulating Qwen API behavior)
    chunks_with_different_ordering = [
        ProcessedResponse(
            content={"delta": {"content": "Test"}, "id": "1", "created": 123}
        ),
        ProcessedResponse(
            content={"created": 123, "delta": {"content": "Test"}, "id": "1"}
        ),  # Different order
        ProcessedResponse(
            content={"id": "1", "created": 123, "delta": {"content": "Test"}}
        ),  # Different order
    ]

    async def mock_iterator():
        for chunk in chunks_with_different_ordering:
            yield chunk

    from src.core.domain.responses import StreamingResponseHandle

    mock_handle = StreamingResponseHandle(
        iterator=mock_iterator(), cancel_callback=AsyncMock()
    )

    with patch.object(
        OpenAIConnector,
        "_handle_streaming_response",
        return_value=mock_handle,
    ):
        result_handle = await qwen_connector._handle_streaming_response(
            url="https://test.com",
            payload={},
            headers={"Authorization": "Bearer test"},
            session_id="test_session",
            stream_format="openai",
        )

        collected_chunks = []
        async for chunk in result_handle.iterator:
            collected_chunks.append(chunk)

        # Should only get 1 chunk (the other 2 are duplicates with different key ordering)
        assert len(collected_chunks) == 1
        assert collected_chunks[0].content["delta"]["content"] == "Test"


@pytest.mark.asyncio
async def test_deduplication_sliding_window(qwen_connector):
    """Test that the sliding window allows same content after window expires."""

    # Create chunks where "A" appears, then 10 other chunks, then "A" again
    chunks = [
        ProcessedResponse(content={"delta": {"content": "A"}, "id": "1"}),
    ]
    # Add 10 unique chunks to fill the window (maxlen=10)
    for i in range(10):
        chunks.append(
            ProcessedResponse(content={"delta": {"content": f"B{i}"}, "id": "1"})
        )
    # Add "A" again - should not be deduplicated since it's outside the window
    chunks.append(ProcessedResponse(content={"delta": {"content": "A"}, "id": "1"}))

    async def mock_iterator():
        for chunk in chunks:
            yield chunk

    from src.core.domain.responses import StreamingResponseHandle

    mock_handle = StreamingResponseHandle(
        iterator=mock_iterator(), cancel_callback=AsyncMock()
    )

    with patch.object(
        OpenAIConnector,
        "_handle_streaming_response",
        return_value=mock_handle,
    ):
        result_handle = await qwen_connector._handle_streaming_response(
            url="https://test.com",
            payload={},
            headers={"Authorization": "Bearer test"},
            session_id="test_session",
            stream_format="openai",
        )

        collected_chunks = []
        async for chunk in result_handle.iterator:
            collected_chunks.append(chunk)

        # Should get all 12 chunks (A, B0-B9, A again)
        assert len(collected_chunks) == 12
        assert collected_chunks[0].content["delta"]["content"] == "A"
        assert collected_chunks[-1].content["delta"]["content"] == "A"


@pytest.mark.asyncio
async def test_deduplication_with_string_chunks(qwen_connector):
    """Test deduplication works with string chunks."""

    string_chunks = [
        ProcessedResponse(content="data: test\n\n"),
        ProcessedResponse(content="data: test\n\n"),  # Duplicate
        ProcessedResponse(content="data: different\n\n"),
    ]

    async def mock_iterator():
        for chunk in string_chunks:
            yield chunk

    from src.core.domain.responses import StreamingResponseHandle

    mock_handle = StreamingResponseHandle(
        iterator=mock_iterator(), cancel_callback=AsyncMock()
    )

    with patch.object(
        OpenAIConnector,
        "_handle_streaming_response",
        return_value=mock_handle,
    ):
        result_handle = await qwen_connector._handle_streaming_response(
            url="https://test.com",
            payload={},
            headers={"Authorization": "Bearer test"},
            session_id="test_session",
            stream_format="openai",
        )

        collected_chunks = []
        async for chunk in result_handle.iterator:
            collected_chunks.append(chunk)

        # Should get 2 chunks (removed 1 duplicate)
        assert len(collected_chunks) == 2
        assert collected_chunks[0].content == "data: test\n\n"
        assert collected_chunks[1].content == "data: different\n\n"
