"""
Tests for empty response middleware.
"""

from unittest.mock import MagicMock, mock_open, patch

import pytest
from src.core.common.exceptions import BackendError
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.empty_response_middleware import (
    EmptyResponseMiddleware,
    EmptyResponseRetryException,
)


class TestEmptyResponseMiddleware:
    """Test cases for EmptyResponseMiddleware."""

    def test_init_default_values(self):
        """Test middleware initialization with default values."""
        middleware = EmptyResponseMiddleware()
        assert middleware._enabled is True
        assert middleware._max_retries == 1
        assert middleware._retry_counts == {}

    def test_init_custom_values(self):
        """Test middleware initialization with custom values."""
        middleware = EmptyResponseMiddleware(enabled=False, max_retries=3)
        assert middleware._enabled is False
        assert middleware._max_retries == 3

    @patch("builtins.open", mock_open(read_data="Test recovery prompt"))
    @patch("pathlib.Path.exists", return_value=True)
    def test_load_recovery_prompt_from_file(self, mock_exists):
        """Test loading recovery prompt from file."""
        middleware = EmptyResponseMiddleware()
        prompt = middleware._load_recovery_prompt()
        assert prompt == "Test recovery prompt"

    @patch("pathlib.Path.exists", return_value=False)
    def test_load_recovery_prompt_fallback(self, mock_exists):
        """Test fallback recovery prompt when file doesn't exist."""
        middleware = EmptyResponseMiddleware()
        prompt = middleware._load_recovery_prompt()
        assert "empty response" in prompt.lower()
        assert "valid response" in prompt.lower()

    def test_is_empty_response_with_content(self):
        """Test empty response detection with content."""
        middleware = EmptyResponseMiddleware()
        response = ProcessedResponse(content="Hello world")
        assert not middleware._is_empty_response(response)

    def test_is_empty_response_empty_content(self):
        """Test empty response detection with empty content."""
        middleware = EmptyResponseMiddleware()
        response = ProcessedResponse(content="")
        assert middleware._is_empty_response(response)

    def test_is_empty_response_whitespace_only(self):
        """Test empty response detection with whitespace-only content."""
        middleware = EmptyResponseMiddleware()
        response = ProcessedResponse(content="   \n\t  ")
        assert middleware._is_empty_response(response)

    def test_is_empty_response_with_tool_calls_in_metadata(self):
        """Test empty response detection with tool calls in metadata."""
        middleware = EmptyResponseMiddleware()
        response = ProcessedResponse(
            content="", metadata={"tool_calls": [{"function": {"name": "test"}}]}
        )
        assert not middleware._is_empty_response(response)

    def test_is_empty_response_with_tool_calls_in_context(self):
        """Test empty response detection with tool calls in context."""
        middleware = EmptyResponseMiddleware()
        response = ProcessedResponse(content="")
        context = {"tool_calls": [{"function": {"name": "test"}}]}
        assert not middleware._is_empty_response(response, context)

    def test_is_empty_response_with_original_response_tool_calls(self):
        """Test empty response detection with tool calls in original response."""
        middleware = EmptyResponseMiddleware()
        response = ProcessedResponse(content="")

        # Mock original response with tool calls
        original_response = MagicMock()
        original_response.tool_calls = [{"function": {"name": "test"}}]
        context = {"original_response": original_response}

        assert not middleware._is_empty_response(response, context)

    def test_is_empty_response_with_original_response_dict_tool_calls(self):
        """Test empty response detection with tool calls in original response dict."""
        middleware = EmptyResponseMiddleware()
        response = ProcessedResponse(content="")

        original_response = {
            "choices": [{"message": {"tool_calls": [{"function": {"name": "test"}}]}}]
        }
        context = {"original_response": original_response}

        assert not middleware._is_empty_response(response, context)

    @pytest.mark.asyncio
    async def test_process_disabled_middleware(self):
        """Test processing when middleware is disabled."""
        middleware = EmptyResponseMiddleware(enabled=False)
        response = ProcessedResponse(content="")

        result = await middleware.process(response, "session123")
        assert result == response

    @pytest.mark.asyncio
    async def test_process_non_empty_response(self):
        """Test processing non-empty response."""
        middleware = EmptyResponseMiddleware()
        response = ProcessedResponse(content="Hello world")

        result = await middleware.process(response, "session123")
        assert result == response
        assert "session123" not in middleware._retry_counts

    @pytest.mark.asyncio
    @patch("builtins.open", mock_open(read_data="Recovery prompt"))
    @patch("pathlib.Path.exists", return_value=True)
    async def test_process_empty_response_first_retry(self, mock_exists):
        """Test processing empty response on first retry."""
        middleware = EmptyResponseMiddleware()
        response = ProcessedResponse(content="")

        with pytest.raises(EmptyResponseRetryException) as exc_info:
            await middleware.process(response, "session123")

        assert exc_info.value.recovery_prompt == "Recovery prompt"
        assert exc_info.value.session_id == "session123"
        assert exc_info.value.retry_count == 1
        assert middleware._retry_counts["session123"] == 1

    @pytest.mark.asyncio
    async def test_process_empty_response_max_retries_exceeded(self):
        """Test processing empty response when max retries exceeded."""
        middleware = EmptyResponseMiddleware(max_retries=1)
        response = ProcessedResponse(content="")

        # Set retry count to max
        middleware._retry_counts["session123"] = 1

        with pytest.raises(BackendError) as exc_info:
            await middleware.process(response, "session123")

        assert "retry attempts" in str(exc_info.value).lower()
        assert "session123" not in middleware._retry_counts  # Should be reset

    @pytest.mark.asyncio
    async def test_process_successful_after_retry(self):
        """Test processing successful response after retry."""
        middleware = EmptyResponseMiddleware()
        response = ProcessedResponse(content="Success!")

        # Set retry count to simulate previous retry
        middleware._retry_counts["session123"] = 1

        result = await middleware.process(response, "session123")
        assert result == response
        assert "session123" not in middleware._retry_counts  # Should be reset

    def test_reset_session(self):
        """Test resetting session retry count."""
        middleware = EmptyResponseMiddleware()
        middleware._retry_counts["session123"] = 2

        middleware.reset_session("session123")
        assert "session123" not in middleware._retry_counts

    def test_reset_session_nonexistent(self):
        """Test resetting session that doesn't exist."""
        middleware = EmptyResponseMiddleware()

        # Should not raise an exception
        middleware.reset_session("nonexistent")


class TestEmptyResponseRetryException:
    """Test cases for EmptyResponseRetryException."""

    def test_exception_creation(self):
        """Test exception creation with all parameters."""
        exc = EmptyResponseRetryException(
            recovery_prompt="Test prompt", session_id="session123", retry_count=1
        )

        assert exc.recovery_prompt == "Test prompt"
        assert exc.session_id == "session123"
        assert exc.retry_count == 1
        assert "session123" in str(exc)
        assert "retry 1" in str(exc)
