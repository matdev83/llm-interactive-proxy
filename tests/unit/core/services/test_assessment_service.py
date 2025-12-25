"""
Unit tests for the assessment service.

These tests verify the core assessment functionality replicating gemini-cli behavior.
"""

from unittest.mock import AsyncMock, Mock, patch

import pytest
from src.core.domain.assessment import AssessmentResult, LLMAssessmentResponse
from src.core.domain.chat import ChatMessage
from src.core.domain.configuration.assessment_config import AssessmentConfig
from src.core.services.assessment_service import AssessmentError, AssessmentService


@pytest.fixture
def mock_backend_service():
    """Mock assessment backend service."""
    mock = Mock()
    mock.perform_assessment = AsyncMock()
    return mock


@pytest.fixture
def assessment_config():
    """Assessment configuration for testing."""
    return AssessmentConfig(
        enabled=True,
        turn_threshold=30,
        confidence_threshold=0.9,
        history_window=20,
        backend="openai",
        model="gpt-4o-mini",
    )


@pytest.fixture
def assessment_service(mock_backend_service, assessment_config):
    """Assessment service instance for testing."""
    return AssessmentService(mock_backend_service, assessment_config)


@pytest.fixture
def sample_conversation():
    """Sample conversation history for testing."""
    return [
        ChatMessage(role="user", content="Hello, can you help me with a task?"),
        ChatMessage(
            role="assistant",
            content="Of course! I'd be happy to help. What do you need assistance with?",
        ),
        ChatMessage(role="user", content="I need to write a Python function"),
        ChatMessage(
            role="assistant",
            content="I can help you write a Python function. What should the function do?",
        ),
        ChatMessage(
            role="user", content="It should calculate the factorial of a number"
        ),
        ChatMessage(
            role="assistant",
            content="Here's a Python function to calculate factorial:\n\n```python\ndef factorial(n):\n    if n == 0 or n == 1:\n        return 1\n    return n * factorial(n - 1)\n```",
        ),
    ]


class TestAssessmentService:
    """Test cases for AssessmentService."""

    @pytest.fixture(autouse=True)
    def mock_prompt_loader(self):
        """Mock the prompt loader for all tests."""
        with patch(
            "src.core.services.assessment_prompts._prompt_loader"
        ) as mock_loader:
            mock_loader.is_loaded = True
            mock_loader.system_prompt = "Test system prompt for assessment"
            mock_loader.task_prompt = "Test task prompt for assessment"
            mock_loader.steering_template = (
                "[SYSTEM NOTICE] Test steering template. {reasoning}"
            )
            yield mock_loader

    @pytest.mark.asyncio
    async def test_assess_conversation_success(
        self, assessment_service, mock_backend_service, sample_conversation
    ):
        """Test successful conversation assessment."""
        # Arrange

        mock_response = LLMAssessmentResponse(
            reasoning="The conversation shows normal progress with the user asking for help and the assistant providing a helpful response.",
            confidence=0.1,
        )
        mock_backend_service.perform_assessment.return_value = mock_response

        # Act
        result = await assessment_service.assess_conversation(
            sample_conversation, "test_session"
        )

        # Assert
        assert isinstance(result, AssessmentResult)
        assert result.reasoning == mock_response.reasoning
        assert result.confidence == 0.1

        assert result.session_id == "test_session"
        assert not result.is_unproductive  # confidence < 0.9
        assert not result.should_intervene

        # Verify backend was called
        mock_backend_service.perform_assessment.assert_called_once()

    @pytest.mark.asyncio
    async def test_assess_conversation_high_confidence(
        self, assessment_service, mock_backend_service, sample_conversation
    ):
        """Test assessment with high confidence (should trigger intervention)."""
        # Arrange

        mock_response = LLMAssessmentResponse(
            reasoning="The assistant is repeating the same response multiple times without making progress.",
            confidence=0.95,
        )
        mock_backend_service.perform_assessment.return_value = mock_response


        # Act
        result = await assessment_service.assess_conversation(
            sample_conversation, "test_session"
        )

        # Assert
        assert result.confidence == 0.95
        assert result.is_unproductive  # confidence > 0.9
        assert result.should_intervene

    @pytest.mark.asyncio
    async def test_assess_conversation_backend_error(
        self, assessment_service, mock_backend_service, sample_conversation
    ):
        """Test assessment when backend fails."""
        # Arrange
        mock_backend_service.perform_assessment.side_effect = Exception("Backend error")

        # Act & Assert
        with pytest.raises(AssessmentError):
            await assessment_service.assess_conversation(
                sample_conversation, "test_session"
            )

    @pytest.mark.asyncio
    async def test_assess_conversation_safe_with_error(
        self, assessment_service, mock_backend_service, sample_conversation
    ):
        """Test safe assessment method with backend error."""
        # Arrange
        mock_backend_service.perform_assessment.side_effect = Exception("Backend error")

        # Act
        result = await assessment_service.assess_conversation_safe(
            sample_conversation, "test_session"
        )

        # Assert
        assert result is None  # Should return None on error, not raise

    @pytest.mark.asyncio
    async def test_assess_conversation_invalid_response(
        self, assessment_service, mock_backend_service, sample_conversation
    ):
        """Test assessment with invalid backend response."""
        # Arrange
        # Mock a response object that's missing 'confidence'
        mock_response = Mock(spec=["reasoning"])
        mock_response.reasoning = "Valid reasoning"
        # Accessing confidence will raise AttributeError which we want to test
        # but the service catches generic Exception and raises AssessmentError
        mock_backend_service.perform_assessment.return_value = mock_response

        # Act & Assert
        with pytest.raises(AssessmentError, match="Assessment failed"):
            await assessment_service.assess_conversation(
                sample_conversation, "test_session"
            )

    @pytest.mark.asyncio
    async def test_assess_conversation_invalid_confidence_range(
        self, assessment_service, mock_backend_service, sample_conversation
    ):
        """Test assessment with confidence outside valid range."""
        # Arrange
        # Use model_construct to bypass Pydantic validation during creation
        mock_response = LLMAssessmentResponse.model_construct(
            reasoning="Valid reasoning",
            confidence=1.5,  # Invalid: > 1.0
        )
        mock_backend_service.perform_assessment.return_value = mock_response

        # Act & Assert
        with pytest.raises(AssessmentError, match="Invalid confidence"):
            await assessment_service.assess_conversation(
                sample_conversation, "test_session"
            )


    def test_trim_recent_history_within_window(
        self, assessment_service, sample_conversation
    ):
        """Test history trimming when within window size."""
        # Act
        trimmed = assessment_service._trim_recent_history(sample_conversation)

        # Assert
        assert len(trimmed) == len(sample_conversation)  # Should be unchanged
        assert trimmed == sample_conversation

    def test_trim_recent_history_exceeds_window(self, assessment_service):
        """Test history trimming when exceeding window size."""
        # Arrange - Create conversation longer than window (20 messages)
        long_conversation = [
            ChatMessage(
                role="user" if i % 2 == 0 else "assistant", content=f"Message {i}"
            )
            for i in range(25)
        ]

        # Act
        trimmed = assessment_service._trim_recent_history(long_conversation)

        # Assert
        assert len(trimmed) == 20  # Should be trimmed to window size
        assert trimmed == long_conversation[-20:]  # Should be the most recent messages

    def test_create_assessment_request(self, assessment_service, sample_conversation):
        """Test assessment request creation."""
        # Arrange

        # Act
        request = assessment_service._create_assessment_request(
            sample_conversation, "test_session"
        )

        # Assert
        assert request.session_id == "test_session"
        assert (
            len(request.messages) == len(sample_conversation) + 2
        )  # +system +task prompt
        assert request.messages[0].role == "system"
        assert request.messages[-1].role == "user"
        assert "test task prompt for assessment" in request.messages[-1].content.lower()


