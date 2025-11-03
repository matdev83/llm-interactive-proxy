from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from src.connectors.hybrid import HybridConnector
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.domain.responses import ResponseEnvelope


@pytest.fixture
def mock_client():
    return AsyncMock(spec=httpx.AsyncClient)


@pytest.fixture
def mock_config():
    config = MagicMock()
    config.backends.disable_hybrid_backend = False
    return config


@pytest.fixture
def mock_translation_service():
    return MagicMock()


@pytest.fixture
def mock_backend_registry():
    return MagicMock()


@pytest.mark.asyncio
@patch("random.random", return_value=0.4)
async def test_hybrid_connector_uses_reasoning_when_probability_is_high(
    mock_random,
    mock_client,
    mock_config,
    mock_translation_service,
    mock_backend_registry,
):
    """
    Test that the reasoning phase is executed when the random number is less than the probability.
    """
    # Arrange
    mock_config.backends.reasoning_injection_probability = 0.5
    hybrid_connector = HybridConnector(
        client=mock_client,
        config=mock_config,
        translation_service=mock_translation_service,
        backend_registry=mock_backend_registry,
    )
    hybrid_connector._execute_reasoning_phase = AsyncMock(
        return_value=MagicMock(text="reasoning", tool_calls=[])
    )
    hybrid_connector._execute_execution_phase = AsyncMock(
        return_value=ResponseEnvelope(content={})
    )
    hybrid_connector._parse_hybrid_model_spec = MagicMock(
        return_value=(
            "reasoning_backend",
            "reasoning_model",
            {},
            "exec_backend",
            "exec_model",
            {},
        )
    )

    request = CanonicalChatRequest(
        model="hybrid:[test:test,test:test]",
        messages=[ChatMessage(role="user", content="Hello")],
    )

    # Act
    await hybrid_connector.chat_completions(
        request_data=request,
        processed_messages=[],
        effective_model="hybrid:[test:test,test:test]",
    )

    # Assert
    hybrid_connector._execute_reasoning_phase.assert_called_once()
    hybrid_connector._execute_execution_phase.assert_called_once()


@pytest.mark.asyncio
@patch("random.random", return_value=0.6)
async def test_hybrid_connector_skips_reasoning_when_probability_is_low(
    mock_random,
    mock_client,
    mock_config,
    mock_translation_service,
    mock_backend_registry,
):
    """
    Test that the reasoning phase is skipped when the random number is greater than the probability.
    """
    # Arrange
    mock_config.backends.reasoning_injection_probability = 0.5
    hybrid_connector = HybridConnector(
        client=mock_client,
        config=mock_config,
        translation_service=mock_translation_service,
        backend_registry=mock_backend_registry,
    )
    hybrid_connector._execute_reasoning_phase = AsyncMock()
    hybrid_connector._execute_execution_phase = AsyncMock(
        return_value=ResponseEnvelope(content={})
    )
    hybrid_connector._parse_hybrid_model_spec = MagicMock(
        return_value=(
            "reasoning_backend",
            "reasoning_model",
            {},
            "exec_backend",
            "exec_model",
            {},
        )
    )

    request = CanonicalChatRequest(
        model="hybrid:[test:test,test:test]",
        messages=[ChatMessage(role="user", content="Hello")],
    )

    # Act
    await hybrid_connector.chat_completions(
        request_data=request,
        processed_messages=[],
        effective_model="hybrid:[test:test,test:test]",
    )

    # Assert
    hybrid_connector._execute_reasoning_phase.assert_not_called()
    hybrid_connector._execute_execution_phase.assert_called_once()


@pytest.mark.asyncio
@patch("random.random", return_value=0.9)
async def test_hybrid_connector_skips_reasoning_with_zero_probability(
    mock_random,
    mock_client,
    mock_config,
    mock_translation_service,
    mock_backend_registry,
):
    """
    Test that the reasoning phase is always skipped when probability is 0.
    """
    # Arrange
    mock_config.backends.reasoning_injection_probability = 0.0
    hybrid_connector = HybridConnector(
        client=mock_client,
        config=mock_config,
        translation_service=mock_translation_service,
        backend_registry=mock_backend_registry,
    )
    hybrid_connector._execute_reasoning_phase = AsyncMock()
    hybrid_connector._execute_execution_phase = AsyncMock(
        return_value=ResponseEnvelope(content={})
    )
    hybrid_connector._parse_hybrid_model_spec = MagicMock(
        return_value=(
            "reasoning_backend",
            "reasoning_model",
            {},
            "exec_backend",
            "exec_model",
            {},
        )
    )

    request = CanonicalChatRequest(
        model="hybrid:[test:test,test:test]",
        messages=[ChatMessage(role="user", content="Hello")],
    )

    # Act
    await hybrid_connector.chat_completions(
        request_data=request,
        processed_messages=[],
        effective_model="hybrid:[test:test,test:test]",
    )

    # Assert
    hybrid_connector._execute_reasoning_phase.assert_not_called()
    hybrid_connector._execute_execution_phase.assert_called_once()


