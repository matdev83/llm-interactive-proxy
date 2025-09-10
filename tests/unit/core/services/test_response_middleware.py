"""Tests for response middleware functionality."""

from unittest.mock import MagicMock

import pytest
from src.core.common.exceptions import LoopDetectionError
from src.core.interfaces.loop_detector_interface import ILoopDetector
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.response_middleware import (
    ContentFilterMiddleware,
    LoggingMiddleware,
    LoopDetectionMiddleware,
)


class TestLoggingMiddleware:
    """Test the LoggingMiddleware functionality."""

    @pytest.fixture
    def middleware(self):
        """Create a LoggingMiddleware instance."""
        return LoggingMiddleware()

    @pytest.mark.asyncio
    async def test_process_logs_response_info(self, middleware, caplog):
        """Test that middleware logs response information."""
        response = ProcessedResponse(
            content="Test response content",
            usage={"prompt_tokens": 10, "completion_tokens": 20},
            metadata={"test": "value"},
        )

        context = {"response_type": "test"}
        result = await middleware.process(response, "session123", context)

        assert result == response
        # Check that logging occurred (we can't easily test debug logs in pytest without specific config)

    @pytest.mark.asyncio
    async def test_process_handles_empty_response(self, middleware):
        """Test middleware handles empty responses gracefully."""
        response = ProcessedResponse(content="")
        context = {}

        result = await middleware.process(response, "session123", context)
        assert result == response


class TestContentFilterMiddleware:
    """Test the ContentFilterMiddleware functionality."""

    @pytest.fixture
    def middleware(self):
        """Create a ContentFilterMiddleware instance."""
        return ContentFilterMiddleware()

    @pytest.mark.asyncio
    async def test_process_filters_prefix(self, middleware):
        """Test that middleware filters specific content prefixes."""
        original_content = "I'll help you with that. Here's the answer."
        response = ProcessedResponse(content=original_content)

        result = await middleware.process(response, "session123", {})

        assert isinstance(result, ProcessedResponse)
        assert result.content == "Here's the answer."
        assert result.usage == response.usage
        assert result.metadata == response.metadata

    @pytest.mark.asyncio
    async def test_process_preserves_other_content(self, middleware):
        """Test that middleware preserves content that doesn't match filter."""
        original_content = "This is a normal response without the prefix."
        response = ProcessedResponse(content=original_content)

        result = await middleware.process(response, "session123", {})

        assert isinstance(result, ProcessedResponse)
        assert result.content == original_content

    @pytest.mark.asyncio
    async def test_process_handles_empty_content(self, middleware):
        """Test middleware handles empty content."""
        response = ProcessedResponse(content="")

        result = await middleware.process(response, "session123", {})

        assert result == response


class TestLoopDetectionMiddleware:
    """Test the LoopDetectionMiddleware functionality."""

    @pytest.fixture
    def mock_loop_detector(self):
        """Create a mock loop detector."""
        detector = MagicMock(spec=ILoopDetector)
        return detector

    @pytest.fixture
    def middleware(self, mock_loop_detector):
        """Create a LoopDetectionMiddleware instance."""
        return LoopDetectionMiddleware(mock_loop_detector)

    @pytest.mark.asyncio
    async def test_process_no_loop_detected(self, middleware, mock_loop_detector):
        """Test middleware processes normally when no loop is detected."""
        # Setup mock to return no loop
        mock_result = MagicMock()
        mock_result.has_loop = False
        mock_loop_detector.check_for_loops.return_value = mock_result

        # Use long enough content to trigger loop detection check (> 100 chars)
        long_content = (
            "Normal content that is long enough to trigger loop detection check. " * 5
        )
        response = ProcessedResponse(content=long_content)
        result = await middleware.process(response, "session123", {})

        assert result == response
        mock_loop_detector.check_for_loops.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_loop_detected_raises_error(
        self, middleware, mock_loop_detector
    ):
        """Test middleware raises error when loop is detected."""
        # Setup mock to return loop detected
        mock_result = MagicMock()
        mock_result.has_loop = True
        mock_result.repetitions = 3
        mock_result.pattern = "ERROR"
        mock_loop_detector.check_for_loops.return_value = mock_result

        response = ProcessedResponse(content="ERROR" * 50)  # Long enough content

        with pytest.raises(LoopDetectionError) as exc_info:
            await middleware.process(response, "session123", {})

        assert "Loop detected" in str(exc_info.value)
        assert exc_info.value.details["repetitions"] == 3
        assert exc_info.value.details["pattern"] == "ERROR"

    @pytest.mark.asyncio
    async def test_process_short_content_no_check(self, middleware, mock_loop_detector):
        """Test middleware doesn't check for loops in short content."""
        response = ProcessedResponse(content="Short")

        result = await middleware.process(response, "session123", {})

        assert result == response
        mock_loop_detector.check_for_loops.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_accumulates_content(self, middleware, mock_loop_detector):
        """Test middleware accumulates content across multiple calls."""
        # Setup mock to return no loop initially
        mock_result = MagicMock()
        mock_result.has_loop = False
        mock_loop_detector.check_for_loops.return_value = mock_result

        # First call with content that won't trigger check yet
        response1 = ProcessedResponse(content="Part 1 ")
        result1 = await middleware.process(response1, "session123", {})
        assert result1 == response1

        # Second call with enough content to trigger check
        long_content = (
            "Part 2 that makes the total content exceed 100 characters for loop detection. "
            * 3
        )
        response2 = ProcessedResponse(content=long_content)
        result2 = await middleware.process(response2, "session123", {})
        assert result2 == response2

        # Check that accumulated content was passed to detector
        args, kwargs = mock_loop_detector.check_for_loops.call_args
        assert "Part 1" in args[0] and "Part 2" in args[0]

    def test_reset_session(self, middleware):
        """Test resetting session accumulated content."""
        # Manually add content to test reset
        middleware._accumulated_content["session123"] = "test content"

        middleware.reset_session("session123")

        assert "session123" not in middleware._accumulated_content

    def test_reset_nonexistent_session(self, middleware):
        """Test resetting a session that doesn't exist doesn't error."""
        # Should not raise any exception
        middleware.reset_session("nonexistent")

    def test_priority_property(self, mock_loop_detector):
        """Test priority property."""
        middleware = LoopDetectionMiddleware(mock_loop_detector, priority=10)
        assert middleware.priority == 10
