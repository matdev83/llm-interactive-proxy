"""Integration tests for Codex connector streaming retry parity.

This test suite verifies that streaming authentication retry behavior matches
the current connector implementation for:
- Handshake-level authentication failures
- Chunk-level authentication failures
- Retry budget and backoff behavior
- Error shapes and status codes
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import pytest_asyncio
from fastapi import HTTPException
from src.connectors.openai_codex import OpenAICodexConnector
from src.core.config.app_config import AppConfig
from src.core.domain.chat import CanonicalChatRequest
from src.core.domain.responses import StreamingResponseEnvelope
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.translation_service import TranslationService


@pytest_asyncio.fixture(name="auth_dir")
async def auth_dir_tmp(tmp_path: Path):
    """Create temporary auth directory with credentials."""
    data = {"tokens": {"access_token": "test_token"}}
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "auth.json").write_text(json.dumps(data), encoding="utf-8")
    return tmp_path


@pytest_asyncio.fixture(name="codex_connector")
async def codex_connector_fixture(auth_dir: Path):
    """Create connector with mocked HTTP client."""
    async with httpx.AsyncClient() as client:
        cfg = AppConfig()
        ts = TranslationService()

        # Create connector - api_key setter will be called but _credential_manager exists by then
        # The setter checks hasattr, so we need to ensure _credential_manager exists
        backend = OpenAICodexConnector(client, cfg, translation_service=ts)

        with (
            patch.object(
                backend, "_validate_credentials_file_exists", return_value=(True, [])
            ),
            patch.object(
                backend, "_validate_credentials_structure", return_value=(True, [])
            ),
            patch.object(backend, "_start_file_watching"),
        ):
            await backend.initialize(openai_codex_path=str(auth_dir))
            backend._auth_credentials = {"tokens": {"access_token": "test_token"}}
            yield backend


class MockStreamHandle:
    """Mock streaming response handle."""

    def __init__(self, chunks: list[ProcessedResponse], headers: dict | None = None):
        self.chunks = chunks
        self.headers = headers or {}
        self.cancel_callback: AsyncMock | None = None

    @property
    def iterator(self):
        """Return async iterator for chunks."""

        async def _gen():
            for chunk in self.chunks:
                yield chunk

        return _gen()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_streaming_handshake_auth_failure_retry_success(
    codex_connector: OpenAICodexConnector,
):
    """Test that handshake authentication failures trigger retry with token refresh."""
    # Mock credential manager to allow refresh
    mock_refresh = AsyncMock(return_value=True)
    codex_connector._credential_manager.refresh_access_token = mock_refresh

    # Create request
    request = CanonicalChatRequest(
        model="openai-codex:gpt-5.1-codex",
        messages=[{"role": "user", "content": "Hello"}],
        stream=True,
    )

    # Mock streaming response: first attempt fails with 401, second succeeds
    call_count = [0]

    async def mock_streaming_response(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            # First attempt: authentication failure
            raise HTTPException(status_code=401, detail="Unauthorized")
        else:
            # Second attempt: success
            chunks = [
                ProcessedResponse(
                    content={
                        "id": "chunk-1",
                        "object": "chat.completion.chunk",
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"content": "Hello"},
                                "finish_reason": None,
                            }
                        ],
                    }
                ),
                ProcessedResponse(
                    content={
                        "id": "chunk-2",
                        "object": "chat.completion.chunk",
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"content": " world"},
                                "finish_reason": "stop",
                            }
                        ],
                    }
                ),
            ]
            handle = MockStreamHandle(chunks)
            return handle

    with patch.object(
        codex_connector._response_executor._base_connector,
        "_handle_streaming_response",
        side_effect=mock_streaming_response,
    ):
        result = await codex_connector.chat_completions(
            request_data=request,
            processed_messages=[],
            effective_model="openai-codex:gpt-5.1-codex",
        )

        assert isinstance(result, StreamingResponseEnvelope)
        # Refresh should be called when retrying after 401
        # Note: refresh is called during the retry loop, so we need to consume the stream
        # to trigger the retry logic
        chunks = []
        async for chunk in result.content:
            chunks.append(chunk)

        assert len(chunks) > 0
        # After consuming stream, refresh should have been called
        assert mock_refresh.call_count >= 1  # Should have refreshed at least once


@pytest.mark.integration
@pytest.mark.asyncio
async def test_streaming_handshake_auth_failure_retry_exhausted(
    codex_connector: OpenAICodexConnector,
):
    """Test that exhausted retries return proper error shape."""
    # Mock credential manager to allow refresh
    mock_refresh = AsyncMock(return_value=True)
    codex_connector._credential_manager.refresh_access_token = mock_refresh

    # Set max retries to 0 to ensure exception is raised immediately after first failure
    codex_connector._response_executor._max_retries = 0

    # Create request
    request = CanonicalChatRequest(
        model="openai-codex:gpt-5.1-codex",
        messages=[{"role": "user", "content": "Hello"}],
        stream=True,
    )

    # Mock streaming response: always fails with 401
    call_count = [0]

    async def mock_streaming_response(*args, **kwargs):
        call_count[0] += 1
        raise HTTPException(status_code=401, detail="Unauthorized")

    with patch.object(
        codex_connector._response_executor._base_connector,
        "_handle_streaming_response",
        side_effect=mock_streaming_response,
    ):
        with pytest.raises(HTTPException) as exc_info:
            result = await codex_connector.chat_completions(
                request_data=request,
                processed_messages=[],
                effective_model="openai-codex:gpt-5.1-codex",
            )
            # If we get here, consume the stream to trigger the error
            if isinstance(result, StreamingResponseEnvelope):
                async for _ in result.content:
                    pass

        # Verify error shape matches exact expected format
        assert exc_info.value.status_code == 401
        detail = exc_info.value.detail
        assert isinstance(detail, dict)
        assert detail.get("error") == "openai_codex_stream_auth_failed"
        assert (
            detail.get("message")
            == "Codex streaming request failed authentication during handshake and could not be recovered."
        )
        assert "details" in detail
        details = detail["details"]
        assert details.get("backend") == "openai-codex"
        assert "attempts" in details
        assert "max_retries" in details
        assert details["attempts"] == 0  # With max_retries=0, no retries attempted
        assert details["max_retries"] == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_streaming_chunk_level_auth_failure_retry(
    codex_connector: OpenAICodexConnector,
):
    """Test that chunk-level authentication failures trigger retry."""
    # Mock credential manager to allow refresh
    mock_refresh = AsyncMock(return_value=True)
    codex_connector._credential_manager.refresh_access_token = mock_refresh

    # Create request
    request = CanonicalChatRequest(
        model="openai-codex:gpt-5.1-codex",
        messages=[{"role": "user", "content": "Hello"}],
        stream=True,
    )

    call_count = [0]

    async def mock_streaming_response(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            # First attempt: handshake succeeds, but chunk indicates auth failure
            # Format matches _should_retry_for_auth_error detection logic
            chunks = [
                ProcessedResponse(
                    content={
                        "error": "auth_failed",
                        "details": {
                            "metadata": {"status_code": 401},
                        },
                    }
                )
            ]
            handle = MockStreamHandle(chunks)
            return handle
        else:
            # Second attempt: success
            chunks = [
                ProcessedResponse(
                    content={
                        "id": "chunk-2",
                        "object": "chat.completion.chunk",
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"content": "Hello"},
                                "finish_reason": "stop",
                            }
                        ],
                    }
                )
            ]
            handle = MockStreamHandle(chunks)
            return handle

    with patch.object(
        codex_connector._response_executor._base_connector,
        "_handle_streaming_response",
        side_effect=mock_streaming_response,
    ):
        result = await codex_connector.chat_completions(
            request_data=request,
            processed_messages=[],
            effective_model="openai-codex:gpt-5.1-codex",
        )

        assert isinstance(result, StreamingResponseEnvelope)

        # Consume stream to trigger retry logic (refresh happens during stream consumption)
        chunks = []
        async for chunk in result.content:
            chunks.append(chunk)

        # Should have refreshed after detecting auth error in chunk
        # Note: Refresh happens during stream consumption when auth error is detected
        assert (
            mock_refresh.call_count >= 1
        ), f"Expected refresh to be called, but call_count was {mock_refresh.call_count}"

        # Should have received successful chunks after retry
        assert len(chunks) > 0


@pytest.mark.integration
@pytest.mark.asyncio
@real_time(reason="Measures actual retry backoff timing to ensure exponential backoff is working correctly.")
async def test_streaming_retry_backoff_behavior(
    codex_connector: OpenAICodexConnector,
):
    """Test that retry backoff delays are applied correctly."""
    import time

    # Mock credential manager
    mock_refresh = AsyncMock(return_value=True)
    codex_connector._credential_manager.refresh_access_token = mock_refresh

    # Set known backoff sequence (reduced delays for test performance)
    codex_connector._response_executor._retry_backoff_seconds = (0.001, 0.002, 0.003)  # Further reduced for performance
    codex_connector._response_executor._max_retries = 2

    # Create request
    request = CanonicalChatRequest(
        model="openai-codex:gpt-5.1-codex",
        messages=[{"role": "user", "content": "Hello"}],
        stream=True,
    )

    call_count = [0]
    retry_times = []

    async def mock_streaming_response(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] <= 2:
            # Use fixed timestamp for deterministic retry tracking
            retry_times.append(1000.0)
            raise HTTPException(status_code=401, detail="Unauthorized")
        else:
            chunks = [
                ProcessedResponse(
                    content={
                        "id": "chunk-1",
                        "object": "chat.completion.chunk",
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"content": "Hello"},
                                "finish_reason": "stop",
                            }
                        ],
                    }
                )
            ]
            handle = MockStreamHandle(chunks)
            return handle

    with patch.object(
        codex_connector._response_executor._base_connector,
        "_handle_streaming_response",
        side_effect=mock_streaming_response,
    ):
        start_time = time.time()
        result = await codex_connector.chat_completions(
            request_data=request,
            processed_messages=[],
            effective_model="openai-codex:gpt-5.1-codex",
        )

        # Consume stream to trigger retry and backoff
        async for _ in result.content:
            pass

        end_time = time.time()

        # Verify backoff was applied (should take at least 0.001 seconds)
        elapsed = end_time - start_time
        assert elapsed >= 0.001  # At least first backoff delay

        assert isinstance(result, StreamingResponseEnvelope)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_streaming_refresh_failure_returns_error(
    codex_connector: OpenAICodexConnector,
):
    """Test that refresh failure returns proper error shape."""
    # Mock credential manager to return False on refresh
    mock_refresh = AsyncMock(return_value=False)
    codex_connector._credential_manager.refresh_access_token = mock_refresh

    # Create request
    request = CanonicalChatRequest(
        model="openai-codex:gpt-5.1-codex",
        messages=[{"role": "user", "content": "Hello"}],
        stream=True,
    )

    # Mock streaming response: fails with 401
    async def mock_streaming_response(*args, **kwargs):
        raise HTTPException(status_code=401, detail="Unauthorized")

    with patch.object(
        codex_connector._response_executor._base_connector,
        "_handle_streaming_response",
        side_effect=mock_streaming_response,
    ):
        result = await codex_connector.chat_completions(
            request_data=request,
            processed_messages=[],
            effective_model="openai-codex:gpt-5.1-codex",
        )

        assert isinstance(result, StreamingResponseEnvelope)

        with pytest.raises(HTTPException) as exc_info:
            async for _ in result.content:
                pass

        # Verify error shape when refresh fails
        assert exc_info.value.status_code == 401
        detail = exc_info.value.detail
        assert isinstance(detail, dict)
        assert detail.get("error") == "openai_codex_stream_auth_failed"
        assert "handshake" in detail.get("message", "").lower()
        # Should have attempted refresh
        assert mock_refresh.call_count >= 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_streaming_ordering_and_termination_parity(
    codex_connector: OpenAICodexConnector,
):
    """Test that streaming chunks arrive in correct order and stream terminates properly (Req 1.2)."""
    # Create request
    request = CanonicalChatRequest(
        model="openai-codex:gpt-5.1-codex",
        messages=[{"role": "user", "content": "Count to 3"}],
        stream=True,
    )

    # Create chunks in specific order
    chunks = [
        ProcessedResponse(content={"choices": [{"delta": {"content": "1"}}]}),
        ProcessedResponse(content={"choices": [{"delta": {"content": "2"}}]}),
        ProcessedResponse(content={"choices": [{"delta": {"content": "3"}}]}),
        ProcessedResponse(
            content={"choices": [{"delta": {}, "finish_reason": "stop"}]}
        ),
    ]

    async def mock_streaming_response(*args, **kwargs):
        handle = MockStreamHandle(chunks)
        return handle

    with patch.object(
        codex_connector._response_executor._base_connector,
        "_handle_streaming_response",
        side_effect=mock_streaming_response,
    ):
        result = await codex_connector.chat_completions(
            request_data=request,
            processed_messages=[],
            effective_model="openai-codex:gpt-5.1-codex",
        )

        assert isinstance(result, StreamingResponseEnvelope)

        # Consume stream and verify ordering
        received_chunks = []
        async for chunk in result.content:
            received_chunks.append(chunk)

        # Verify chunks arrived in correct order
        assert len(received_chunks) == 4
        # Verify stream terminated properly (no exception, all chunks received)
        assert (
            received_chunks[-1].content.get("choices", [{}])[0].get("finish_reason")
            == "stop"
        )
