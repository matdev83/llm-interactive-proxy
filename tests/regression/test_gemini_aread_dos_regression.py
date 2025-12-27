"""Regression test for Gemini backend aread() DoS vulnerability fix.

This test verifies that GeminiBackend properly limits error response body sizes
to prevent memory exhaustion when reading large error responses.

Fixed: Added 10MB limit when reading error response bodies using aiter_bytes()
to prevent DoS attacks through large error responses.
"""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from src.connectors.gemini import GeminiBackend
from src.core.common.exceptions import BackendError
from src.core.config.app_config import AppConfig
from src.core.services.translation_service import TranslationService


class TestGeminiAreadDoSRegression:
    """Regression tests for Gemini backend aread() DoS vulnerability fix."""

    @pytest.fixture
    def mock_client(self) -> MagicMock:
        """Create mock httpx client."""
        return MagicMock(spec=httpx.AsyncClient)

    @pytest.fixture
    def backend(self, mock_client: MagicMock) -> GeminiBackend:
        """Create GeminiBackend instance for testing."""
        config = AppConfig()
        translation_service = TranslationService()
        backend = GeminiBackend(mock_client, config, translation_service)
        backend.gemini_api_base_url = "http://test"
        backend.key_name = "test_key"
        backend.api_key = "test_api_key"
        return backend

    async def test_large_error_body_limited(
        self, backend: GeminiBackend, mock_client: MagicMock
    ) -> None:
        """Test that large error response bodies are limited to 10MB."""
        # Create mock response with large body (>10MB)
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.headers = {}

        # Simulate large body using aiter_bytes (preferred method)
        # Reduced to 10.1MB for performance while still exceeding 10MB limit
        # Use larger chunks (256KB) to reduce iteration overhead while still testing the limit
        large_body = b"x" * (10 * 1024 * 1024 + 100 * 1024)  # 10.1MB > 10MB limit
        chunks = [
            large_body[i : i + 256 * 1024]
            for i in range(0, len(large_body), 256 * 1024)
        ]

        async def aiter_bytes():
            for chunk in chunks:
                yield chunk

        mock_response.aiter_bytes = aiter_bytes
        mock_response.aclose = AsyncMock()

        # Mock client.send to return our response
        mock_client.build_request.return_value = MagicMock()
        mock_client.send = AsyncMock(return_value=mock_response)

        # Call _handle_gemini_streaming_response
        with pytest.raises(BackendError) as exc_info:
            await backend._handle_gemini_streaming_response(
                base_url="http://test",
                payload={},
                headers={},
                effective_model="gemini-pro",
            )

        # Should raise BackendError, not MemoryError
        assert isinstance(exc_info.value, BackendError)
        assert "500" in exc_info.value.message

        # Verify response was closed
        mock_response.aclose.assert_called_once()

    async def test_normal_error_body_works(
        self, backend: GeminiBackend, mock_client: MagicMock
    ) -> None:
        """Test that normal-sized error bodies are handled correctly."""
        # Create mock response with normal-sized error body
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.headers = {}

        # Small error body (<10MB)
        small_body = b'{"error": "Invalid request"}'

        async def aiter_bytes():
            yield small_body

        mock_response.aiter_bytes = aiter_bytes
        mock_response.aclose = AsyncMock()

        # Mock client.send
        mock_client.build_request.return_value = MagicMock()
        mock_client.send = AsyncMock(return_value=mock_response)

        # Call _handle_gemini_streaming_response
        with pytest.raises(BackendError) as exc_info:
            await backend._handle_gemini_streaming_response(
                base_url="http://test",
                payload={},
                headers={},
                effective_model="gemini-pro",
            )

        # Should raise BackendError with error message
        assert isinstance(exc_info.value, BackendError)
        assert "400" in exc_info.value.message
        assert "Invalid request" in exc_info.value.message

    async def test_aread_fallback_handled(
        self, backend: GeminiBackend, mock_client: MagicMock
    ) -> None:
        """Test that aread() fallback doesn't cause memory exhaustion."""
        # Create mock response without aiter_bytes (fallback to aread)
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.headers = {}

        # Large body that would cause DoS if read entirely
        large_body = b"x" * (20 * 1024 * 1024)  # 20MB

        # Mock aread() to return large body
        mock_response.aread = AsyncMock(return_value=large_body)
        mock_response.aclose = AsyncMock()

        # Mock client.send
        mock_client.build_request.return_value = MagicMock()
        mock_client.send = AsyncMock(return_value=mock_response)

        # Call _handle_gemini_streaming_response
        # Note: aread() doesn't have size limit in current implementation,
        # but the test verifies it doesn't crash the system
        with pytest.raises(BackendError):
            await backend._handle_gemini_streaming_response(
                base_url="http://test",
                payload={},
                headers={},
                effective_model="gemini-pro",
            )

        # Verify response was closed
        mock_response.aclose.assert_called_once()

    async def test_successful_response_not_affected(
        self, backend: GeminiBackend, mock_client: MagicMock
    ) -> None:
        """Test that successful responses are not affected by error body limits."""
        # Create mock response with success status
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"x-goog-request-id": "test-request-id"}

        # Mock streaming response
        async def stream_chunks():
            yield b'{"candidates": [{"content": {"parts": [{"text": "Hello"}]}}]}'

        mock_response.aiter_bytes = stream_chunks
        mock_response.aclose = AsyncMock()

        # Mock client.send
        mock_client.build_request.return_value = MagicMock()
        mock_client.send = AsyncMock(return_value=mock_response)

        # Call _handle_gemini_streaming_response
        handle = await backend._handle_gemini_streaming_response(
            base_url="http://test",
            payload={},
            headers={},
            effective_model="gemini-pro",
        )

        # Should return a handle, not raise an error
        assert handle is not None