class TestAssessmentConfig:
    """Test cases for AssessmentConfig."""

    def test_default_values_match_gemini_cli(self):
        """Test that default values match gemini-cli constants."""
        config = AssessmentConfig()

        # Verify gemini-cli constants are replicated
        assert config.turn_threshold == 30  # LLM_CHECK_AFTER_TURNS
        assert config.history_window == 20  # LLM_LOOP_CHECK_HISTORY_COUNT
        assert config.min_interval == 5  # MIN_LLM_CHECK_INTERVAL
        assert config.max_interval == 15  # MAX_LLM_CHECK_INTERVAL
        assert config.default_interval == 3  # DEFAULT_LLM_CHECK_INTERVAL
        assert config.confidence_threshold == 0.9

    def test_validation_success(self):
        """Test successful configuration validation."""
        config = AssessmentConfig(
            enabled=True,
            backend="openai",
            model="gpt-4o-mini",
            turn_threshold=30,
            confidence_threshold=0.9,
        )

        errors = config.validate()
        assert len(errors) == 0

    def test_validation_missing_backend(self):
        """Test validation failure when backend is missing."""
        config = AssessmentConfig(enabled=True, model="gpt-4o-mini", backend="")

        errors = config.validate()
        assert any(
            "backend must be specified when assessment is enabled" in error
            for error in errors
        )

    def test_validation_invalid_confidence(self):
        """Test validation failure with invalid confidence threshold."""
        config = AssessmentConfig(confidence_threshold=1.5)

        errors = config.validate()
        assert any(
            "confidence_threshold must be between 0.0 and 1.0" in error
            for error in errors
        )

    def test_validation_invalid_intervals(self):
        """Test validation failure with invalid intervals."""
        config = AssessmentConfig(min_interval=10, max_interval=5)

        errors = config.validate()
        assert any("max_interval must be >= min_interval" in error for error in errors)


class TestAssessmentResult:
    """Test cases for AssessmentResult."""

    def test_from_llm_response(self):
        """Test creating AssessmentResult from LLM response."""
        response = {"reasoning": "Test reasoning", "confidence": 0.85}

        result = AssessmentResult.from_llm_response(response, "test_session", 42)

        assert result.reasoning == "Test reasoning"
        assert result.confidence == 0.85
        assert result.session_id == "test_session"
        assert result.turn_count == 42
        assert not result.is_unproductive  # confidence < 0.9

    def test_is_unproductive_threshold(self):
        """Test unproductive detection at confidence threshold."""
        # Below threshold
        result_low = AssessmentResult(
            reasoning="Low confidence", confidence=0.89, session_id="test", turn_count=1
        )
        assert not result_low.is_unproductive

        # At threshold
        result_threshold = AssessmentResult(
            reasoning="At threshold", confidence=0.9, session_id="test", turn_count=1
        )
        assert result_threshold.is_unproductive  # >= 0.9, threshold behavior

        # Above threshold
        result_high = AssessmentResult(
            reasoning="High confidence",
            confidence=0.91,
            session_id="test",
            turn_count=1,
        )
        assert result_high.is_unproductive

    def test_to_dict(self):
        """Test conversion to dictionary."""
        result = AssessmentResult(
            reasoning="Test reasoning",
            confidence=0.95,
            session_id="test_session",
            turn_count=50,
        )

        data = result.to_dict()

        assert data["reasoning"] == "Test reasoning"
        assert data["confidence"] == 0.95
        assert data["session_id"] == "test_session"
        assert data["turn_count"] == 50
        assert data["is_unproductive"] is True
        assert "timestamp" in data
