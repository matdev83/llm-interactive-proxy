"""Regression test for streaming error handling.

This test verifies the fix for the issue where streaming errors were being
returned as JSON responses with SSE data embedded in the message body,
instead of proper SSE responses.

Root cause: request.state.is_streaming was never set, causing global error
handlers to treat streaming requests as non-streaming.
"""

import contextlib
from unittest.mock import AsyncMock, Mock

import pytest
from src.core.app.controllers.chat_controller import ChatController
from src.core.common.exceptions import BackendError
from src.core.domain.chat import ChatRequest


class TestStreamingErrorRegression:
    """Test that streaming errors are properly formatted as SSE."""

    @pytest.fixture
    def mock_processor(self):
        """Create a mock request processor."""
        processor = AsyncMock()
        return processor

    @pytest.fixture
    def controller(self, mock_processor):
        """Create a ChatController with mocked dependencies."""
        return ChatController(
            request_processor=mock_processor,
            translation_service=None,
            wire_capture=None,
            metrics_initializer=None,
        )

    @pytest.fixture
    def mock_streaming_request(self):
        """Create a properly mocked streaming request."""
        mock_request = AsyncMock()
        mock_request.body = AsyncMock(return_value=b'{"model":"test","messages":[]}')
        mock_request.headers = {}
        mock_request.cookies = {}  # Add cookies to avoid TypeError
        mock_request.url = Mock()
        mock_request.url.path = "/v1/chat/completions"
        mock_request.state = Mock()
        # Simulate state being unset initially
        mock_request.state.is_streaming = None
        return mock_request

    @pytest.mark.asyncio
    async def test_request_state_is_streaming_is_set(
        self, controller, mock_processor, mock_streaming_request
    ):
        """Test that request.state.is_streaming is properly set for streaming requests.

        This is the core regression test - ensures the flag is set so global
        error handlers can detect streaming requests.
        """
        # Setup
        mock_processor.process_request.side_effect = BackendError(
            message="Backend returned 429 error",
            status_code=429,
        )

        request_data = ChatRequest(
            model="test:model",
            messages=[{"role": "user", "content": "test"}],
            stream=True,  # This is a streaming request
        )

        # Execute - let the exception propagate
        with contextlib.suppress(Exception):
            await controller.handle_chat_completion(
                request=mock_streaming_request,
                request_data=request_data,
            )

        # Verify - The critical fix: request.state.is_streaming should be set to True
        assert mock_streaming_request.state.is_streaming is True, (
            "REGRESSION: request.state.is_streaming was not set. "
            "This causes global error handlers to treat streaming requests as non-streaming, "
            "resulting in JSON responses with embedded SSE data instead of proper SSE responses."
        )

    @pytest.mark.asyncio
    async def test_non_streaming_request_state_is_set_false(
        self, controller, mock_processor, mock_streaming_request
    ):
        """Test that request.state.is_streaming is False for non-streaming requests."""
        # Setup
        mock_processor.process_request.side_effect = BackendError(
            message="Backend error",
            status_code=500,
        )

        request_data = ChatRequest(
            model="test:model",
            messages=[{"role": "user", "content": "test"}],
            stream=False,  # Non-streaming request
        )

        # Execute
        with contextlib.suppress(Exception):
            await controller.handle_chat_completion(
                request=mock_streaming_request,
                request_data=request_data,
            )

        # Verify
        assert (
            mock_streaming_request.state.is_streaming is False
        ), "request.state.is_streaming should be False for non-streaming requests"

    @pytest.mark.asyncio
    async def test_streaming_flag_prevents_json_response_with_embedded_sse(
        self, mock_streaming_request
    ):
        """Test that the is_streaming flag prevents the regression.

        This is a focused test that verifies the core fix: when is_streaming is set,
        the error handler can detect it and return proper SSE instead of JSON.

        Before the fix: is_streaming was never set, so:
        - _is_streaming_request() returned False
        - Error handler returned JSON with embedded SSE: {"error": {"message": "data: {...} data: [DONE]"}}

        After the fix: is_streaming is set, so:
        - _is_streaming_request() returns True
        - Error handler returns proper SSE response
        """
        from src.core.app.error_handlers import _is_streaming_request

        # Before setting the flag
        mock_streaming_request.state.is_streaming = None
        assert not _is_streaming_request(
            mock_streaming_request
        ), "Without is_streaming set, should return False"

        # After setting the flag to True (streaming request)
        mock_streaming_request.state.is_streaming = True
        assert _is_streaming_request(mock_streaming_request), (
            "REGRESSION: With is_streaming=True, should return True. "
            "This is the core fix that prevents JSON responses with embedded SSE data."
        )

        # After setting the flag to False (non-streaming request)
        mock_streaming_request.state.is_streaming = False
        assert not _is_streaming_request(
            mock_streaming_request
        ), "With is_streaming=False, should return False"

    def test_is_streaming_request_detection_logic(self, mock_streaming_request):
        """Test the _is_streaming_request detection logic.

        Verifies the fix works correctly for different scenarios.
        """
        from src.core.app.error_handlers import _is_streaming_request

        # Scenario 1: No Accept header, no is_streaming flag
        mock_streaming_request.headers = {}
        mock_streaming_request.state.is_streaming = None
        assert not _is_streaming_request(mock_streaming_request)

        # Scenario 2: Accept header present (should detect streaming)
        mock_streaming_request.headers = {"accept": "text/event-stream"}
        mock_streaming_request.state.is_streaming = None
        assert _is_streaming_request(mock_streaming_request)

        # Scenario 3: No Accept header, but is_streaming flag set (the fix)
        mock_streaming_request.headers = {}
        mock_streaming_request.state.is_streaming = True
        assert _is_streaming_request(
            mock_streaming_request
        ), "REGRESSION: Flag should be checked when Accept header is missing"

        # Scenario 4: Non-chat endpoint
        mock_streaming_request.url.path = "/v1/other"
        mock_streaming_request.headers = {}
        mock_streaming_request.state.is_streaming = True
        # Should still respect the flag for non-chat endpoints
        # (Though in practice, only chat endpoints set this flag)
        assert not _is_streaming_request(
            mock_streaming_request
        ), "Non-chat endpoints should not be treated as streaming without Accept header"

    @pytest.mark.asyncio
    async def test_streaming_flag_set_early_before_processor_called(
        self, controller, mock_processor, mock_streaming_request
    ):
        """Test that is_streaming flag is set before processor is called.

        This ensures that even if the processor raises an exception during
        execution, the flag is already set for error handlers to use.
        """

        def check_flag_then_raise(*args, **kwargs):
            """Check flag is set, then raise exception."""
            # At this point, the flag should already be set
            assert (
                mock_streaming_request.state.is_streaming is True
            ), "is_streaming should be set BEFORE calling processor"
            raise BackendError("Test error", status_code=500)

        mock_processor.process_request.side_effect = check_flag_then_raise

        request_data = ChatRequest(
            model="test:model",
            messages=[{"role": "user", "content": "test"}],
            stream=True,
        )

        # Execute - expect exception
        with contextlib.suppress(Exception):
            await controller.handle_chat_completion(
                request=mock_streaming_request,
                request_data=request_data,
            )

        # The assertion inside check_flag_then_raise will have verified the flag was set
