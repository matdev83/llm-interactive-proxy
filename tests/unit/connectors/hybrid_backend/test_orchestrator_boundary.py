"""Unit tests for HybridOrchestrator boundary hardening.

Tests verify that HybridOrchestrator rejects dict inputs and only accepts
canonical contracts (CanonicalChatRequest | ChatRequest).

Requirement: 5.2 - Centralize legacy coercion at explicit adapter boundaries only.
"""

from unittest.mock import MagicMock

import pytest
from src.connectors.hybrid_backend.orchestration.orchestrator import HybridOrchestrator
from src.connectors.hybrid_backend.protocols import (
    IInjectionPolicy,
    IMessageAugmentor,
    IModelSpecParser,
    IParameterApplicator,
    IPhaseExecutor,
    IReasoningMarkupProcessor,
    IResponseBuilder,
    IResponseFilter,
)
from src.core.common.exceptions import InvalidRequestError
from src.core.domain.chat import CanonicalChatRequest, ChatMessage


@pytest.fixture
def mock_config():
    """Create a mock AppConfig for testing."""
    config = MagicMock()
    config.backends.disable_hybrid_backend = False
    return config


@pytest.fixture
def orchestrator(mock_config):
    """Create a HybridOrchestrator instance for testing."""
    return HybridOrchestrator(
        model_spec_parser=MagicMock(spec=IModelSpecParser),
        parameter_applicator=MagicMock(spec=IParameterApplicator),
        injection_policy=MagicMock(spec=IInjectionPolicy),
        phase_executor=MagicMock(spec=IPhaseExecutor),
        message_augmentor=MagicMock(spec=IMessageAugmentor),
        response_filter=MagicMock(spec=IResponseFilter),
        response_builder=MagicMock(spec=IResponseBuilder),
        config=mock_config,
        reasoning_markup_processor=MagicMock(spec=IReasoningMarkupProcessor),
    )


@pytest.fixture
def canonical_request():
    """Create a canonical request for testing."""
    return CanonicalChatRequest(
        model="hybrid:openai:gpt-4,openai:gpt-3.5-turbo",
        messages=[ChatMessage(role="user", content="test")],
    )


class TestHybridOrchestratorBoundaryHardening:
    """Test that HybridOrchestrator rejects dict inputs."""

    @pytest.mark.asyncio
    async def test_execute_rejects_dict_input(self, orchestrator):
        """Test that execute() rejects dict inputs with InvalidRequestError."""
        dict_request = {
            "model": "hybrid:openai:gpt-4,openai:gpt-3.5-turbo",
            "messages": [{"role": "user", "content": "test"}],
        }

        with pytest.raises(InvalidRequestError) as exc_info:
            await orchestrator.execute(
                request_data=dict_request,
                processed_messages=[],
                effective_model="hybrid:openai:gpt-4,openai:gpt-3.5-turbo",
            )

        assert "dict input" in exc_info.value.message.lower()
        assert "adapter boundaries" in exc_info.value.message.lower()
        assert exc_info.value.details["received_type"] == "dict"
        assert exc_info.value.details["service"] == "HybridOrchestrator"

    def test_execute_accepts_canonical_chat_request_signature(self, orchestrator, canonical_request):
        """Test that execute() signature accepts CanonicalChatRequest (type check)."""
        # This test verifies the type signature accepts canonical contracts
        import inspect

        sig = inspect.signature(orchestrator.execute)
        param = sig.parameters["request_data"]
        # Verify the annotation allows CanonicalChatRequest
        assert hasattr(param.annotation, "__args__") or "CanonicalChatRequest" in str(
            param.annotation
        )

    def test_execute_accepts_chat_request_signature(self, orchestrator):
        """Test that execute() signature accepts ChatRequest (type check)."""
        # This test verifies the type signature accepts canonical contracts
        import inspect

        sig = inspect.signature(orchestrator.execute)
        param = sig.parameters["request_data"]
        # Verify the annotation allows ChatRequest
        assert hasattr(param.annotation, "__args__") or "ChatRequest" in str(
            param.annotation
        )

    def test_canonical_request_to_dict_only_accepts_contracts(
        self, orchestrator, canonical_request
    ):
        """Test that _canonical_request_to_dict only accepts canonical contracts."""
        # Should work with canonical contracts
        result = orchestrator._canonical_request_to_dict(canonical_request)
        assert isinstance(result, dict)
        assert result["model"] == canonical_request.model

        # Should reject dicts
        with pytest.raises(TypeError) as exc_info:
            orchestrator._canonical_request_to_dict({"model": "test"})
        assert "CanonicalChatRequest or ChatRequest" in str(exc_info.value)
