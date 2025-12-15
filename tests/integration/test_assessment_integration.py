"""
Integration tests for LLM assessment system.

These tests verify the complete assessment flow from configuration to middleware.
"""

from unittest.mock import AsyncMock, Mock, patch

import pytest
from src.core.app.middleware.assessment_middleware import AssessmentMiddleware
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.configuration.assessment_config import AssessmentConfig
from src.core.repositories.assessment_repository import InMemoryAssessmentRepository
from src.core.services.assessment_service import AssessmentService
from src.core.services.turn_counter_service import TurnCounterService


@pytest.fixture
def assessment_config():
    """Assessment configuration for testing."""
    return AssessmentConfig(
        enabled=True,
        turn_threshold=5,  # Lower threshold for testing
        confidence_threshold=0.9,
        history_window=10,
        backend="openai",
        model="gpt-4o-mini",
    )


@pytest.fixture
def assessment_repository():
    """Assessment repository for testing."""
    return InMemoryAssessmentRepository()


@pytest.fixture
def turn_counter_service(assessment_repository, assessment_config):
    """Turn counter service for testing."""
    return TurnCounterService(assessment_repository, assessment_config)


@pytest.fixture
def mock_backend_service():
    """Mock backend service for testing."""
    mock = Mock()
    mock.perform_assessment = AsyncMock()
    return mock


@pytest.fixture
def assessment_service(mock_backend_service, assessment_config):
    """Assessment service for testing."""
    # Mock the prompt loading functions
    with (
        patch("src.core.services.assessment_prompts.get_system_prompt") as mock_system,
        patch("src.core.services.assessment_prompts.get_task_prompt") as mock_task,
    ):

        mock_system.return_value = "Test system prompt for assessment"
        mock_task.return_value = "Test task prompt for assessment"

        return AssessmentService(mock_backend_service, assessment_config)


@pytest.fixture
def assessment_middleware(assessment_service, turn_counter_service, assessment_config):
    """Assessment middleware for testing."""
    return AssessmentMiddleware(
        assessment_service, turn_counter_service, assessment_config
    )


@pytest.fixture
def sample_chat_request():
    """Sample chat request for testing."""
    return ChatRequest(
        model="gpt-4",
        messages=[
            ChatMessage(role="user", content="Hello"),
            ChatMessage(role="assistant", content="Hi there!"),
            ChatMessage(role="user", content="Can you help me?"),
            ChatMessage(role="assistant", content="Of course!"),
            ChatMessage(role="user", content="I need help with Python"),
            ChatMessage(role="assistant", content="I'd be happy to help with Python!"),
        ],
    )


