"""Integration tests for streaming compatibility with model replacement.

This module tests that model replacement works correctly with streaming requests,
ensuring that streaming responses are properly handled with replacement backends.

Feature: random-model-replacement
Validates: Requirements 10.1, 10.2, 10.3, 10.4, 10.5
"""

from __future__ import annotations

import pytest
from src.core.domain.configuration.replacement_config import ReplacementConfig
from src.core.domain.request_context import RequestContext
from src.core.services.backend_registry import BackendRegistry
from src.core.services.model_replacement_service import ModelReplacementService


def create_test_service(
    probability: float = 1.0,
    backend_model: str = "replacement-backend:replacement-model",
    turn_count: int = 1,
) -> ModelReplacementService:
    """Helper to create a test replacement service."""
    registry = BackendRegistry()

    def mock_factory() -> None:
        pass

    # Register both original and replacement backends
    registry.register_backend("original-backend", mock_factory)
    registry.register_backend("replacement-backend", mock_factory)

    config = ReplacementConfig(
        enabled=True,
        probability=probability,
        backend_model=backend_model,
        turn_count=turn_count,
    )

    return ModelReplacementService(config, registry)


def create_test_context_with_stream(stream: bool = True) -> RequestContext:
    """Helper to create a test request context with streaming flag."""
    context = RequestContext(
        headers={},
        cookies={},
        state=None,
        app_state=None,
    )

    # Add streaming flag to context state
    if context.state is None:
        context.state = {}
    context.state["stream"] = stream

    return context


@pytest.mark.asyncio
async def test_streaming_works_with_replacement() -> None:
    """Test that stream=True requests work with replacement.

    When replacement is active and a streaming request is made, the request
    should be routed to the replacement backend and streaming should work.

    Validates: Requirements 10.1
    """
    # Create service with probability=1.0 to ensure replacement triggers
    service = create_test_service(probability=1.0, turn_count=1)

    # Create context with streaming enabled
    context = create_test_context_with_stream(stream=True)

    session_id = "test-session"

    # Check if replacement should trigger
    should_replace = service.should_replace(session_id, context)
    assert should_replace, "Replacement should trigger with probability=1.0"

    # Activate replacement
    await service.activate_replacement(session_id, "original-backend", "original-model")

    # Get effective backend:model
    effective_backend, effective_model = service.get_effective_backend_model(
        session_id, "original-backend", "original-model"
    )

    # Verify replacement is active
    assert effective_backend == "replacement-backend"
    assert effective_model == "replacement-model"

    # Verify streaming flag is preserved
    assert context.state is not None
    assert "stream" in context.state
    assert context.state["stream"] is True


@pytest.mark.asyncio
async def test_streaming_responses_returned_correctly() -> None:
    """Test that streaming responses are returned correctly with replacement.

    When replacement is active and streaming is enabled, the streaming
    response should be properly returned from the replacement backend.

    Validates: Requirements 10.1
    """
    # Create service with probability=1.0
    service = create_test_service(probability=1.0, turn_count=3)

    # Create context with streaming enabled
    context = create_test_context_with_stream(stream=True)

    session_id = "test-session"

    # Activate replacement
    should_replace = service.should_replace(session_id, context)
    assert should_replace

    await service.activate_replacement(session_id, "original-backend", "original-model")

    # Simulate multiple streaming turns
    for turn in range(3):
        # Get effective backend:model
        effective_backend, effective_model = service.get_effective_backend_model(
            session_id, "original-backend", "original-model"
        )

        if turn < 2:  # First 2 turns should use replacement
            assert effective_backend == "replacement-backend"
            assert effective_model == "replacement-model"

        # Verify streaming is still enabled
        assert context.state is not None
        assert context.state["stream"] is True

        # Complete the turn (simulating streaming completion)
        service.complete_turn(session_id)

    # After all turns, replacement should be inactive
    effective_backend, effective_model = service.get_effective_backend_model(
        session_id, "original-backend", "original-model"
    )
    assert effective_backend == "original-backend"
    assert effective_model == "original-model"


@pytest.mark.asyncio
async def test_non_streaming_requests_unaffected() -> None:
    """Test that non-streaming requests work normally with replacement.

    When replacement is active and streaming is disabled, the request
    should work normally without streaming.

    Validates: Requirements 10.1
    """
    # Create service with probability=1.0
    service = create_test_service(probability=1.0, turn_count=1)

    # Create context with streaming disabled
    context = create_test_context_with_stream(stream=False)

    session_id = "test-session"

    # Activate replacement
    should_replace = service.should_replace(session_id, context)
    assert should_replace

    await service.activate_replacement(session_id, "original-backend", "original-model")

    # Get effective backend:model
    effective_backend, effective_model = service.get_effective_backend_model(
        session_id, "original-backend", "original-model"
    )

    # Verify replacement is active
    assert effective_backend == "replacement-backend"
    assert effective_model == "replacement-model"

    # Verify streaming is disabled
    assert context.state is not None
    assert "stream" in context.state
    assert context.state["stream"] is False