@pytest.mark.asyncio
@patch("random.random", return_value=0.1)
async def test_hybrid_connector_uses_reasoning_with_one_probability(
    mock_random,
    mock_client,
    mock_config,
    mock_translation_service,
    mock_backend_registry,
):
    """
    Test that the reasoning phase is always executed when probability is 1.
    """
    # Arrange
    mock_config.backends.reasoning_injection_probability = 1.0
    hybrid_connector = HybridConnector(
        client=mock_client,
        config=mock_config,
        translation_service=mock_translation_service,
        backend_registry=mock_backend_registry,
    )
    hybrid_connector._execute_reasoning_phase = AsyncMock(
        return_value=MagicMock(text="reasoning", tool_calls=[])
    )
    hybrid_connector._execute_execution_phase = AsyncMock(
        return_value=ResponseEnvelope(content={})
    )
    hybrid_connector._parse_hybrid_model_spec = MagicMock(
        return_value=(
            "reasoning_backend",
            "reasoning_model",
            {},
            "exec_backend",
            "exec_model",
            {},
        )
    )

    request = CanonicalChatRequest(
        model="hybrid:[test:test,test:test]",
        messages=[ChatMessage(role="user", content="Hello")],
    )

    # Act
    await hybrid_connector.chat_completions(
        request_data=request,
        processed_messages=[],
        effective_model="hybrid:[test:test,test:test]",
    )

    # Assert
    hybrid_connector._execute_reasoning_phase.assert_called_once()
    hybrid_connector._execute_execution_phase.assert_called_once()


@pytest.mark.asyncio
@patch("random.random", return_value=0.4)
async def test_hybrid_connector_updates_probability_at_runtime(
    mock_random,
    mock_client,
    mock_config,
    mock_translation_service,
    mock_backend_registry,
):
    """
    Test that the reasoning injection probability is re-evaluated on each call.
    """
    # Arrange
    mock_config.backends.reasoning_injection_probability = 1.0  # Start with 100%
    hybrid_connector = HybridConnector(
        client=mock_client,
        config=mock_config,
        translation_service=mock_translation_service,
        backend_registry=mock_backend_registry,
    )
    hybrid_connector._execute_reasoning_phase = AsyncMock(
        return_value=MagicMock(text="reasoning", tool_calls=[])
    )
    hybrid_connector._execute_execution_phase = AsyncMock(
        return_value=ResponseEnvelope(content={})
    )
    hybrid_connector._parse_hybrid_model_spec = MagicMock(
        return_value=(
            "reasoning_backend",
            "reasoning_model",
            {},
            "exec_backend",
            "exec_model",
            {},
        )
    )

    request = CanonicalChatRequest(
        model="hybrid:[test:test,test:test]",
        messages=[ChatMessage(role="user", content="Hello")],
    )

    # Act 1: Call with 100% probability
    await hybrid_connector.chat_completions(
        request_data=request,
        processed_messages=[],
        effective_model="hybrid:[test:test,test:test]",
    )

    # Assert 1: Reasoning phase should be called
    hybrid_connector._execute_reasoning_phase.assert_called_once()
    hybrid_connector._execute_execution_phase.assert_called_once()

    # Arrange 2: Update probability to 0% and reset mocks
    mock_config.backends.reasoning_injection_probability = 0.0
    hybrid_connector._execute_reasoning_phase.reset_mock()
    hybrid_connector._execute_execution_phase.reset_mock()

    # Act 2: Call with 0% probability
    await hybrid_connector.chat_completions(
        request_data=request,
        processed_messages=[],
        effective_model="hybrid:[test:test,test:test]",
    )

    # Assert 2: Reasoning phase should be skipped
    hybrid_connector._execute_reasoning_phase.assert_not_called()
    hybrid_connector._execute_execution_phase.assert_called_once()
