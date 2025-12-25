"""
Integration test to verify that the hybrid backend correctly overrides reasoning parameters.
"""

from unittest.mock import MagicMock

import pytest
from httpx import AsyncClient
from src.connectors.hybrid import HybridConnector
from src.connectors.utils.model_capabilities import (
    get_execution_params,
    get_reasoning_params,
)
from src.core.config.app_config import AppConfig
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.services.backend_registry import BackendRegistry
from src.core.services.translation_service import TranslationService


def test_model_capabilities_reasoning_params():
    """Test that reasoning parameters are properly defined."""
    openai_reasoning = get_reasoning_params("openai")
    assert openai_reasoning.reasoning_effort == "high"
    assert openai_reasoning["reasoning_effort"] == "high"
    assert openai_reasoning.get("reasoning_effort") == "high"
    assert "reasoning_effort" in openai_reasoning

    openai_execution = get_execution_params("openai")
    assert openai_execution.reasoning_effort == "low"
    assert openai_execution["reasoning_effort"] == "low"
    assert openai_execution.get("reasoning_effort") == "low"
    assert "reasoning_effort" in openai_execution


def test_hybrid_connector_type_handling():
    """Test that the hybrid connector properly handles different input types."""
    # Create mock dependencies
    config = AppConfig()
    mock_translation_service = MagicMock(spec=TranslationService)
    mock_translation_service.to_domain_request.side_effect = (
        lambda request_dict, backend: CanonicalChatRequest(**request_dict)
    )

    # Create an AsyncClient for the test
    client = AsyncClient()

    connector = HybridConnector(
        client=client,
        config=config,
        translation_service=mock_translation_service,
        backend_registry=BackendRegistry(),
    )

    # Create a proper ChatMessage for the request
    chat_message = ChatMessage(role="user", content="Hello")

    # Test with CanonicalChatRequest (DomainModel)
    domain_request = CanonicalChatRequest(
        model="test-model", messages=[chat_message], extra_body={"some_param": "value"}
    )

    # Apply reasoning params (for reasoning phase)
    reasoning_params_dict = dict(get_reasoning_params("openai"))
    result = connector._apply_reasoning_params(domain_request, reasoning_params_dict)

    assert isinstance(result, CanonicalChatRequest)
    assert result.extra_body is not None
    assert "reasoning_effort" in result.extra_body
    assert result.extra_body["reasoning_effort"] == "high"
    assert result.extra_body["some_param"] == "value"

    # Test with dict
    dict_request = {
        "model": "test-model",
        "messages": [{"role": "user", "content": "Hello"}],
        "extra_body": {"some_param": "value"},
    }

    # Apply reasoning params (for reasoning phase)
    result = connector._apply_reasoning_params(dict_request, reasoning_params_dict)
    assert isinstance(result, dict)
    assert "extra_body" in result
    assert result["extra_body"] is not None
    assert "reasoning_effort" in result["extra_body"]
    assert result["extra_body"]["reasoning_effort"] == "high"
    assert result["extra_body"]["some_param"] == "value"


@pytest.mark.asyncio
@pytest.mark.parametrize("backend_name", ["openai", "qwen"])
async def test_hybrid_reasoning_param_override(backend_name: str):
    """
    Test that reasoning parameters are correctly overridden for different backends.
    """
    # Create proper mock dependencies using AsyncClient and AppConfig
    async with AsyncClient() as client:
        config = AppConfig()
        mock_translation_service = MagicMock(spec=TranslationService)
        mock_translation_service.to_domain_request.side_effect = (
            lambda request_dict, backend: CanonicalChatRequest(**request_dict)
        )

        # Initialize hybrid connector with proper types
        connector = HybridConnector(
            client=client,
            config=config,
            translation_service=mock_translation_service,
            backend_registry=BackendRegistry(),
        )

        # Create a proper ChatMessage for the request
        chat_message = ChatMessage(role="user", content="Hello")

        # Test data
        request_data = CanonicalChatRequest(
            model="test-model",
            messages=[chat_message],
            reasoning_effort="low",  # This should be overridden for reasoning phase
            thinking_budget=10,  # This should be overridden for reasoning phase
        )

        # Test reasoning phase parameter application
        reasoning_params = get_reasoning_params(backend_name)
        reasoning_params_dict = dict(reasoning_params)
        reasoning_request = connector._apply_reasoning_params(
            request_data, reasoning_params_dict
        )

        # For reasoning phase, parameters should be set to high reasoning effort
        expected_reasoning_params = get_reasoning_params(backend_name)

        assert isinstance(reasoning_request, CanonicalChatRequest)
        assert reasoning_request.extra_body is not None
        for key, expected_value in expected_reasoning_params.items():
            assert key in reasoning_request.extra_body
            assert reasoning_request.extra_body[key] == expected_value

        # Test execution phase parameter application
        execution_params = get_execution_params(backend_name)
        execution_params_dict = dict(execution_params)
        execution_request = connector._apply_reasoning_params(
            request_data, execution_params_dict
        )

        # For execution phase, parameters should be set to low reasoning effort
        expected_execution_params = get_execution_params(backend_name)

        assert isinstance(execution_request, CanonicalChatRequest)
        assert execution_request.extra_body is not None
        for key, expected_value in expected_execution_params.items():
            assert key in execution_request.extra_body
            assert execution_request.extra_body[key] == expected_value


if __name__ == "__main__":
    pytest.main([__file__])