class TestAssessmentIntegration:
    """Integration tests for the assessment system."""

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
    async def test_middleware_disabled(
        self, assessment_middleware, sample_chat_request
    ):
        """Test that middleware passes through when assessment is disabled."""
        # Arrange
        assessment_middleware.config.enabled = False

        # Act
        result = await assessment_middleware.process(sample_chat_request)

        # Assert
        assert result == sample_chat_request  # Should be unchanged

    @pytest.mark.asyncio
    async def test_middleware_turn_counting(
        self, assessment_middleware, turn_counter_service, sample_chat_request
    ):
        """Test that middleware increments turn count."""
        # Arrange
        session_id = "test_session"

        with patch.object(
            assessment_middleware, "_get_session_id", return_value=session_id
        ):
            # Act
            await assessment_middleware.process(sample_chat_request)

            # Assert
            turn_count = turn_counter_service.get_turn_count(session_id)
            assert turn_count == 1

    @pytest.mark.asyncio
    async def test_middleware_assessment_not_triggered_below_threshold(
        self, assessment_middleware, mock_backend_service, sample_chat_request
    ):
        """Test that assessment is not triggered below turn threshold."""
        # Arrange
        session_id = "test_session"

        with patch.object(
            assessment_middleware, "_get_session_id", return_value=session_id
        ):
            # Act - Process request below threshold
            await assessment_middleware.process(sample_chat_request)

            # Assert
            mock_backend_service.perform_assessment.assert_not_called()

    @pytest.mark.asyncio
    async def test_middleware_assessment_triggered_above_threshold(
        self,
        assessment_middleware,
        mock_backend_service,
        turn_counter_service,
        sample_chat_request,
    ):
        """Test that assessment is triggered above turn threshold."""
        # Arrange
        session_id = "test_session"
        mock_response = {"reasoning": "Normal conversation flow", "confidence": 0.2}
        mock_backend_service.perform_assessment.return_value = mock_response

        with patch.object(
            assessment_middleware, "_get_session_id", return_value=session_id
        ):
            # Act - Process multiple requests to exceed threshold
            for _ in range(6):  # Threshold is 5
                await assessment_middleware.process(sample_chat_request)

            # Assert
            mock_backend_service.perform_assessment.assert_called()

    @pytest.mark.asyncio
    async def test_middleware_steering_injection_high_confidence(
        self, assessment_middleware, mock_backend_service, sample_chat_request
    ):
        """Test that steering message is injected for high confidence assessment."""
        # Arrange
        session_id = "test_session"
        mock_response = {
            "reasoning": "The assistant is stuck in a repetitive loop",
            "confidence": 0.95,
        }
        mock_backend_service.perform_assessment.return_value = mock_response
        original_message_count = len(sample_chat_request.messages)

        with patch.object(
            assessment_middleware, "_get_session_id", return_value=session_id
        ):
            # Process enough requests to trigger assessment (threshold is 5)
            result = None
            for _ in range(6):  # Process 6 times to ensure we trigger assessment
                result = await assessment_middleware.process(sample_chat_request)
                # Assessment should trigger on the 5th call (when turn count reaches threshold)
                if len(result.messages) > original_message_count:
                    break

            # Assert
            assert result is not None
            assert len(result.messages) > original_message_count
            assert (
                len(result.messages) == original_message_count + 1
            )  # Should have one additional steering message

            # Check that steering message was added
            steering_message = result.messages[-1]
            assert steering_message.role == "system"
            assert "SYSTEM NOTICE" in steering_message.content
            assert "Test steering template" in steering_message.content
            assert (
                "The assistant is stuck in a repetitive loop"
                in steering_message.content
            )

            # Verify the steering message has the expected metadata
            assert steering_message.metadata is not None
            assert steering_message.metadata.get("is_assessment_steering") is True
            assert steering_message.metadata.get("confidence") == 0.95

    @pytest.mark.asyncio
    async def test_middleware_no_steering_low_confidence(
        self, assessment_middleware, mock_backend_service, sample_chat_request
    ):
        """Test that no steering message is injected for low confidence assessment."""
        # Arrange
        session_id = "test_session"
        mock_response = {
            "reasoning": "Normal conversation progression",
            "confidence": 0.1,
        }
        mock_backend_service.perform_assessment.return_value = mock_response

        with patch.object(
            assessment_middleware, "_get_session_id", return_value=session_id
        ):
            # Process enough requests to trigger assessment
            for _ in range(5):
                await assessment_middleware.process(sample_chat_request)

            # Act - Process one more to trigger assessment
            result = await assessment_middleware.process(sample_chat_request)

            # Assert
            assert len(result.messages) == len(
                sample_chat_request.messages
            )  # No steering added

    @pytest.mark.asyncio
    async def test_middleware_error_handling(
        self, assessment_middleware, mock_backend_service, sample_chat_request
    ):
        """Test that middleware handles assessment errors gracefully."""
        # Arrange
        session_id = "test_session"
        mock_backend_service.perform_assessment.side_effect = Exception("Backend error")

        with patch.object(
            assessment_middleware, "_get_session_id", return_value=session_id
        ):
            # Process enough requests to trigger assessment
            for _ in range(5):
                await assessment_middleware.process(sample_chat_request)

            # Act - Process one more to trigger assessment (should not fail)
            result = await assessment_middleware.process(sample_chat_request)

            # Assert
            assert (
                result == sample_chat_request
            )  # Should return original request despite error

    def test_turn_counter_interval_adjustment(self, turn_counter_service):
        """Test that turn counter adjusts intervals based on confidence."""
        # Arrange
        session_id = "test_session"

        # Act - Adjust interval with high confidence (should decrease interval)
        turn_counter_service.adjust_check_interval(session_id, 0.9)
        state = turn_counter_service.repository.get_session_state(session_id)
        high_confidence_interval = state.current_check_interval

        # Act - Adjust interval with low confidence (should increase interval)
        turn_counter_service.adjust_check_interval(session_id, 0.1)
        state = turn_counter_service.repository.get_session_state(session_id)
        low_confidence_interval = state.current_check_interval

        # Assert
        assert low_confidence_interval > high_confidence_interval

    def test_session_state_persistence(self, assessment_repository):
        """Test that session state persists correctly."""
        # Arrange
        session_id = "test_session"

        # Act
        state1 = assessment_repository.get_session_state(session_id)
        state1.turn_count = 10
        assessment_repository.update_session_state(state1)

        state2 = assessment_repository.get_session_state(session_id)

        # Assert
        assert state2.turn_count == 10
        assert state2.session_id == session_id

    def test_repository_cleanup(self, assessment_repository):
        """Test that repository cleans up expired sessions."""
        # Arrange
        session_id = "test_session"
        state = assessment_repository.get_session_state(session_id)

        # Act - Force expiration by setting old timestamp
        state.last_updated = 0  # Very old timestamp
        assessment_repository._states[session_id] = (
            state  # Direct update to bypass timestamp update
        )

        # Trigger cleanup
        assessment_repository.cleanup_expired_sessions(max_age_seconds=1)

        # Assert
        assert session_id not in assessment_repository._states


class TestConfigurationIntegration:
    """Test configuration loading and validation."""

    def test_cli_configuration_precedence(self):
        """Test that CLI configuration takes precedence."""
        # This would test the actual CLI argument parsing
        # For now, just test the config merge logic

        cli_config = AssessmentConfig.from_cli_args(
            Mock(
                llm_assessment_enabled=True,
                llm_assessment_turn_threshold=50,
                llm_assessment_backend="anthropic",
            )
        )

        env_config = AssessmentConfig.from_env_vars()
        yaml_config = AssessmentConfig()

        merged = AssessmentConfig.merge_configs(cli_config, env_config, yaml_config)

        assert merged.enabled is True
        assert merged.turn_threshold == 50
        assert merged.backend == "anthropic"

    def test_environment_variable_parsing(self):
        """Test environment variable parsing."""
        import os

        # Set environment variables
        os.environ["LLM_ASSESSMENT_ENABLED"] = "true"
        os.environ["LLM_ASSESSMENT_TURN_THRESHOLD"] = "25"
        os.environ["LLM_ASSESSMENT_BACKEND"] = "openai"

        try:
            config = AssessmentConfig.from_env_vars()

            assert config.enabled is True
            assert config.turn_threshold == 25
            assert config.backend == "openai"
        finally:
            # Clean up
            for key in [
                "LLM_ASSESSMENT_ENABLED",
                "LLM_ASSESSMENT_TURN_THRESHOLD",
                "LLM_ASSESSMENT_BACKEND",
            ]:
                os.environ.pop(key, None)
