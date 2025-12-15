"""
Behavior specification tests for LLM assessment system.

These tests follow BDD principles to specify the expected behavior of the assessment
system as defined in the PRD and architecture documents. They use Given-When-Then
structure to clearly specify behavior requirements rather than just validating
implementation details.

Key behaviors specified:
1. Assessment triggering based on turn thresholds
2. Confidence threshold steering intervention
3. Dynamic interval adjustment
4. Session state persistence
5. Configuration precedence
"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, Mock, patch

import pytest
from src.core.app.middleware.assessment_middleware import AssessmentMiddleware
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.configuration.assessment_config import AssessmentConfig
from src.core.repositories.assessment_repository import InMemoryAssessmentRepository
from src.core.services.assessment_prompts import initialize_prompts
from src.core.services.assessment_service import AssessmentService
from src.core.services.turn_counter_service import TurnCounterService

# Initialize prompts for all assessment tests
initialize_prompts()


class TestAssessmentTriggeringBehavior:
    """
    Behavior specifications for assessment triggering as defined in PRD section 2.1.

    Given: A conversation session with assessment enabled
    When: The turn threshold is reached
    Then: An assessment should be triggered automatically
    """

    @pytest.mark.asyncio
    async def test_assessment_triggers_at_exact_turn_threshold(self):
        """
        Given: Assessment is enabled with turn threshold of 10
        And: A session has reached 9 turns without assessment
        When: The 10th turn is processed
        Then: Assessment should be triggered exactly once
        """
        # Given
        config = AssessmentConfig(
            enabled=True,
            turn_threshold=10,
            confidence_threshold=0.9,
            history_window=20,
            backend="openai",
            model="gpt-4o-mini",
        )

        repository = InMemoryAssessmentRepository()
        turn_counter = TurnCounterService(repository, config)

        mock_backend = Mock()
        mock_backend.perform_assessment = AsyncMock()
        assessment_service = AssessmentService(mock_backend, config)
        middleware = AssessmentMiddleware(assessment_service, turn_counter, config)

        session_id = "test_session"
        # Create a proper conversation history for assessment
        conversation_messages = [
            ChatMessage(role="user", content="Hello"),
            ChatMessage(role="assistant", content="Hi there! How can I help you?"),
            ChatMessage(role="user", content="I need help with something"),
            ChatMessage(role="assistant", content="I'd be happy to help!"),
            ChatMessage(role="user", content="Can you assist me?"),
            ChatMessage(role="assistant", content="Of course, what do you need?"),
            ChatMessage(role="user", content="Test message"),
        ]
        chat_request = ChatRequest(model="gpt-4", messages=conversation_messages)

        mock_backend.perform_assessment.return_value = {
            "reasoning": "Normal conversation",
            "confidence": 0.3,
        }

        # When - Process exactly 10 turns
        with patch.object(middleware, "_get_session_id", return_value=session_id):
            for _i in range(10):
                await middleware.process(chat_request)

        # Then
        assert mock_backend.perform_assessment.call_count == 1
        assert turn_counter.get_turn_count(session_id) == 10
        assert (
            turn_counter.should_trigger_assessment(session_id) is False
        )  # Should be reset after assessment

    @pytest.mark.asyncio
    async def test_assessment_not_triggered_below_threshold(self):
        """
        Given: Assessment is enabled with turn threshold of 15
        When: A session processes only 14 turns
        Then: No assessment should be triggered
        """
        # Given
        config = AssessmentConfig(
            enabled=True,
            turn_threshold=15,
            confidence_threshold=0.9,
            history_window=20,
            backend="openai",
            model="gpt-4o-mini",
        )

        repository = InMemoryAssessmentRepository()
        turn_counter = TurnCounterService(repository, config)

        mock_backend = Mock()
        mock_backend.perform_assessment = AsyncMock()
        assessment_service = AssessmentService(mock_backend, config)
        middleware = AssessmentMiddleware(assessment_service, turn_counter, config)

        session_id = "test_session"
        chat_request = ChatRequest(
            model="gpt-4", messages=[ChatMessage(role="user", content="Test message")]
        )

        # When - Process 14 turns (below threshold of 15)
        with patch.object(middleware, "_get_session_id", return_value=session_id):
            for _i in range(14):
                await middleware.process(chat_request)

        # Then
        mock_backend.perform_assessment.assert_not_called()
        assert turn_counter.get_turn_count(session_id) == 14

    @pytest.mark.asyncio
    async def test_assessment_disabled_bypasses_triggering(self):
        """
        Given: Assessment is explicitly disabled
        When: Any number of turns are processed
        Then: No assessment should ever be triggered
        """
        # Given
        config = AssessmentConfig(
            enabled=False,  # Explicitly disabled
            turn_threshold=5,
            confidence_threshold=0.9,
            history_window=20,
            backend="openai",
            model="gpt-4o-mini",
        )

        repository = InMemoryAssessmentRepository()
        turn_counter = TurnCounterService(repository, config)

        mock_backend = Mock()
        mock_backend.perform_assessment = AsyncMock()
        assessment_service = AssessmentService(mock_backend, config)
        middleware = AssessmentMiddleware(assessment_service, turn_counter, config)

        session_id = "test_session"
        chat_request = ChatRequest(
            model="gpt-4", messages=[ChatMessage(role="user", content="Test message")]
        )

        # When - Process many turns even though assessment is disabled
        with patch.object(middleware, "_get_session_id", return_value=session_id):
            for _i in range(20):
                await middleware.process(chat_request)

        # Then
        mock_backend.perform_assessment.assert_not_called()
        assert (
            turn_counter.get_turn_count(session_id) == 0
        )  # Turns should not be counted when disabled


class TestConfidenceThresholdBehavior:
    """
    Behavior specifications for confidence threshold steering intervention as defined in PRD section 2.2.

    Given: An assessment has been performed
    When: The confidence score exceeds the threshold
    Then: A steering message should be injected into the conversation
    """

    @pytest.mark.asyncio
    async def test_high_confidence_triggers_steering_intervention(self):
        """
        Given: Assessment confidence threshold is 0.9
        And: An assessment returns confidence of 0.95
        When: The assessment result is processed
        Then: A steering message should be injected into the conversation
        """
        # Given
        config = AssessmentConfig(
            enabled=True,
            turn_threshold=5,
            confidence_threshold=0.9,
            history_window=20,
            backend="openai",
            model="gpt-4o-mini",
        )

        repository = InMemoryAssessmentRepository()
        turn_counter = TurnCounterService(repository, config)

        mock_backend = Mock()
        mock_backend.perform_assessment = AsyncMock()
        assessment_service = AssessmentService(mock_backend, config)
        middleware = AssessmentMiddleware(assessment_service, turn_counter, config)

        session_id = "test_session"
        original_messages = [
            ChatMessage(role="user", content="Hello"),
            ChatMessage(role="assistant", content="Hi there!"),
            ChatMessage(role="user", content="Help me"),
            ChatMessage(role="assistant", content="Sure!"),
            ChatMessage(role="user", content="I'm stuck"),
            ChatMessage(role="assistant", content="I can help with that!"),
        ]

        chat_request = ChatRequest(model="gpt-4", messages=original_messages)

        # Mock high confidence assessment response
        mock_backend.perform_assessment.return_value = {
            "reasoning": "The assistant appears to be stuck in a repetitive help loop without providing specific assistance",
            "confidence": 0.95,
        }

        # When - Process enough turns to trigger assessment
        with patch.object(middleware, "_get_session_id", return_value=session_id):
            result = None
            for _i in range(5):  # Threshold is 5
                result = await middleware.process(chat_request)

        # Then
        assert result is not None
        assert len(result.messages) > len(original_messages)

        # Check steering message properties
        steering_message = result.messages[-1]
        assert steering_message.role == "system"
        assert "SYSTEM NOTICE" in steering_message.content
        assert "loop detected" in steering_message.content.lower()

        # Verify metadata
        assert steering_message.metadata is not None
        assert steering_message.metadata.get("is_assessment_steering") is True
        assert steering_message.metadata.get("confidence") == 0.95
        # Reasoning is in content, not metadata
        assert "repetitive help loop" in steering_message.content

    @pytest.mark.asyncio
    async def test_low_confidence_no_steering_intervention(self):
        """
        Given: Assessment confidence threshold is 0.9
        And: An assessment returns confidence of 0.3
        When: The assessment result is processed
        Then: No steering message should be injected
        """
        # Given
        config = AssessmentConfig(
            enabled=True,
            turn_threshold=5,
            confidence_threshold=0.9,
            history_window=20,
            backend="openai",
            model="gpt-4o-mini",
        )

        repository = InMemoryAssessmentRepository()
        turn_counter = TurnCounterService(repository, config)

        mock_backend = Mock()
        mock_backend.perform_assessment = AsyncMock()
        assessment_service = AssessmentService(mock_backend, config)
        middleware = AssessmentMiddleware(assessment_service, turn_counter, config)

        session_id = "test_session"
        original_messages = [
            ChatMessage(role="user", content="Hello"),
            ChatMessage(role="assistant", content="Hi there!"),
            ChatMessage(role="user", content="Help me"),
            ChatMessage(role="assistant", content="Sure!"),
        ]

        chat_request = ChatRequest(model="gpt-4", messages=original_messages)

        # Mock low confidence assessment response
        mock_backend.perform_assessment.return_value = {
            "reasoning": "Normal conversation flow with productive progression",
            "confidence": 0.3,
        }

        # When - Process enough turns to trigger assessment
        with patch.object(middleware, "_get_session_id", return_value=session_id):
            result = None
            for _i in range(5):  # Threshold is 5
                result = await middleware.process(chat_request)

        # Then
        assert result is not None
        assert len(result.messages) == len(original_messages)  # No steering added

    @pytest.mark.asyncio
    async def test_exact_threshold_confidence_triggers_steering(self):
        """
        Given: Assessment confidence threshold is 0.8
        And: An assessment returns confidence of exactly 0.8
        When: The assessment result is processed
        Then: A steering message should be injected (>= threshold)
        """
        # Given
        config = AssessmentConfig(
            enabled=True,
            turn_threshold=3,
            confidence_threshold=0.9,
            history_window=20,
            backend="openai",
            model="gpt-4o-mini",
        )

        repository = InMemoryAssessmentRepository()
        turn_counter = TurnCounterService(repository, config)

        mock_backend = Mock()
        mock_backend.perform_assessment = AsyncMock()
        assessment_service = AssessmentService(mock_backend, config)
        middleware = AssessmentMiddleware(assessment_service, turn_counter, config)

        session_id = "test_session"
        original_messages = [
            ChatMessage(role="user", content="Hello"),
            ChatMessage(role="assistant", content="Hi there!"),
            ChatMessage(role="user", content="How are you?"),
            ChatMessage(role="assistant", content="I'm doing well!"),
            ChatMessage(role="user", content="That's good to hear"),
            ChatMessage(role="assistant", content="Thank you for asking!"),
        ]

        chat_request = ChatRequest(model="gpt-4", messages=original_messages)

        # Mock exact threshold confidence assessment response
        mock_backend.perform_assessment.return_value = {
            "reasoning": "Borderline case with exactly threshold confidence",
            "confidence": 0.9,  # Exactly at threshold
        }

        # When - Process enough turns to trigger assessment
        with patch.object(middleware, "_get_session_id", return_value=session_id):
            result = None
            for _i in range(3):  # Threshold is 3
                result = await middleware.process(chat_request)

        # Then
        assert result is not None
        assert len(result.messages) > len(original_messages)  # Steering should be added

        steering_message = result.messages[-1]
        assert steering_message.metadata.get("confidence") == 0.9


class TestDynamicIntervalAdjustmentBehavior:
    """
    Behavior specifications for dynamic interval adjustment as defined in ARCHITECTURE.md section 3.2.

    Given: An assessment has been performed with a confidence score
    When: The interval adjustment is applied
    Then: Future assessment intervals should be adjusted based on confidence
    """

    def test_high_confidence_decreases_check_interval(self):
        """
        Given: Current check interval is 10 turns
        And: Assessment returns high confidence (0.9+)
        When: Interval adjustment is applied
        Then: Check interval should decrease for more frequent monitoring
        """
        # Given
        config = AssessmentConfig(
            enabled=True,
            turn_threshold=10,
            confidence_threshold=0.9,
            history_window=20,
            backend="openai",
            model="gpt-4o-mini",
        )

        repository = InMemoryAssessmentRepository()
        turn_counter = TurnCounterService(repository, config)

        session_id = "test_session"

        # Set up initial state with a larger interval
        initial_state = turn_counter.repository.get_session_state(session_id)
        initial_state.current_check_interval = 10  # Start with larger interval
        repository.update_session_state(initial_state)
        initial_interval = initial_state.current_check_interval

        # When - Apply interval adjustment with high confidence
        turn_counter.adjust_check_interval(session_id, 0.95)

        # Then
        adjusted_state = turn_counter.repository.get_session_state(session_id)
        adjusted_interval = adjusted_state.current_check_interval

        assert adjusted_interval < initial_interval
        # Should be decreased but not below minimum
        assert adjusted_interval >= config.min_interval

    def test_low_confidence_increases_check_interval(self):
        """
        Given: Current check interval is 10 turns
        And: Assessment returns low confidence (< 0.5)
        When: Interval adjustment is applied
        Then: Check interval should increase for less frequent monitoring
        """
        # Given
        config = AssessmentConfig(
            enabled=True,
            turn_threshold=10,
            confidence_threshold=0.9,
            history_window=20,
            backend="openai",
            model="gpt-4o-mini",
        )

        repository = InMemoryAssessmentRepository()
        turn_counter = TurnCounterService(repository, config)

        session_id = "test_session"

        # Set up initial state with a smaller interval
        initial_state = turn_counter.repository.get_session_state(session_id)
        initial_state.current_check_interval = 10  # Start with moderate interval
        repository.update_session_state(initial_state)
        initial_interval = initial_state.current_check_interval

        # When - Apply interval adjustment with low confidence
        turn_counter.adjust_check_interval(session_id, 0.2)

        # Then
        adjusted_state = turn_counter.repository.get_session_state(session_id)
        adjusted_interval = adjusted_state.current_check_interval

        assert adjusted_interval > initial_interval
        # Should be increased but not above maximum
        assert adjusted_interval <= config.max_interval

    def test_medium_confidence_maintains_interval(self):
        """
        Given: Current check interval is 10 turns
        And: Assessment returns medium confidence (0.5-0.7)
        When: Interval adjustment is applied
        Then: Check interval should remain approximately the same
        """
        # Given
        config = AssessmentConfig(
            enabled=True,
            turn_threshold=10,
            confidence_threshold=0.9,
            history_window=20,
            backend="openai",
            model="gpt-4o-mini",
        )

        repository = InMemoryAssessmentRepository()
        turn_counter = TurnCounterService(repository, config)

        session_id = "test_session"

        # Set up initial state with a moderate interval
        initial_state = turn_counter.repository.get_session_state(session_id)
        initial_state.current_check_interval = 10  # Start with moderate interval
        repository.update_session_state(initial_state)
        initial_interval = initial_state.current_check_interval

        # When - Apply interval adjustment with medium confidence
        turn_counter.adjust_check_interval(session_id, 0.6)

        # Then
        adjusted_state = turn_counter.repository.get_session_state(session_id)
        adjusted_interval = adjusted_state.current_check_interval

        # Should remain close to original (allowing for minor adjustments)
        assert abs(adjusted_interval - initial_interval) <= 2

    def test_interval_adjustment_respects_bounds(self):
        """
        Given: Configuration defines min and max check intervals
        When: Multiple interval adjustments are applied
        Then: Interval should never exceed configured bounds
        """
        # Given
        config = AssessmentConfig(
            enabled=True,
            turn_threshold=10,
            confidence_threshold=0.9,
            min_interval=3,
            max_interval=50,
            history_window=20,
            backend="openai",
            model="gpt-4o-mini",
        )

        repository = InMemoryAssessmentRepository()
        turn_counter = TurnCounterService(repository, config)

        session_id = "test_session"

        # When - Apply extreme adjustments
        # Try to decrease below minimum with repeated high confidence
        for _ in range(10):
            turn_counter.adjust_check_interval(session_id, 0.95)

        # Then - Should not go below minimum
        state = turn_counter.repository.get_session_state(session_id)
        assert state.current_check_interval >= config.min_interval

        # Try to increase above maximum with repeated low confidence
        for _ in range(10):
            turn_counter.adjust_check_interval(session_id, 0.1)

        # Then - Should not exceed maximum
        state = turn_counter.repository.get_session_state(session_id)
        assert state.current_check_interval <= config.max_interval


class TestSteeringMessageInjectionBehavior:
    """
    Behavior specifications for steering message injection as defined in PRD section 2.3.

    Given: A high confidence assessment has been performed
    When: The assessment result indicates unproductive conversation
    Then: A system steering message should be injected with specific properties
    """

    @pytest.mark.asyncio
    async def test_steering_message_format_and_content(self):
        """
        Given: Assessment confidence 0.95 indicates conversation loop
        When: The middleware processes the assessment result
        Then: A properly formatted steering message should be injected
        """
        # Given
        config = AssessmentConfig(
            enabled=True,
            turn_threshold=3,
            confidence_threshold=0.9,
            history_window=20,
            backend="openai",
            model="gpt-4o-mini",
        )

        repository = InMemoryAssessmentRepository()
        turn_counter = TurnCounterService(repository, config)

        mock_backend = Mock()
        mock_backend.perform_assessment = AsyncMock()
        assessment_service = AssessmentService(mock_backend, config)
        middleware = AssessmentMiddleware(assessment_service, turn_counter, config)

        session_id = "test_session"
        original_messages = [
            ChatMessage(role="user", content="Help me with Python"),
            ChatMessage(role="assistant", content="I can help with Python!"),
            ChatMessage(role="user", content="I'm stuck in a loop"),
            ChatMessage(role="assistant", content="I can help with Python!"),
            ChatMessage(role="user", content="Can you help me debug this?"),
            ChatMessage(role="assistant", content="I can help with Python!"),
        ]

        chat_request = ChatRequest(model="gpt-4", messages=original_messages)

        mock_backend.perform_assessment.return_value = {
            "reasoning": "Assistant is repeating the same response without addressing the user's specific loop problem",
            "confidence": 0.95,
        }

        # When
        with patch.object(middleware, "_get_session_id", return_value=session_id):
            result = None
            for _i in range(3):
                result = await middleware.process(chat_request)

        # Then
        assert result is not None
        assert len(result.messages) == len(original_messages) + 1

        steering_message = result.messages[-1]

        # Check message format
        assert steering_message.role == "system"
        assert isinstance(steering_message.content, str)
        assert len(steering_message.content) > 0

        # Check content contains required elements
        content = steering_message.content.upper()
        assert "SYSTEM NOTICE" in content
        assert "LOOP" in content or "REPETITIVE" in content

        # Check metadata structure
        assert steering_message.metadata is not None
        assert isinstance(steering_message.metadata, dict)

        required_metadata_fields = ["is_assessment_steering", "confidence"]

        for field in required_metadata_fields:
            assert field in steering_message.metadata

        # Check metadata values
        assert steering_message.metadata["is_assessment_steering"] is True
        assert steering_message.metadata["confidence"] == 0.95
        assert steering_message.metadata["session_id"] == session_id
        assert isinstance(steering_message.metadata["timestamp"], int | float)

    @pytest.mark.asyncio
    async def test_steering_message_preserves_conversation_context(self):
        """
        Given: A conversation with multiple messages
        When: A steering message is injected
        Then: Original conversation messages should remain unchanged and in order
        """
        # Given
        config = AssessmentConfig(
            enabled=True,
            turn_threshold=2,
            confidence_threshold=0.9,
            history_window=20,
            backend="openai",
            model="gpt-4o-mini",
        )

        repository = InMemoryAssessmentRepository()
        turn_counter = TurnCounterService(repository, config)

        mock_backend = Mock()
        mock_backend.perform_assessment = AsyncMock()
        assessment_service = AssessmentService(mock_backend, config)
        middleware = AssessmentMiddleware(assessment_service, turn_counter, config)

        session_id = "test_session"
        original_messages = [
            ChatMessage(role="user", content="First question"),
            ChatMessage(role="assistant", content="First answer"),
            ChatMessage(role="user", content="Second question"),
            ChatMessage(role="assistant", content="Second answer"),
            ChatMessage(role="user", content="Third question"),
        ]

        chat_request = ChatRequest(
            model="gpt-4",
            messages=original_messages.copy(),  # Use copy to preserve original
        )

        mock_backend.perform_assessment.return_value = {
            "reasoning": "Conversation shows signs of unproductive repetition",
            "confidence": 0.92,
        }

        # When
        with patch.object(middleware, "_get_session_id", return_value=session_id):
            result = None
            for _i in range(2):
                result = await middleware.process(chat_request)

        # Then
        assert result is not None
        assert len(result.messages) == len(original_messages) + 1

        # Check that original messages are preserved
        for i, original_msg in enumerate(original_messages):
            result_msg = result.messages[i]
            assert result_msg.role == original_msg.role
            assert result_msg.content == original_msg.content

        # Check that steering message is last
        steering_message = result.messages[-1]
        assert steering_message.role == "system"

    @pytest.mark.asyncio
    async def test_multiple_assessments_only_one_steering_per_turn(self):
        """
        Given: A conversation triggers assessment
        When: The assessment results in high confidence
        Then: Only one steering message should be injected per assessment trigger
        """
        # Given
        config = AssessmentConfig(
            enabled=True,
            turn_threshold=1,
            confidence_threshold=0.9,
            history_window=20,
            backend="openai",
            model="gpt-4o-mini",
        )

        repository = InMemoryAssessmentRepository()
        turn_counter = TurnCounterService(repository, config)

        mock_backend = Mock()
        mock_backend.perform_assessment = AsyncMock()
        assessment_service = AssessmentService(mock_backend, config)
        middleware = AssessmentMiddleware(assessment_service, turn_counter, config)

        session_id = "test_session"
        chat_request = ChatRequest(
            model="gpt-4", messages=[ChatMessage(role="user", content="Test")]
        )

        mock_backend.perform_assessment.return_value = {
            "reasoning": "High confidence loop detection",
            "confidence": 0.98,
        }

        # When - Process same request multiple times
        with patch.object(middleware, "_get_session_id", return_value=session_id):
            results = []
            for _i in range(3):
                result = await middleware.process(chat_request)
                results.append(result)

        # Then - Only one steering message per assessment trigger
        for result in results:
            # Each result should have at most one steering message
            steering_count = sum(
                1
                for msg in result.messages
                if msg.metadata and msg.metadata.get("is_assessment_steering")
            )
            assert steering_count <= 1

    @pytest.mark.asyncio
    async def test_steering_message_content_varies_by_assessment_reasoning(self):
        """
        Given: Different assessment reasoning for high confidence results
        When: Multiple steering messages are generated
        Then: Steering message content should reflect the specific assessment reasoning
        """
        # Given
        config = AssessmentConfig(
            enabled=True,
            turn_threshold=2,
            confidence_threshold=0.9,
            history_window=20,
            backend="openai",
            model="gpt-4o-mini",
        )

        repository = InMemoryAssessmentRepository()
        turn_counter = TurnCounterService(repository, config)

        mock_backend = Mock()
        mock_backend.perform_assessment = AsyncMock()
        assessment_service = AssessmentService(mock_backend, config)
        middleware = AssessmentMiddleware(assessment_service, turn_counter, config)

        session_id = "test_session"
        # Create proper conversation history for assessment
        conversation_messages = [
            ChatMessage(role="user", content="Hello"),
            ChatMessage(role="assistant", content="Hi there!"),
            ChatMessage(role="user", content="How are you?"),
            ChatMessage(role="assistant", content="I'm doing well!"),
            ChatMessage(role="user", content="Test"),
            ChatMessage(role="assistant", content="I can help!"),
        ]
        chat_request = ChatRequest(model="gpt-4", messages=conversation_messages)

        # Test different reasoning scenarios
        test_scenarios = [
            {
                "reasoning": "Assistant is stuck in a repetitive greeting loop",
                "confidence": 0.94,
                "expected_keywords": ["greeting", "repetitive", "hello"],
            },
            {
                "reasoning": "Assistant keeps providing the same generic help response",
                "confidence": 0.91,
                "expected_keywords": ["generic", "help", "same"],
            },
            {
                "reasoning": "Assistant is not addressing the user's specific Python error",
                "confidence": 0.96,
                "expected_keywords": ["python", "error", "specific"],
            },
        ]

        for i, scenario in enumerate(test_scenarios):
            # When - Use unique session ID for each scenario to avoid interval conflicts
            scenario_session_id = f"{session_id}_scenario_{i}"
            mock_backend.perform_assessment.return_value = {
                "reasoning": scenario["reasoning"],
                "confidence": scenario["confidence"],
            }

            with patch.object(
                middleware, "_get_session_id", return_value=scenario_session_id
            ):
                result = None
                for _j in range(2):
                    result = await middleware.process(chat_request)

            # Then
            assert result is not None
            steering_message = result.messages[-1]

            # Check that reasoning is preserved in metadata
            assert steering_message.metadata["reasoning"] == scenario["reasoning"]

            # Check that content reflects the reasoning (at least one keyword should appear)
            content_lower = steering_message.content.lower()
            scenario["reasoning"].lower()

            # At least some overlap between content and reasoning
            overlap_found = any(
                keyword in content_lower for keyword in scenario["expected_keywords"]
            )
            assert (
                overlap_found
            ), f"Expected keywords {scenario['expected_keywords']} not found in steering content: {steering_message.content}"


class TestSessionStateBehavior:
    """
    Behavior specifications for session state management as defined in ARCHITECTURE.md section 4.1.

    Given: A conversation session
    When: Assessment activities occur
    Then: Session state should be accurately tracked and persisted
    """

    def test_session_state_creation_and_persistence(self):
        """
        Given: A new session identifier
        When: Session state is first accessed
        Then: A new session state should be created with default values
        """
        # Given
        repository = InMemoryAssessmentRepository()
        AssessmentConfig()
        session_id = "new_test_session"

        # When
        state = repository.get_session_state(session_id)

        # Then
        assert state.session_id == session_id
        assert state.turn_count == 0
        assert (
            state.current_check_interval == 3
        )  # Default value from SessionAssessmentState
        assert state.disabled_for_session is False
        assert state.last_check_turn == 0
        assert len(state.assessment_history) == 0
        assert isinstance(state.last_updated, int | float)
        assert state.last_updated > 0

    def test_turn_count_increment_behavior(self):
        """
        Given: A session with existing turn count
        When: A turn is incremented
        Then: Turn count should increase by exactly one and timestamp should update
        """
        # Given
        repository = InMemoryAssessmentRepository()
        config = AssessmentConfig()
        turn_counter = TurnCounterService(repository, config)
        session_id = "test_session"

        # Initialize session with some turns
        initial_state = repository.get_session_state(session_id)
        initial_state.turn_count = 5
        initial_timestamp = initial_state.last_updated
        repository.update_session_state(initial_state)

        # When
        new_count = turn_counter.increment_turn(session_id)

        # Then
        assert new_count == 6
        updated_state = repository.get_session_state(session_id)
        assert updated_state.turn_count == 6
        assert updated_state.last_updated > initial_timestamp

    def test_session_state_isolation(self):
        """
        Given: Multiple conversation sessions
        When: Activities occur in different sessions
        Then: Each session's state should remain isolated from others
        """
        # Given
        repository = InMemoryAssessmentRepository()
        config = AssessmentConfig()
        turn_counter = TurnCounterService(repository, config)

        session1 = "session_1"
        session2 = "session_2"
        session3 = "session_3"

        # When - Perform different activities in each session
        # Session 1: Multiple turns
        for _i in range(5):
            turn_counter.increment_turn(session1)

        # Session 2: Single turn and interval adjustment
        turn_counter.increment_turn(session2)
        turn_counter.adjust_check_interval(session2, 0.8)

        # Session 3: No activity

        # Then - Each session should have independent state
        state1 = repository.get_session_state(session1)
        state2 = repository.get_session_state(session2)
        state3 = repository.get_session_state(session3)

        assert state1.turn_count == 5
        assert len(state1.assessment_history) == 0
        assert state1.current_check_interval == 3  # Default value

        assert state2.turn_count == 1
        assert len(state2.assessment_history) == 0
        assert state2.current_check_interval != 3  # Should be adjusted

        assert state3.turn_count == 0
        assert len(state3.assessment_history) == 0
        assert state3.current_check_interval == 3  # Default value

    def test_assessment_tracking_state_updates(self):
        """
        Given: A session that triggers assessment
        When: Assessment is performed
        Then: Assessment tracking fields should be updated appropriately
        """
        # Given
        repository = InMemoryAssessmentRepository()
        config = AssessmentConfig()
        turn_counter = TurnCounterService(repository, config)
        session_id = "test_session"

        # Initialize with some turns
        for _i in range(10):
            turn_counter.increment_turn(session_id)

        initial_state = repository.get_session_state(session_id)
        initial_turn_count = initial_state.turn_count
        initial_assessment_count = len(initial_state.assessment_history)
        initial_last_updated = initial_state.last_updated

        # When - Mark assessment as performed
        import time

        time.sleep(0.001)  # Small delay to ensure different timestamps
        turn_counter.mark_assessment_performed(session_id)

        # Then - Assessment tracking should be updated
        updated_state = repository.get_session_state(session_id)

        assert (
            updated_state.turn_count == initial_turn_count
        )  # Turn count shouldn't change
        assert updated_state.len() == initial_assessment_count + 1
        assert updated_state.last_check_turn == initial_turn_count
        assert updated_state.last_updated > initial_last_updated

    def test_session_enable_disable_behavior(self):
        """
        Given: A session with assessment enabled
        When: Assessment is disabled or enabled for the session
        Then: Session state should reflect the enabled/disabled status
        """
        # Given
        repository = InMemoryAssessmentRepository()
        config = AssessmentConfig()
        turn_counter = TurnCounterService(repository, config)
        session_id = "test_session"

        # Initial state should be enabled
        initial_state = repository.get_session_state(session_id)
        assert initial_state.disabled_for_session is False

        # When - Disable assessment for session
        turn_counter.disable_for_session(session_id)

        # Then - Session should be disabled
        disabled_state = repository.get_session_state(session_id)
        assert disabled_state.disabled_for_session is True
        assert turn_counter.should_trigger_assessment(session_id) is False

        # When - Re-enable assessment for session
        turn_counter.enable_for_session(session_id)

        # Then - Session should be enabled again
        enabled_state = repository.get_session_state(session_id)
        assert enabled_state.disabled_for_session is False

    def test_session_state_cleanup_behavior(self):
        """
        Given: Multiple sessions with varying ages
        When: Session cleanup is performed
        Then: Only expired sessions should be removed
        """
        # Given
        repository = InMemoryAssessmentRepository()
        AssessmentConfig()

        # Create sessions with different ages
        recent_session = "recent_session"
        old_session = "old_session"
        very_old_session = "very_old_session"

        # Create recent session (current time)
        repository.get_session_state(recent_session)

        # Create old session (1 hour ago)
        old_state = repository.get_session_state(old_session)
        old_state.last_updated = (datetime.now() - timedelta(hours=1)).timestamp()
        repository.update_session_state(old_state, update_timestamp=False)

        # Create very old session (2 hours ago)
        very_old_state = repository.get_session_state(very_old_session)
        very_old_state.last_updated = (datetime.now() - timedelta(hours=2)).timestamp()
        repository.update_session_state(very_old_state, update_timestamp=False)

        # Verify all sessions exist initially
        all_sessions = repository.get_all_session_ids()
        assert recent_session in all_sessions
        assert old_session in all_sessions
        assert very_old_session in all_sessions
        assert len(all_sessions) == 3

        # When - Clean up sessions older than 90 minutes
        repository.cleanup_expired_sessions(
            max_age_seconds=2700
        )  # 45 minutes = 2700 seconds

        # Then - Only recent session should remain
        remaining_sessions = repository.get_all_session_ids()
        assert recent_session in remaining_sessions
        assert old_session not in remaining_sessions
        assert very_old_session not in remaining_sessions
        assert len(remaining_sessions) == 1

    def test_concurrent_session_state_access(self):
        """
        Given: Multiple rapid state updates to the same session
        When: State operations are performed concurrently
        Then: All operations should complete successfully with consistent state
        """
        # Given
        repository = InMemoryAssessmentRepository()
        config = AssessmentConfig()
        turn_counter = TurnCounterService(repository, config)
        session_id = "concurrent_session"

        # When - Perform rapid consecutive operations
        operations = []
        for i in range(100):
            operations.append(("increment", turn_counter.increment_turn(session_id)))
            if i % 10 == 0:
                operations.append(
                    (
                        "adjust",
                        turn_counter.adjust_check_interval(
                            session_id, 0.5 + (i % 3) * 0.2
                        ),
                    )
                )

        # Then - Final state should be consistent
        final_state = repository.get_session_state(session_id)

        # Should have 100 increments
        assert final_state.turn_count == 100

        # Should have some interval adjustments (at least one)
        assert final_state.current_check_interval != 3  # Default value

        # Should have consistent timestamps
        assert final_state.last_updated > 0

        # Assessment count should still be 0 (no assessments were marked)
        assert len(final_state.assessment_history) == 0
