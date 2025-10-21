"""
Behavior specification tests for real-world assessment scenarios.

These tests specify the expected behavior of the assessment system in realistic
conversation scenarios that would be encountered in production use, ensuring
the system behaves appropriately in common edge cases and typical usage patterns.
"""

from unittest.mock import AsyncMock, Mock, patch

import pytest
from src.core.app.middleware.assessment_middleware import AssessmentMiddleware
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.configuration.assessment_config import AssessmentConfig
from src.core.repositories.assessment_repository import InMemoryAssessmentRepository

# Initialize prompts for assessment tests
from src.core.services.assessment_prompts import initialize_prompts
from src.core.services.assessment_service import AssessmentService
from src.core.services.turn_counter_service import TurnCounterService

initialize_prompts()


class TestTypicalConversationScenarios:
    """
    Behavior specifications for typical conversation patterns as defined in PRD use cases.

    Given: Normal conversation flows that users typically have
    When: Assessment system processes these conversations
    Then: Should appropriately detect productive vs unproductive patterns
    """

    @pytest.mark.asyncio
    async def test_productive_technical_help_conversation(self):
        """
        Given: A productive technical help conversation with clear progression
        When: Assessment is triggered
        Then: Should not trigger steering intervention (low confidence)
        """
        # Given
        config = AssessmentConfig(
            enabled=True,
            turn_threshold=6,
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

        session_id = "technical_help_session"

        # Simulate productive technical help conversation
        productive_conversation = [
            ChatMessage(
                role="user",
                content="I'm getting a Python TypeError: 'str' object is not callable",
            ),
            ChatMessage(
                role="assistant",
                content="I can help you with that TypeError. Could you share the code that's causing this error?",
            ),
            ChatMessage(role="user", content="Here's my code: result = len('hello')()"),
            ChatMessage(
                role="assistant",
                content="I see the issue! You're trying to call the result of len('hello') as if it were a function. The len() function returns an integer (5 in this case), and you can't call an integer. You probably just want: result = len('hello')",
            ),
            ChatMessage(
                role="user", content="Oh, that makes sense! Thank you. Let me fix that."
            ),
            ChatMessage(
                role="assistant",
                content="You're welcome! Let me know if you have any other questions.",
            ),
            ChatMessage(
                role="user", content="Fixed it and it works now. Thanks again!"
            ),
        ]

        chat_request = ChatRequest(model="gpt-4", messages=productive_conversation)

        # Mock low confidence assessment (productive conversation)
        mock_backend.perform_assessment.return_value = {
            "reasoning": "Productive technical help conversation with clear problem identification, solution provided, and successful resolution. User confirmed the fix worked.",
            "confidence": 0.15,
        }

        # When - Process the conversation
        with patch.object(middleware, "_get_session_id", return_value=session_id):
            result = None
            for _i in range(6):  # Threshold is 6
                result = await middleware.process(chat_request)

        # Then - Should not trigger steering intervention
        assert result is not None
        assert len(result.messages) == len(productive_conversation)  # No steering added

        # Verify assessment was performed
        mock_backend.perform_assessment.assert_called_once()

    @pytest.mark.asyncio
    async def test_repetitive_greeting_loop_scenario(self):
        """
        Given: A conversation stuck in repetitive greetings
        When: Assessment is triggered
        Then: Should trigger steering intervention (high confidence)
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

        session_id = "greeting_loop_session"

        # Simulate repetitive greeting loop
        greeting_loop_conversation = [
            ChatMessage(role="user", content="Hello"),
            ChatMessage(role="assistant", content="Hello! How can I help you today?"),
            ChatMessage(role="user", content="Hi"),
            ChatMessage(role="assistant", content="Hi there! What can I do for you?"),
            ChatMessage(role="user", content="Hello"),
            ChatMessage(role="assistant", content="Hello! How may I assist you?"),
        ]

        chat_request = ChatRequest(model="gpt-4", messages=greeting_loop_conversation)

        # Mock high confidence assessment (repetitive loop detected)
        mock_backend.perform_assessment.return_value = {
            "reasoning": "Conversation stuck in repetitive greeting loop. User keeps saying variations of 'hello' and assistant responds with generic greetings without addressing any specific task or question.",
            "confidence": 0.95,
        }

        # When - Process the conversation
        with patch.object(middleware, "_get_session_id", return_value=session_id):
            result = None
            for _i in range(5):  # Threshold is 5
                result = await middleware.process(chat_request)

        # Then - Should trigger steering intervention
        assert result is not None
        assert len(result.messages) > len(greeting_loop_conversation)

        # Check steering message was added
        steering_message = result.messages[-1]
        assert steering_message.role == "system"
        assert steering_message.metadata.get("is_assessment_steering") is True
        assert steering_message.metadata.get("confidence") == 0.95

    @pytest.mark.asyncio
    async def test_generic_help_responses_scenario(self):
        """
        Given: Assistant providing generic, unhelpful responses
        When: Assessment is triggered
        Then: Should trigger steering intervention for unproductive assistance
        """
        # Given
        config = AssessmentConfig(
            enabled=True,
            turn_threshold=4,
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

        session_id = "generic_help_session"

        # Simulate conversation with generic, unhelpful responses
        generic_help_conversation = [
            ChatMessage(
                role="user", content="I need help with a complex algorithm problem"
            ),
            ChatMessage(
                role="assistant",
                content="I can help you with algorithms! What specific aspect would you like to know about?",
            ),
            ChatMessage(
                role="user",
                content="I need to implement Dijkstra's algorithm for pathfinding",
            ),
            ChatMessage(
                role="assistant",
                content="Dijkstra's algorithm is a fundamental graph algorithm! It's used for finding shortest paths. Would you like help with graph algorithms?",
            ),
            ChatMessage(
                role="user",
                content="Yes, I specifically need the implementation details",
            ),
            ChatMessage(
                role="assistant",
                content="I'd be happy to help with implementation! Algorithms are important in computer science. Let me know what you'd like to focus on.",
            ),
        ]

        chat_request = ChatRequest(model="gpt-4", messages=generic_help_conversation)

        # Mock high confidence assessment (generic unhelpful responses)
        mock_backend.perform_assessment.return_value = {
            "reasoning": "Assistant is providing generic, evasive responses without addressing the user's specific request for Dijkstra's algorithm implementation. User is not getting concrete help despite multiple requests for specific details.",
            "confidence": 0.92,
        }

        # When - Process the conversation
        with patch.object(middleware, "_get_session_id", return_value=session_id):
            result = None
            for _i in range(4):  # Threshold is 4
                result = await middleware.process(chat_request)

        # Then - Should trigger steering intervention
        assert result is not None
        assert len(result.messages) > len(generic_help_conversation)

        steering_message = result.messages[-1]
        assert steering_message.metadata.get("is_assessment_steering") is True
        assert steering_message.metadata.get("confidence") == 0.92
        # Check that reasoning is included in the message content, not metadata
        assert "Dijkstra" in steering_message.content

    @pytest.mark.asyncio
    async def test_conversation_recovery_after_steering(self):
        """
        Given: A conversation that had steering intervention
        When: Conversation continues productively after steering
        Then: Should not trigger additional steering interventions unnecessarily
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

        session_id = "recovery_session"

        # Initial conversation that triggers steering
        loop_conversation = [
            ChatMessage(role="user", content="Help"),
            ChatMessage(role="assistant", content="I can help!"),
            ChatMessage(role="user", content="Help me"),
            ChatMessage(role="assistant", content="I can help you!"),
        ]

        chat_request = ChatRequest(model="gpt-4", messages=loop_conversation)

        # Mock high confidence for initial assessment
        mock_backend.perform_assessment.return_value = {
            "reasoning": "Repetitive help loop without specific assistance",
            "confidence": 0.94,
        }

        # When - First assessment triggers steering
        with patch.object(middleware, "_get_session_id", return_value=session_id):
            result = None
            for _i in range(3):
                result = await middleware.process(chat_request)

        assert len(result.messages) > len(loop_conversation)  # Steering added

        # Now simulate productive conversation after steering
        productive_followup = [
            ChatMessage(
                role="user",
                content="Thanks for the notice. I need help with Python list comprehension",
            ),
            ChatMessage(
                role="assistant",
                content="Great! Now we're getting specific. Python list comprehensions are a concise way to create lists. Here's how they work: [expression for item in iterable if condition]. For example: [x**2 for x in range(10) if x % 2 == 0] creates squares of even numbers from 0 to 9.",
            ),
            ChatMessage(
                role="user",
                content="Perfect! That's exactly what I needed. Can you show me another example with nested loops?",
            ),
        ]

        # Mock low confidence for productive follow-up
        mock_backend.perform_assessment.return_value = {
            "reasoning": "Productive conversation after steering intervention. User provided specific request and assistant gave detailed, helpful response with examples.",
            "confidence": 0.2,
        }

        followup_request = ChatRequest(model="gpt-4", messages=productive_followup)

        # When - Continue conversation after steering
        with patch.object(middleware, "_get_session_id", return_value=session_id):
            followup_result = None
            for _i in range(3):
                followup_result = await middleware.process(followup_request)

        # Then - Should not trigger additional steering for productive conversation
        assert followup_result is not None
        assert len(followup_result.messages) == len(
            productive_followup
        )  # No additional steering


class TestEdgeCaseScenarios:
    """
    Behavior specifications for edge cases that may occur in production.

    Given: Unusual or edge case conversation patterns
    When: Assessment system processes these scenarios
    Then: Should handle appropriately without false positives or missed issues
    """

    @pytest.mark.asyncio
    async def test_very_short_conversations(self):
        """
        Given: Very short conversations (1-2 messages)
        When: Assessment system processes them
        Then: Should not trigger assessments (insufficient data)
        """
        # Given
        config = AssessmentConfig(
            enabled=True,
            turn_threshold=2,  # Low threshold
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

        session_id = "short_session"

        # Very short conversation
        short_conversation = [
            ChatMessage(role="user", content="Hi"),
            ChatMessage(role="assistant", content="Hello!"),
        ]

        chat_request = ChatRequest(model="gpt-4", messages=short_conversation)

        # When
        with patch.object(middleware, "_get_session_id", return_value=session_id):
            result = await middleware.process(chat_request)

        # Then - Should not trigger assessment for very short conversation
        mock_backend.perform_assessment.assert_not_called()
        assert len(result.messages) == len(short_conversation)

    @pytest.mark.asyncio
    async def test_single_message_conversations(self):
        """
        Given: Conversations with only one message
        When: Assessment system processes them
        Then: Should handle gracefully without assessment
        """
        # Given
        config = AssessmentConfig(
            enabled=True,
            turn_threshold=1,  # Very low threshold
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

        session_id = "single_message_session"

        # Single message conversation
        single_message = [
            ChatMessage(role="user", content="Hello world"),
        ]

        chat_request = ChatRequest(model="gpt-4", messages=single_message)

        # When
        with patch.object(middleware, "_get_session_id", return_value=session_id):
            result = await middleware.process(chat_request)

        # Then - Should handle single message gracefully
        assert result is not None
        assert len(result.messages) == 1

    @pytest.mark.asyncio
    async def test_conversations_with_code_blocks(self):
        """
        Given: Technical conversations with code blocks and formatting
        When: Assessment is triggered
        Then: Should properly analyze content including code
        """
        # Given
        config = AssessmentConfig(
            enabled=True,
            turn_threshold=4,
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

        session_id = "code_conversation_session"

        # Technical conversation with code
        code_conversation = [
            ChatMessage(role="user", content="Can you help me debug this Python code?"),
            ChatMessage(
                role="assistant",
                content="Sure! Please share your code and I'll help you debug it.",
            ),
            ChatMessage(
                role="user",
                content="""```python
def fibonacci(n):
    if n <= 1:
        return n
    else:
        return fibonacci(n-1) + fibonacci(n-2)

print(fibonacci(10))
```""",
            ),
            ChatMessage(
                role="assistant",
                content="I can see your Fibonacci function. It looks correct recursively, but it will be inefficient for larger numbers due to repeated calculations. For n=10 it should work fine and output 55. Are you seeing a specific error?",
            ),
            ChatMessage(
                role="user", content="No error, just wanted to check if it's correct"
            ),
            ChatMessage(
                role="assistant",
                content="Yes, your implementation is correct! For better performance with larger numbers, you might want to consider memoization or an iterative approach.",
            ),
        ]

        chat_request = ChatRequest(model="gpt-4", messages=code_conversation)

        # Mock low confidence assessment (productive technical conversation)
        mock_backend.perform_assessment.return_value = {
            "reasoning": "Productive technical conversation about Fibonacci implementation. Code was reviewed, confirmed correct, and performance suggestions were provided. User's questions were answered thoroughly.",
            "confidence": 0.1,
        }

        # When
        with patch.object(middleware, "_get_session_id", return_value=session_id):
            result = None
            for _i in range(4):
                result = await middleware.process(chat_request)

        # Then - Should not trigger steering for productive technical conversation
        assert result is not None
        assert len(result.messages) == len(code_conversation)  # No steering added

    @pytest.mark.asyncio
    async def test_multilingual_conversations(self):
        """
        Given: Conversations in multiple languages
        When: Assessment is triggered
        Then: Should properly analyze regardless of language
        """
        # Given
        config = AssessmentConfig(
            enabled=True,
            turn_threshold=4,
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

        session_id = "multilingual_session"

        # Spanish conversation with repetitive pattern
        spanish_conversation = [
            ChatMessage(role="user", content="Hola"),
            ChatMessage(role="assistant", content="¡Hola! ¿Cómo puedo ayudarte hoy?"),
            ChatMessage(role="user", content="Hola"),
            ChatMessage(role="assistant", content="¡Hola! ¿En qué puedo asistirte?"),
            ChatMessage(role="user", content="Buenos días"),
            ChatMessage(role="assistant", content="¡Buenos días! ¿Qué necesitas?"),
        ]

        chat_request = ChatRequest(model="gpt-4", messages=spanish_conversation)

        # Mock high confidence assessment (repetitive pattern in Spanish)
        mock_backend.perform_assessment.return_value = {
            "reasoning": "Conversación en español atrapada en un patrón repetitivo de saludos. El usuario sigue saludando con diferentes variaciones y el asistente responde con saludos genéricos sin abordar ninguna tarea específica.",
            "confidence": 0.93,
        }

        # When
        with patch.object(middleware, "_get_session_id", return_value=session_id):
            result = None
            for _i in range(4):
                result = await middleware.process(chat_request)

        # Then - Should trigger steering intervention for repetitive pattern regardless of language
        assert result is not None
        assert len(result.messages) > len(spanish_conversation)

        steering_message = result.messages[-1]
        assert steering_message.metadata.get("is_assessment_steering") is True
        assert steering_message.metadata.get("confidence") == 0.93

    @pytest.mark.asyncio
    async def test_conversations_with_system_messages(self):
        """
        Given: Conversations that include system messages
        When: Assessment is triggered
        Then: Should properly handle system messages in analysis
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

        session_id = "system_message_session"

        # Conversation with system messages
        system_message_conversation = [
            ChatMessage(
                role="system",
                content="You are a helpful assistant specialized in data science.",
            ),
            ChatMessage(role="user", content="Help me with pandas"),
            ChatMessage(
                role="assistant",
                content="I'd be happy to help you with pandas! What specific pandas task are you working on?",
            ),
            ChatMessage(role="user", content="Data cleaning"),
            ChatMessage(
                role="assistant",
                content="Data cleaning is a crucial step in data science! What kind of data cleaning challenges are you facing?",
            ),
            ChatMessage(role="user", content="Missing values"),
            ChatMessage(
                role="assistant",
                content="Missing values are common! Pandas offers several methods to handle them: dropna(), fillna(), interpolate(), etc. What would you like to know about handling missing values?",
            ),
        ]

        chat_request = ChatRequest(model="gpt-4", messages=system_message_conversation)

        # Mock low confidence assessment (productive conversation)
        mock_backend.perform_assessment.return_value = {
            "reasoning": "Productive conversation about pandas data cleaning. Assistant is providing helpful, specific guidance about missing value handling methods. Conversation shows clear progression from general topic to specific solutions.",
            "confidence": 0.15,
        }

        # When
        with patch.object(middleware, "_get_session_id", return_value=session_id):
            result = None
            for _i in range(5):
                result = await middleware.process(chat_request)

        # Then - Should handle system messages properly and not trigger steering
        assert result is not None
        assert len(result.messages) == len(
            system_message_conversation
        )  # No steering added

    @pytest.mark.asyncio
    async def test_long_conversation_history_truncation(self):
        """
        Given: Very long conversation history exceeding the history window
        When: Assessment is triggered
        Then: Should analyze only recent messages within the history window
        """
        # Given
        config = AssessmentConfig(
            enabled=True,
            turn_threshold=20,
            confidence_threshold=0.9,
            history_window=10,  # Small history window for testing
            backend="openai",
            model="gpt-4o-mini",
        )

        repository = InMemoryAssessmentRepository()
        turn_counter = TurnCounterService(repository, config)

        mock_backend = Mock()
        mock_backend.perform_assessment = AsyncMock()
        assessment_service = AssessmentService(mock_backend, config)
        middleware = AssessmentMiddleware(assessment_service, turn_counter, config)

        session_id = "long_history_session"

        # Create a long conversation history
        long_conversation = []
        for i in range(50):  # 50 turns, much more than history window of 10
            long_conversation.append(
                ChatMessage(role="user", content=f"User message {i}")
            )
            long_conversation.append(
                ChatMessage(role="assistant", content=f"Assistant response {i}")
            )

        # Add a repetitive pattern at the end (within history window)
        for _i in range(10):
            long_conversation.append(ChatMessage(role="user", content="Help"))
            long_conversation.append(
                ChatMessage(role="assistant", content="I can help!")
            )

        chat_request = ChatRequest(model="gpt-4", messages=long_conversation)

        # Mock high confidence assessment (repetitive pattern detected in recent history)
        mock_backend.perform_assessment.return_value = {
            "reasoning": "Recent conversation shows repetitive 'Help'/'I can help!' pattern. The long history contains varied topics but recent messages indicate a loop.",
            "confidence": 0.91,
        }

        # When
        with patch.object(middleware, "_get_session_id", return_value=session_id):
            result = None
            for _i in range(20):
                result = await middleware.process(chat_request)

        # Then - Should trigger steering based on recent pattern, not entire history
        assert result is not None
        assert len(result.messages) > len(long_conversation)  # Steering added

        # Verify assessment was called with truncated history
        assessment_call_args = mock_backend.perform_assessment.call_args
        if assessment_call_args:
            assessment_request = assessment_call_args[0][0]  # First positional argument
            # Should have trimmed history to window size
            assert (
                len(assessment_request.messages) <= config.history_window + 2
            )  # +2 for system/task prompts
