"""
Unit tests for the LoopBreakingService.

Tests the complete loop breaking functionality including:
- API cancellation triggering
- Steering message generation
- Retry request creation
- Integration with loop detection
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.configuration.assessment_config import AssessmentConfig
from src.core.ports.streaming_contracts import StreamingContent
from src.core.services.assessment_prompts import initialize_prompts
from src.core.services.loop_breaking_service import LoopBreakingService
from src.loop_detection.event import LoopDetectionEvent

from tests.utils.fake_clock import FakeClock, FakeClockContext


class MockLoopDetector:
    """Mock loop detector for testing."""

    def __init__(
        self,
        should_detect_loop: bool = False,
        mock_event: LoopDetectionEvent | None = None,
    ):
        self.should_detect_loop = should_detect_loop
        self.mock_event = mock_event
        self.reset_calls = 0
        self.process_chunk_calls: list[str] = []

    def reset(self) -> None:
        """Track reset calls."""
        self.reset_calls += 1

    def process_chunk(self, content: str) -> LoopDetectionEvent | None:
        """Mock process_chunk method."""
        # Track calls for verification
        self.process_chunk_calls.append(content)

        if self.should_detect_loop:
            # Use fixed timestamp - tests will control time via FakeClockContext
            return self.mock_event or LoopDetectionEvent(
                pattern="I am now complete. I am now finished. I will now exit.",
                repetition_count=5,
                pattern_length=50,
                total_length=250,
                confidence=1.0,
                buffer_content="I am now complete. I am now finished.",
                timestamp=1000.0,
            )

        # If mock_event is explicitly set, return it even if should_detect_loop is False
        if self.mock_event is not None:
            return self.mock_event

        return None


class MockAssessmentService:
    """Mock assessment service for testing."""

    def __init__(self, confidence: float = 0.95, should_fail: bool = False):
        self.confidence = confidence
        self.should_fail = should_fail
        self.assess_calls: list[tuple[Any, str]] = []

    async def assess_conversation(self, history, session_id: str):
        """Mock assess_conversation method."""
        self.assess_calls.append((history, session_id))

        if self.should_fail:
            raise Exception("Assessment service failed")

        from src.core.domain.assessment import AssessmentResult

        return AssessmentResult(
            session_id=session_id,
            reasoning="repetitive content pattern detected",
            confidence=self.confidence,
            turn_count=len(history),
        )

    async def assess_conversation_safe(self, history, session_id: str):
        """Mock assess_conversation_safe method."""
        try:
            return await self.assess_conversation(history, session_id)
        except Exception:
            return None


class MockBackendProcessor:
    """Mock backend processor for testing."""

    def __init__(self, should_fail_retry: bool = False, retry_response=None):
        self.should_fail_retry = should_fail_retry
        self.retry_response = retry_response
        self.process_calls: list[tuple[ChatRequest, str, dict | None]] = []

    async def process_backend_request(
        self, request: ChatRequest, session_id: str, context: dict | None = None
    ):
        """Mock process_backend_request method."""
        self.process_calls.append((request, session_id, context))

        if self.should_fail_retry:
            from src.core.domain.responses import ResponseEnvelope

            return ResponseEnvelope(
                content="LOOP BREAKING FAILED",
                metadata={"loop_broken": True, "retry_failed": True},
            )

        if self.retry_response:
            return self.retry_response

        # Return a successful response
        from src.core.domain.responses import ResponseEnvelope

        return ResponseEnvelope(
            content="Retry successful response",
            metadata={
                "retry_initiated": True,
                "session_id": session_id,
                "loop_broken": True,
            },
        )


class TestLoopBreakingService:
    """Test cases for LoopBreakingService."""

    @pytest.fixture
    def loop_detector(self):
        """Create a mock loop detector."""
        return MockLoopDetector()

    @pytest.fixture
    def assessment_service(self):
        """Create a mock assessment service."""
        return MockAssessmentService()

    @pytest.fixture
    def backend_processor(self):
        """Create a mock backend processor."""
        return MockBackendProcessor()

    @pytest.fixture
    def assessment_config(self):
        """Create a mock assessment config."""
        # Initialize prompts for assessment system
        initialize_prompts()
        return AssessmentConfig(
            turn_threshold=30,
            confidence_threshold=0.9,
            history_window=20,
        )

    @pytest.fixture
    def loop_breaking_service(
        self, loop_detector, assessment_service, backend_processor, assessment_config
    ):
        """Create a loop breaking service."""
        return LoopBreakingService(
            loop_detector=loop_detector,
            assessment_service=assessment_service,
            backend_processor=backend_processor,
            assessment_config=assessment_config,
        )

    @pytest.fixture
    def loop_breaking_service_no_backend(
        self, loop_detector, assessment_service, assessment_config
    ):
        """Create a loop breaking service without backend processor."""
        return LoopBreakingService(
            loop_detector=loop_detector,
            assessment_service=assessment_service,
            backend_processor=None,
            assessment_config=assessment_config,
        )

    @pytest.mark.asyncio
    async def test_process_streaming_content_no_loop_detection(
        self, loop_breaking_service, loop_detector
    ):
        """Test processing content without loop detection."""
        # Given
        content = StreamingContent(content="This is normal content.", is_done=False)
        cancel_callback = AsyncMock()

        # When
        result_content, should_break = (
            await loop_breaking_service.process_streaming_content(
                content, "test_session_123", cancel_callback
            )
        )

        # Then
        assert should_break is False
        assert result_content.content == content.content
        assert result_content.is_done == content.is_done
        assert cancel_callback.call_count == 0

    @pytest.mark.asyncio
    async def test_process_streaming_content_with_loop_detection(
        self, loop_breaking_service, loop_detector
    ):
        """Test processing content with loop detection."""
        async with FakeClockContext(FakeClock(initial_time=1000.0)) as clock:
            # Given
            loop_detector.should_detect_loop = True
            loop_detector.mock_event = LoopDetectionEvent(
                pattern="I am now complete. I am now finished.",
                repetition_count=4,
                pattern_length=30,
                total_length=120,
                confidence=1.0,
                buffer_content="I am now complete.",
                timestamp=clock.now(),
            )
            content = StreamingContent(
                content="I am now complete. I am now finished. I will now exit."
            )
            cancel_callback = AsyncMock()

            # When
            result_content, should_break = (
                await loop_breaking_service.process_streaming_content(
                    content, "test_session_456", cancel_callback
                )
            )

            # Then
            assert should_break is True
            assert result_content.is_cancellation is True
            assert "[LOOP BROKEN]" in result_content.content
            assert (
                "Pattern 'I am now complete. I am now finished....' was repeated 4 times"
                in result_content.content
            )
            assert cancel_callback.call_count == 1
            assert cancel_callback.call_args_list == [()]

    @pytest.mark.asyncio
    async def test_generate_steering_message_with_assessment_service(
        self,
        loop_breaking_service,
        loop_detector,
        assessment_service,
        assessment_config,
    ):
        """Test steering message generation with assessment service."""
        async with FakeClockContext(FakeClock(initial_time=1000.0)) as clock:
            # Given
            loop_detector.mock_event = LoopDetectionEvent(
                pattern="repetitive pattern",
                repetition_count=6,
                pattern_length=20,
                total_length=120,
                confidence=1.0,
                buffer_content="repetitive",
                timestamp=clock.now(),
            )
            assessment_service.confidence = 0.92  # Above threshold

            # When
            detection_event = loop_detector.mock_event
            steering_message = await loop_breaking_service._generate_steering_message(
                detection_event, "test_session_789"
            )

            # Then
            assert "repeating" in steering_message.lower()
            assert "different" in steering_message.lower()
            # The assessment service should be called with loop detection history
            assert len(assessment_service.assess_calls) == 1
            assert assessment_service.assess_calls[0][1] == "test_session_789"
            # The history should contain the loop detection message
            history = assessment_service.assess_calls[0][0]
            assert len(history) == 1
            assert "repetitive pattern" in history[0].content
            assert "repeated 6 times" in history[0].content

    @pytest.mark.asyncio
    async def test_generate_steering_message_below_threshold(
        self,
        loop_breaking_service,
        loop_detector,
        assessment_service,
        assessment_config,
    ):
        """Test steering message when assessment confidence is below threshold."""
        async with FakeClockContext(FakeClock(initial_time=1000.0)) as clock:
            # Given
            assessment_service.confidence = 0.85  # Below threshold of 0.9
            detection_event = LoopDetectionEvent(
                pattern="low confidence pattern",
                repetition_count=3,
                pattern_length=25,
                total_length=75,
                confidence=1.0,
                buffer_content="low confidence",
                timestamp=clock.now(),
            )

            # When
            steering_message = await loop_breaking_service._generate_steering_message(
                detection_event, "test_session_012"
            )

            # Then
            assert "getting stuck" in steering_message.lower()
            # The assessment service should be called with loop detection history
            assert len(assessment_service.assess_calls) == 1
            assert assessment_service.assess_calls[0][1] == "test_session_012"
            # The history should contain the loop detection message
            history = assessment_service.assess_calls[0][0]
            assert len(history) == 1
            assert "low confidence pattern" in history[0].content
            assert "repeated 3 times" in history[0].content

    @pytest.mark.asyncio
    async def test_generate_steering_message_without_assessment_service(
        self, loop_breaking_service, loop_detector
    ):
        """Test steering message generation without assessment service."""
        async with FakeClockContext(FakeClock(initial_time=1000.0)) as clock:
            # Given
            detection_event = LoopDetectionEvent(
                pattern="fallback pattern",
                repetition_count=5,
                pattern_length=15,
                total_length=75,
                confidence=1.0,
                buffer_content="fallback",
                timestamp=clock.now(),
            )

            # When
            steering_message = await loop_breaking_service._generate_steering_message(
                detection_event, "test_session_345"
            )

            # Then
            assert "repetitive content pattern detected" in steering_message.lower()
            assert "different" in steering_message.lower()
            # The assessment service should not be called when it's not provided

    @pytest.mark.asyncio
    async def test_create_retry_request_with_steering(
        self,
        loop_breaking_service,
        loop_detector,
        assessment_service,
        assessment_config,
    ):
        """Test creating retry request with steering message."""
        async with FakeClockContext(FakeClock(initial_time=1000.0)) as clock:
            # Given
            original_request = ChatRequest(
                model="gpt-4o",
                messages=[ChatMessage(role="user", content="Original request")],
                temperature=0.0,
                max_tokens=1024,
                top_p=1.0,
            )
            loop_detector.mock_event = LoopDetectionEvent(
                pattern="test pattern",
                repetition_count=4,
                pattern_length=12,
                total_length=48,
                confidence=1.0,
                buffer_content="test",
                timestamp=clock.now(),
            )
            assessment_service.confidence = 0.93

            # When
            retry_request = (
                await loop_breaking_service.create_retry_request_with_steering(
                    original_request, loop_detector.mock_event, "test_session_678"
                )
            )

            # Then
            assert len(retry_request.messages) == len(original_request.messages) + 1
            assert retry_request.messages[-1].role == "system"
            assert (
                "previous response was canceled due to a loop detection"
                in retry_request.messages[-1].content
            )
            assert "- Pattern: 'test pattern'" in retry_request.messages[-1].content
            assert "- Repetitions: 4" in retry_request.messages[-1].content
            assert "Steering Guidance:" in retry_request.messages[-1].content
            # The assessment service should be called with loop detection history
            assert len(assessment_service.assess_calls) == 1
            assert assessment_service.assess_calls[0][1] == "test_session_678"
            # The history should contain the loop detection message
            history = assessment_service.assess_calls[0][0]
            assert len(history) == 1
            assert "test pattern" in history[0].content
            assert "repeated 4 times" in history[0].content

    @pytest.mark.asyncio
    async def test_process_loop_breaking_retry_success(
        self,
        loop_breaking_service,
        loop_detector,
        assessment_service,
        backend_processor,
        assessment_config,
    ):
        """Test successful loop breaking retry flow."""
        async with FakeClockContext(FakeClock(initial_time=1000.0)) as clock:
            # Given
            loop_detector.mock_event = LoopDetectionEvent(
                pattern="successful test pattern",
                repetition_count=5,
                pattern_length=22,
                total_length=110,
                confidence=1.0,
                buffer_content="successful test",
                timestamp=clock.now(),
            )
            assessment_service.confidence = 0.94
            original_request = ChatRequest(
                model="gpt-4o",
                messages=[ChatMessage(role="user", content="Test for loop breaking")],
            )

            # When
            result = await loop_breaking_service.process_loop_breaking_retry(
                original_request, loop_detector.mock_event, "test_session_999"
            )

            # Then
            assert hasattr(result, "content")
            assert result.metadata.get("loop_broken") is True
            assert result.metadata.get("retry_initiated") is True
            assert result.metadata.get("session_id") == "test_session_999"
            assert len(backend_processor.process_calls) == 1
            call_request, call_session_id, call_context = (
                backend_processor.process_calls[0]
            )
            assert call_session_id == "test_session_999"
            assert call_context in ({}, None)
            # Check that the request has the expected structure
            assert len(call_request.messages) == len(original_request.messages) + 1
            assert call_request.messages[-1].role == "system"

    @pytest.mark.asyncio
    async def test_process_loop_breaking_retry_backend_failure(
        self,
        loop_breaking_service,
        loop_detector,
        assessment_service,
        backend_processor,
    ):
        """Test loop breaking retry when backend fails."""
        async with FakeClockContext(FakeClock(initial_time=1000.0)) as clock:
            # Given
            loop_detector.mock_event = LoopDetectionEvent(
                pattern="backend failure test",
                repetition_count=3,
                pattern_length=20,
                total_length=60,
                confidence=1.0,
                buffer_content="backend failure",
                timestamp=clock.now(),
            )
            backend_processor.should_fail_retry = True
            original_request = ChatRequest(
                model="gpt-4o",
                messages=[ChatMessage(role="user", content="Test backend failure")],
            )

            # When/Then
            result = await loop_breaking_service.process_loop_breaking_retry(
                original_request, loop_detector.mock_event, "test_session_failure"
            )

            # Then
            assert result.metadata.get("loop_broken") is True
            assert result.metadata.get("retry_failed") is True
            assert "LOOP BREAKING FAILED" in result.content
            assert len(backend_processor.process_calls) == 1
            call_request, call_session_id, call_context = (
                backend_processor.process_calls[0]
            )
            assert call_session_id == "test_session_failure"
            assert call_context in ({}, None)

    @pytest.mark.asyncio
    async def test_process_loop_breaking_retry_no_backend_processor(
        self,
        loop_breaking_service_no_backend,
        loop_detector,
        assessment_service,
        assessment_config,
    ):
        """Test loop breaking retry without backend processor."""
        async with FakeClockContext(FakeClock(initial_time=1000.0)) as clock:
            # Given
            loop_detector.mock_event = LoopDetectionEvent(
                pattern="no backend test",
                repetition_count=2,
                pattern_length=15,
                total_length=30,
                confidence=1.0,
                buffer_content="no backend",
                timestamp=clock.now(),
            )
            original_request = ChatRequest(
                model="gpt-4o",
                messages=[ChatMessage(role="user", content="Test no backend")],
            )

            # When/Then
            with pytest.raises(
                RuntimeError,
                match="Cannot retry request without backend processor configured",
            ):
                await loop_breaking_service_no_backend.process_loop_breaking_retry(
                    original_request,
                    loop_detector.mock_event,
                    "test_session_no_backend",
                )

    @pytest.mark.asyncio
    async def test_integration_with_real_world_scenario(
        self,
        loop_breaking_service,
        loop_detector,
        assessment_service,
        backend_processor,
        assessment_config,
    ):
        """Test complete integration with real-world loop scenario."""
        async with FakeClockContext(FakeClock(initial_time=1000.0)) as clock:
            # Given - Real-world loop scenario from wire capture
            real_world_pattern = "I am now complete. I am now finished. I will now exit. I am now done. I will now stop."
            loop_detector.mock_event = LoopDetectionEvent(
                pattern=real_world_pattern,
                repetition_count=8,  # High repetition count as seen in logs
                pattern_length=len(real_world_pattern),
                total_length=len(real_world_pattern) * 8,
                confidence=1.0,
                buffer_content=real_world_pattern[:50],
                timestamp=clock.now(),
            )
            assessment_service.confidence = 0.96
            cancel_callback = AsyncMock()

            # When
            break_content, should_break = (
                await loop_breaking_service.process_streaming_content(
                    StreamingContent(
                        content=real_world_pattern * 3
                    ),  # Simulate streaming chunks
                    "real_world_session_123",
                    cancel_callback,
                )
            )

            # Then
            assert should_break is True
            assert break_content.is_cancellation is True
            assert break_content.metadata.get("loop_broken") is True
            assert break_content.metadata.get("repetition_count") == 8
            assert cancel_callback.call_count == 1