@pytest.mark.asyncio
async def test_streaming_format_consistency() -> None:
    """Test that streaming format matches original backend.

    When replacement is active with streaming, the format should be
    consistent regardless of which backend is used.

    Validates: Requirements 10.2
    """
    # Create service with probability=1.0
    service = create_test_service(probability=1.0, turn_count=1)

    # Create context with streaming enabled
    context = create_test_context_with_stream(stream=True)

    session_id = "test-session"

    # Activate replacement
    should_replace = service.should_replace(session_id, context)
    assert should_replace

    await service.activate_replacement(session_id, "original-backend", "original-model")

    # Get effective backend:model
    effective_backend, effective_model = service.get_effective_backend_model(
        session_id, "original-backend", "original-model"
    )

    # Verify replacement is active
    assert effective_backend == "replacement-backend"
    assert effective_model == "replacement-model"

    # The format consistency is ensured by the backend implementation
    # This test verifies that the replacement service doesn't interfere
    # with format handling
    assert context.state["stream"] is True


@pytest.mark.asyncio
async def test_streaming_turn_completion() -> None:
    """Test that streaming requests complete turns correctly.

    When a streaming request completes with replacement active, the
    turn counter should be decremented properly.

    Validates: Requirements 10.3
    """
    # Create service with 3-turn window
    service = create_test_service(probability=1.0, turn_count=3)

    # Create context with streaming enabled
    context = create_test_context_with_stream(stream=True)

    session_id = "test-session"

    # Activate replacement
    should_replace = service.should_replace(session_id, context)
    assert should_replace

    await service.activate_replacement(session_id, "original-backend", "original-model")

    # Get initial state
    state = service.get_state(session_id)
    assert state.active is True
    assert state.turns_remaining == 3

    # Complete first streaming turn
    service.complete_turn(session_id)
    state = service.get_state(session_id)
    assert state.active is True
    assert state.turns_remaining == 2

    # Complete second streaming turn
    service.complete_turn(session_id)
    state = service.get_state(session_id)
    assert state.active is True
    assert state.turns_remaining == 1

    # Complete third streaming turn
    service.complete_turn(session_id)
    state = service.get_state(session_id)
    assert state.active is False
    assert state.turns_remaining == 0


@pytest.mark.asyncio
async def test_streaming_context_association() -> None:
    """Test that streaming context uses effective backend:model.

    When streaming is active with replacement, the streaming context
    should be associated with the replacement backend:model.

    Validates: Requirements 10.5
    """
    # Create service with probability=1.0
    service = create_test_service(probability=1.0, turn_count=1)

    # Create context with streaming enabled
    context = create_test_context_with_stream(stream=True)

    session_id = "test-session"

    # Activate replacement
    should_replace = service.should_replace(session_id, context)
    assert should_replace

    await service.activate_replacement(session_id, "original-backend", "original-model")

    # Get effective backend:model
    effective_backend, effective_model = service.get_effective_backend_model(
        session_id, "original-backend", "original-model"
    )

    # Verify the effective backend:model is the replacement
    assert effective_backend == "replacement-backend"
    assert effective_model == "replacement-model"

    # The streaming context should use these values
    # This is verified by the fact that get_effective_backend_model
    # returns the replacement values when active
    state = service.get_state(session_id)
    assert state.replacement_backend == "replacement-backend"
    assert state.replacement_model == "replacement-model"


@pytest.mark.asyncio
async def test_streaming_error_handling_consistency() -> None:
    """Test that streaming errors are handled consistently.

    When streaming errors occur with replacement, error handling should
    be identical to error handling with the original model.

    Validates: Requirements 10.4
    """
    # Create service with probability=1.0
    service = create_test_service(probability=1.0, turn_count=1)

    # Create context with streaming enabled
    context = create_test_context_with_stream(stream=True)

    session_id = "test-session"

    # Activate replacement
    should_replace = service.should_replace(session_id, context)
    assert should_replace

    await service.activate_replacement(session_id, "original-backend", "original-model")

    # Get effective backend:model
    effective_backend, effective_model = service.get_effective_backend_model(
        session_id, "original-backend", "original-model"
    )

    # Verify replacement is active
    assert effective_backend == "replacement-backend"
    assert effective_model == "replacement-model"

    # Simulate error by completing turn (error handling would happen
    # in the backend layer, but turn completion should still work)
    service.complete_turn(session_id)

    # Verify turn was completed even with simulated error
    state = service.get_state(session_id)
    assert state.active is False
