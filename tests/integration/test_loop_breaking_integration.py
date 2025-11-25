"""Integration tests for complete loop breaking flow.

Tests the complete loop breaking functionality:
1. Stream processing with loop detection
2. API cancellation triggered by LoopBreakingService
3. Steering message generation
4. Retry request with steering message
5. End-to-end integration with request processor service
"""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.configuration.assessment_config import AssessmentConfig
from src.core.ports.streaming_contracts import StreamingContent
from src.core.services.loop_breaking_service import LoopBreakingService
from src.loop_detection.event import LoopDetectionEvent

logger = logging.getLogger(__name__)


class TestLoopBreakingIntegration:
    """Integration tests for complete loop breaking flow."""

    @pytest.fixture
    def mock_services(self):
        """Create mock services for testing."""
        from src.core.interfaces.loop_detector_interface import ILoopDetector

        # Mock dependencies
        mock_loop_detector = AsyncMock(spec=ILoopDetector)
        mock_assessment_service = AsyncMock()
        mock_backend_processor = AsyncMock()
        mock_prompt_loader = MagicMock()

        # Configure mock prompt loader to return templates
        mock_prompt_loader.steering_template = (
            "[SYSTEM NOTICE] Loop detected: {reasoning}. "
            "Please stop repeating this pattern and provide a helpful response."
        )

        return {
            "loop_detector": mock_loop_detector,
            "assessment_service": mock_assessment_service,
            "backend_processor": mock_backend_processor,
            "prompt_loader": mock_prompt_loader,
        }

    @pytest.fixture
    def assessment_config(self):
        """Create assessment configuration for testing."""
        return AssessmentConfig(
            turn_threshold=30,
            confidence_threshold=0.9,
            history_window=20,
        )

    @pytest.mark.asyncio
    async def test_streaming_with_loop_breaking_service(
        self, mock_services, assessment_config
    ):
        """Test LoopBreakingService integration with streaming response."""
        # Given
        loop_breaking_service = LoopBreakingService(
            loop_detector=mock_services["loop_detector"],
            assessment_service=mock_services["assessment_service"],
            backend_processor=mock_services["backend_processor"],
            assessment_config=assessment_config,
        )

        # Mock assessment service to return high confidence
        mock_services["assessment_service"].assess_conversation.return_value = (
            MagicMock(
                reasoning="repetitive content pattern detected",
                confidence=0.95,  # Above threshold
                turn_count=5,
                session_id="test_session_123",
            )
        )

        # When - Process streaming content with loop detection
        content = StreamingContent(
            content="I am now complete. I am now finished. I will now exit.",
            is_done=False,
        )
        cancel_callback = AsyncMock()

        result_content, should_break = (
            await loop_breaking_service.process_streaming_content(
                content, "test_session_123", cancel_callback
            )
        )

        # Then
        assert should_break is True
        assert result_content.is_cancellation is True
        assert "[LOOP BROKEN]" in result_content.content
        assert cancel_callback.call_count == 1
        assert mock_services["assessment_service"].assess_conversation.call_count == 1

    @pytest.mark.asyncio
    async def test_response_processor_with_loop_breaking(self, mock_services):
        """Test ResponseProcessor with loop breaking integration."""
        loop_breaking_service = LoopBreakingService(
            loop_detector=mock_services["loop_detector"],
            assessment_service=mock_services["assessment_service"],
            backend_processor=mock_services["backend_processor"],
        )

        mock_services["loop_detector"].process_chunk.return_value = LoopDetectionEvent(
            pattern="I am now complete. I am now finished.",
            pattern_length=35,
            repetition_count=5,
            total_length=50,
            confidence=0.95,
            buffer_content="I am now complete. I am now finished.",
            timestamp=0.0,
        )

        streaming_content = StreamingContent(content="loop", is_done=False)
        cancel_callback = AsyncMock()

        result_content, should_break = (
            await loop_breaking_service.process_streaming_content(
                streaming_content,
                "test_session_456",
                cancel_callback,
            )
        )

        assert should_break is True
        assert result_content.metadata["loop_detected"] is True
        cancel_callback.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_backend_request_manager_with_loop_breaking(
        self, mock_services, assessment_config
    ):
        loop_breaking_service = LoopBreakingService(
            loop_detector=mock_services["loop_detector"],
            assessment_service=mock_services["assessment_service"],
            backend_processor=mock_services["backend_processor"],
            assessment_config=assessment_config,
        )

        mock_services["loop_detector"].process_chunk.return_value = LoopDetectionEvent(
            pattern="test pattern for loop breaking",
            pattern_length=25,
            repetition_count=4,
            total_length=30,
            confidence=0.90,
            buffer_content="test pattern for loop breaking",
            timestamp=0.0,
        )

        original_request = ChatRequest(
            messages=[ChatMessage(role="user", content="Test for loop breaking")],
            model="gpt-4o",
        )
        mock_services["backend_processor"].process_backend_request.return_value = (
            MagicMock(
                content="Successfully retried with steering",
                metadata={
                    "retry_success": True,
                    "session_id": "test_session_integration",
                },
            )
        )

        await loop_breaking_service.process_loop_breaking_retry(
            original_request,
            mock_services["loop_detector"].process_chunk.return_value,
            "test_session_integration",
        )

        mock_services["backend_processor"].process_backend_request.assert_awaited()

    @pytest.mark.asyncio
    async def test_end_to_end_flow_with_api_cancellation(self, mock_services):
        """Test complete end-to-end flow including API cancellation."""
        # Given
        loop_breaking_service = LoopBreakingService(
            loop_detector=mock_services["loop_detector"],
            assessment_service=mock_services["assessment_service"],
            backend_processor=mock_services["backend_processor"],
        )

        # Mock successful API cancellation
        cancel_callback = AsyncMock()

        # When - Process streaming content with loop
        content = "repetitive loop content " * 6  # Loop pattern
        streaming_content = StreamingContent(content=content, is_done=False)

        result_content, should_break = (
            await loop_breaking_service.process_streaming_content(
                streaming_content, "test_end_to_end", cancel_callback
            )
        )

        # Then
        assert should_break is True
        assert cancel_callback.call_count == 1
        assert "[LOOP BROKEN]" in result_content.content

        # Test cancellation failure handling
        cancel_callback.side_effect = Exception("Cancellation failed")

        # When - Process content again
        result_content, should_break = (
            await loop_breaking_service.process_streaming_content(
                streaming_content, "test_cancellation_failure", cancel_callback
            )
        )

        # Then
        assert should_break is True
        assert cancel_callback.call_count == 2  # Should still be attempted
        # Should still break content even if cancellation fails
        assert "[LOOP BROKEN]" in result_content.content

    @pytest.mark.asyncio
    async def test_confidence_threshold_behavior(
        self, mock_services, assessment_config
    ):
        """Test loop breaking behavior with different confidence levels."""
        # Given
        loop_breaking_service = LoopBreakingService(
            loop_detector=mock_services["loop_detector"],
            assessment_service=mock_services["assessment_service"],
            backend_processor=mock_services["backend_processor"],
            assessment_config=assessment_config,
        )

        # Given - Assessment below threshold
        mock_services["assessment_service"].assess_conversation.return_value = (
            MagicMock(
                reasoning="low confidence pattern",
                confidence=0.8,  # Below 0.9 threshold
                turn_count=3,
                session_id="test_low_confidence",
            )
        )
        detection_event = LoopDetectionEvent(
            pattern="test pattern",
            pattern_length=12,
            repetition_count=3,
            total_length=15,  # Reasonable total length
            confidence=0.85,  # Moderate confidence
            buffer_content="test pattern",
            timestamp=0.0,  # Fixed timestamp for testing
        )

        # When
        steering_message = await loop_breaking_service._generate_steering_message(
            detection_event, "test_low_confidence"
        )

        # Then
        assert "getting stuck" in steering_message.lower()
        assessment_call_args = mock_services[
            "assessment_service"
        ].assess_conversation.call_args
        assert assessment_call_args.args[1] == "test_low_confidence"

    @pytest.mark.asyncio
    async def test_real_world_loop_scenario(self, mock_services, assessment_config):
        """Test with real-world loop pattern from wire capture."""
        # Given - Real-world loop pattern
        real_world_pattern = "I am now complete. I am now finished. I will now exit. I am now done. I will now stop."

        # Mock the steering template function
        with patch(
            "src.core.services.loop_breaking_service.get_steering_template"
        ) as mock_get_template:
            mock_get_template.return_value = (
                "[SYSTEM NOTICE] Loop detected: {reasoning}. "
                "Please stop repeating this pattern and provide a helpful response."
            )

            loop_breaking_service = LoopBreakingService(
                loop_detector=mock_services["loop_detector"],
                assessment_service=mock_services["assessment_service"],
                backend_processor=mock_services["backend_processor"],
                assessment_config=assessment_config,
            )

            detection_event = LoopDetectionEvent(
                pattern=real_world_pattern,
                pattern_length=len(real_world_pattern),
                repetition_count=6,  # High repetition count
                total_length=len(real_world_pattern) * 2,  # Reasonable total length
                confidence=0.98,  # High confidence
                buffer_content=real_world_pattern,
                timestamp=0.0,  # Fixed timestamp for testing
            )

            # Mock high confidence assessment
            mock_services["assessment_service"].assess_conversation.return_value = (
                MagicMock(
                    reasoning="severe repetitive loop detected with high confidence",
                    confidence=0.98,  # Well above threshold
                    turn_count=8,
                    session_id="real_world_test",
                )
            )

            # When
            steering_message = await loop_breaking_service._generate_steering_message(
                detection_event, "real_world_test"
            )

            # Then
            assert "SYSTEM NOTICE" in steering_message
            assert "repetitive loop detected" in steering_message.lower()

            # Verify assessment was called with correct session_id
            call_args = mock_services[
                "assessment_service"
            ].assess_conversation.call_args
            assert call_args.args[1] == "real_world_test"

            # Test break content creation
            break_content = loop_breaking_service._create_break_content(
                detection_event, steering_message
            )

            assert break_content.content == (
                f"[LOOP BROKEN] Pattern '{real_world_pattern[:50]}...' "
                f"was repeated 6 times. Steering: {steering_message}"
            )
            assert break_content.metadata["loop_detected"] is True
            assert break_content.metadata["repetition_count"] == 6
            assert break_content.metadata["pattern"] == real_world_pattern
            assert break_content.metadata["steering_message"] == steering_message
            assert break_content.metadata["loop_broken"] is True

    @pytest.mark.asyncio
    async def test_retry_request_creation_fallback_behavior(self, mock_services):
        """Test retry request creation when assessment service is not available."""
        # Given
        loop_breaking_service = LoopBreakingService(
            loop_detector=mock_services["loop_detector"],
            assessment_service=None,  # No assessment service
            backend_processor=mock_services["backend_processor"],
        )

        original_request = ChatRequest(
            messages=[ChatMessage(role="user", content="Original request")],
            model="gpt-4o",
        )
        detection_event = LoopDetectionEvent(
            pattern="fallback test pattern",
            pattern_length=20,
            repetition_count=3,
            total_length=25,  # Reasonable total length
            confidence=0.80,  # Lower confidence for fallback
            buffer_content="fallback test pattern",
            timestamp=0.0,  # Fixed timestamp for testing
        )

        # When
        retry_request = await loop_breaking_service.create_retry_request_with_steering(
            original_request, detection_event, "test_fallback"
        )

        # Then
        assert len(retry_request.messages) == 2
        assert retry_request.messages[-1].role == "system"
        assert (
            "previous response was canceled due to a loop detection"
            in retry_request.messages[-1].content
        )
        assert (
            "- Pattern: 'fallback test pattern'" in retry_request.messages[-1].content
        )
