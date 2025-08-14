"""
Unit tests for the response middleware system.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from src.loop_detection.config import LoopDetectionConfig
from src.response_middleware import (
    LoopDetectionProcessor,
    RequestContext,
    ResponseMiddleware,
    ResponseProcessor,
    configure_loop_detection_middleware,
    get_response_middleware,
)


class TestResponseMiddleware:
    """Test the ResponseMiddleware class."""

    def test_middleware_initialization(self):
        """Test that middleware initializes correctly."""
        middleware = ResponseMiddleware()
        assert len(middleware.middleware_stack) == 0

    def test_add_processor(self):
        """Test adding processors to middleware."""
        middleware = ResponseMiddleware()
        processor = ResponseProcessor()

        middleware.add_processor(processor)
        assert len(middleware.middleware_stack) == 1
        assert middleware.middleware_stack[0] is processor

    def test_remove_processor(self):
        """Test removing processors by type."""
        middleware = ResponseMiddleware()
        processor1 = ResponseProcessor()
        processor2 = LoopDetectionProcessor(LoopDetectionConfig())

        middleware.add_processor(processor1)
        middleware.add_processor(processor2)
        assert len(middleware.middleware_stack) == 2

        middleware.remove_processor(LoopDetectionProcessor)
        assert len(middleware.middleware_stack) == 1
        assert isinstance(middleware.middleware_stack[0], ResponseProcessor)
        assert not isinstance(middleware.middleware_stack[0], LoopDetectionProcessor)

    @pytest.mark.asyncio
    async def test_process_response_no_processors(self):
        """Test processing response with no processors."""
        middleware = ResponseMiddleware()
        context = RequestContext("test-session", "openrouter", "gpt-4", False)
        response = {"test": "response"}

        result = await middleware.process_response(response, context)
        assert result == response

    @pytest.mark.asyncio
    async def test_process_response_with_processors(self):
        """Test processing response through processors."""
        middleware = ResponseMiddleware()

        # Create mock processor
        processor = MagicMock(spec=ResponseProcessor)
        processor.should_process.return_value = True
        processor.process = AsyncMock(return_value={"processed": True})

        middleware.add_processor(processor)

        context = RequestContext("test-session", "openrouter", "gpt-4", False)
        response = {"test": "response"}

        result = await middleware.process_response(response, context)

        processor.should_process.assert_called_once_with(response, context)
        processor.process.assert_called_once_with(response, context)
        assert result == {"processed": True}


class TestRequestContext:
    """Test the RequestContext class."""

    def test_context_creation(self):
        """Test creating RequestContext instances."""
        context = RequestContext(
            session_id="test-session",
            backend_type="openrouter",
            model="gpt-4",
            is_streaming=True,
            request_data={"test": "data"},
            extra_param="value",
        )

        assert context.session_id == "test-session"
        assert context.backend_type == "openrouter"
        assert context.model == "gpt-4"
        assert context.is_streaming == True
        assert context.request_data == {"test": "data"}
        assert context.metadata["extra_param"] == "value"


class TestLoopDetectionProcessor:
    """Test the LoopDetectionProcessor class."""

    def test_processor_initialization(self):
        """Test that processor initializes correctly."""
        config = LoopDetectionConfig(enabled=True)
        processor = LoopDetectionProcessor(config)

        assert processor.config.enabled == True
        assert len(processor._detectors) == 0

    def test_should_process_enabled(self):
        """Test should_process when loop detection is enabled."""
        config = LoopDetectionConfig(enabled=True)
        processor = LoopDetectionProcessor(config)
        context = RequestContext("test-session", "openrouter", "gpt-4", False)

        assert processor.should_process({}, context) == True

    def test_should_process_disabled(self):
        """Test should_process when loop detection is disabled."""
        config = LoopDetectionConfig(enabled=False)
        processor = LoopDetectionProcessor(config)
        context = RequestContext("test-session", "openrouter", "gpt-4", False)

        assert processor.should_process({}, context) == False

    def test_get_or_create_detector(self):
        """Test detector creation and caching."""
        config = LoopDetectionConfig(enabled=True)
        processor = LoopDetectionProcessor(config)

        # First call should create detector
        detector1 = processor._get_or_create_detector("session1")
        assert "session1" in processor._detectors

        # Second call should return same detector
        detector2 = processor._get_or_create_detector("session1")
        assert detector1 is detector2

        # Different session should create different detector
        detector3 = processor._get_or_create_detector("session2")
        assert detector3 is not detector1
        assert "session2" in processor._detectors

    @pytest.mark.asyncio
    async def test_process_non_streaming_response(self):
        """Test processing non-streaming responses."""
        config = LoopDetectionConfig(enabled=True)
        processor = LoopDetectionProcessor(config)
        context = RequestContext("test-session", "openrouter", "gpt-4", False)

        response = {
            "choices": [
                {"message": {"content": "This is a normal response without loops."}}
            ]
        }

        result = await processor.process(response, context)
        # Should return original response if no loops detected
        assert result == response

    def test_cleanup_session(self):
        """Test session cleanup."""
        config = LoopDetectionConfig(enabled=True)
        processor = LoopDetectionProcessor(config)

        # Create detector for session
        processor._get_or_create_detector("test-session")
        assert "test-session" in processor._detectors

        # Cleanup session
        processor.cleanup_session("test-session")
        assert "test-session" not in processor._detectors


class TestGlobalMiddleware:
    """Test global middleware configuration."""

    def test_configure_loop_detection_middleware(self):
        """Test configuring loop detection middleware."""
        config = LoopDetectionConfig(enabled=True)

        # Configure middleware
        configure_loop_detection_middleware(config)

        # Check that processor was added
        middleware = get_response_middleware()
        assert len(middleware.middleware_stack) > 0

        # Find loop detection processor
        loop_processors = [
            p
            for p in middleware.middleware_stack
            if isinstance(p, LoopDetectionProcessor)
        ]
        assert len(loop_processors) == 1
        assert loop_processors[0].config.enabled == True

    def test_configure_disabled_loop_detection(self):
        """Test configuring disabled loop detection."""
        config = LoopDetectionConfig(enabled=False)

        # Configure middleware
        configure_loop_detection_middleware(config)

        # Check that no loop detection processor was added
        middleware = get_response_middleware()
        loop_processors = [
            p
            for p in middleware.middleware_stack
            if isinstance(p, LoopDetectionProcessor)
        ]
        assert len(loop_processors) == 0

    def test_reconfigure_middleware(self):
        """Test reconfiguring middleware removes old processors."""
        # First configuration
        config1 = LoopDetectionConfig(enabled=True, buffer_size=1024)
        configure_loop_detection_middleware(config1)

        middleware = get_response_middleware()
        initial_count = len(middleware.middleware_stack)

        # Second configuration should replace the first
        config2 = LoopDetectionConfig(enabled=True, buffer_size=2048)
        configure_loop_detection_middleware(config2)

        # Should have same number of processors (old one replaced)
        assert len(middleware.middleware_stack) == initial_count

        # New processor should have new config
        loop_processors = [
            p
            for p in middleware.middleware_stack
            if isinstance(p, LoopDetectionProcessor)
        ]
        assert len(loop_processors) == 1
        assert loop_processors[0].config.buffer_size == 2048


if __name__ == "__main__":
    pytest.main([__file__])
