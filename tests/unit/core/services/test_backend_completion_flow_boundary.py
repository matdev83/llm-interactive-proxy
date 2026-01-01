"""Unit tests for BackendCompletionFlow boundary hardening.

Tests verify that BackendCompletionFlow rejects dict inputs and only accepts
typed contracts (ChatRequest | CanonicalChatRequest).

Requirement: 5.2 - Centralize legacy coercion at explicit adapter boundaries only.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.common.exceptions import InvalidRequestError
from src.core.domain.chat import CanonicalChatRequest, ChatMessage, ChatRequest
from src.core.domain.responses import ResponseEnvelope
from src.core.services.backend_completion_flow.service import BackendCompletionFlow


@pytest.fixture
def mock_dependencies():
    """Create mock dependencies for BackendCompletionFlow."""
    return {
        "availability_checker": MagicMock(),
        "request_preparer": MagicMock(),
        "session_resolver": MagicMock(),
        "backend_invoker": MagicMock(),
        "failover_executor": MagicMock(),
        "wire_capture_orchestrator": MagicMock(),
        "usage_accounting_orchestrator": MagicMock(),
        "exception_normalizer": MagicMock(),
        "stream_formatting_service": MagicMock(),
        "connector_invoker": MagicMock(),
    }


@pytest.fixture
def completion_flow(mock_dependencies):
    """Create a BackendCompletionFlow instance for testing."""
    # Mock all required methods
    mock_dependencies["request_preparer"].prepare_request = AsyncMock(
        return_value=MagicMock(backend="openai", model="gpt-4", uri_params={})
    )
    mock_dependencies["request_preparer"].synchronize_request_with_target = MagicMock(
        return_value=CanonicalChatRequest(
            model="gpt-4", messages=[ChatMessage(role="user", content="test")]
        )
    )
    mock_dependencies["availability_checker"].check_backend_availability = AsyncMock()
    mock_dependencies["failover_executor"].check_complex_failover = AsyncMock(
        return_value=False
    )
    mock_dependencies["backend_invoker"].invoke = AsyncMock(
        return_value=ResponseEnvelope(
            content="test response",
            usage=MagicMock(),
        )
    )

    return BackendCompletionFlow(**mock_dependencies)


@pytest.fixture
def canonical_request():
    """Create a canonical request for testing."""
    return CanonicalChatRequest(
        model="gpt-4",
        messages=[ChatMessage(role="user", content="test")],
    )


@pytest.fixture
def chat_request():
    """Create a ChatRequest for testing."""
    return ChatRequest(
        model="gpt-4",
        messages=[ChatMessage(role="user", content="test")],
    )


class TestBackendCompletionFlowBoundaryHardening:
    """Test that BackendCompletionFlow rejects dict inputs."""

    @pytest.mark.asyncio
    async def test_call_completion_rejects_dict_input(self, completion_flow):
        """Test that call_completion() rejects dict inputs with InvalidRequestError."""
        dict_request = {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "test"}],
        }

        with pytest.raises(InvalidRequestError) as exc_info:
            await completion_flow.call_completion(
                request=dict_request,  # type: ignore[arg-type]
                stream=False,
            )

        assert "dict input" in exc_info.value.message.lower()
        assert "adapter boundaries" in exc_info.value.message.lower()
        assert exc_info.value.details["received_type"] == "dict"
        assert exc_info.value.details["service"] == "BackendCompletionFlow"

    def test_call_completion_accepts_canonical_chat_request_signature(
        self, completion_flow, canonical_request
    ):
        """Test that call_completion() signature accepts CanonicalChatRequest (type check)."""
        # This test verifies the type signature accepts canonical contracts
        import inspect

        sig = inspect.signature(completion_flow.call_completion)
        param = sig.parameters["request"]
        # Verify the annotation allows CanonicalChatRequest (via ChatRequest)
        assert "ChatRequest" in str(param.annotation)

    def test_call_completion_accepts_chat_request_signature(
        self, completion_flow, chat_request
    ):
        """Test that call_completion() signature accepts ChatRequest (type check)."""
        # This test verifies the type signature accepts canonical contracts
        import inspect

        sig = inspect.signature(completion_flow.call_completion)
        param = sig.parameters["request"]
        # Verify the annotation allows ChatRequest
        assert "ChatRequest" in str(param.annotation)
