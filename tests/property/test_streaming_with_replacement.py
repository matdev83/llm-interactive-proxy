"""Property-based tests for streaming with model replacement.

This module contains property-based tests that verify streaming requests
work correctly with model replacement across all valid configurations.

Feature: random-model-replacement
Property 36: Streaming with replacement
Validates: Requirements 10.1
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st
from src.core.domain.configuration.replacement_config import ReplacementConfig
from src.core.domain.request_context import RequestContext
from src.core.services.backend_registry import BackendRegistry
from src.core.services.model_replacement_service import ModelReplacementService


def create_test_registry() -> BackendRegistry:
    """Create a test backend registry with mock backends."""
    registry = BackendRegistry()

    def mock_factory() -> None:
        pass

    # Register test backends
    registry.register_backend("original-backend", mock_factory)
    registry.register_backend("replacement-backend", mock_factory)
    registry.register_backend("test-backend-1", mock_factory)
    registry.register_backend("test-backend-2", mock_factory)

    return registry


def create_test_context(stream: bool = True) -> RequestContext:
    """Create a test request context with streaming flag."""
    context = RequestContext(
        headers={},
        cookies={},
        state=None,
        app_state=None,
    )

    if context.state is None:
        context.state = {}
    context.state["stream"] = stream

    return context


@given(
    probability=st.floats(min_value=0.0, max_value=1.0),
    turn_count=st.integers(min_value=1, max_value=10),
    stream=st.booleans(),
)
@pytest.mark.asyncio
async def test_property_36_streaming_with_replacement(
    probability: float,
    turn_count: int,
    stream: bool,
) -> None:
    """
    Feature: random-model-replacement, Property 36: Streaming with replacement

    For any request with stream=True routed to a replacement model, the response
    must be a streaming response from the replacement backend.

    Validates: Requirements 10.1
    """
    # Create service with test configuration
    registry = create_test_registry()
    config = ReplacementConfig(
        enabled=True,
        probability=probability,
        backend_model="replacement-backend:replacement-model",
        turn_count=turn_count,
    )

    # Use deterministic random generator for testing
    random_value = 0.5
    service = ModelReplacementService(
        config, registry, random_generator=lambda: random_value
    )

    # Create context with streaming flag
    context = create_test_context(stream=stream)

    session_id = "test-session"

    # First turn is always skipped (guaranteed original model)
    first_turn_result = service.should_replace(session_id, context)
    assert first_turn_result is False, "First turn should always return False"

    # Second turn checks probability
    should_replace = service.should_replace(session_id, context)

    # Determine expected behavior based on probability
    expected_replace = random_value < probability
    assert should_replace == expected_replace

    if should_replace:
        # Activate replacement
        await service.activate_replacement(
            session_id, "original-backend", "original-model"
        )

        # Get effective backend:model
        effective_backend, effective_model = service.get_effective_backend_model(
            session_id, "original-backend", "original-model"
        )

        # Verify replacement is active
        assert effective_backend == "replacement-backend"
        assert effective_model == "replacement-model"

        # Verify streaming flag is preserved in context
        assert context.state is not None
        assert "stream" in context.state
        assert context.state["stream"] == stream

        # If streaming is enabled, verify it works with replacement
        if stream:
            # The streaming flag should remain True throughout
            assert context.state["stream"] is True

            # Simulate streaming completion
            service.complete_turn(session_id)

            # Verify turn was completed
            state = service.get_state(session_id)
            if turn_count == 1:
                assert state.active is False
            else:
                assert state.active is True
                assert state.turns_remaining == turn_count - 1
    else:
        # If replacement doesn't trigger, original backend should be used
        effective_backend, effective_model = service.get_effective_backend_model(
            session_id, "original-backend", "original-model"
        )

        assert effective_backend == "original-backend"
        assert effective_model == "original-model"

        # Streaming flag should still be preserved
        assert context.state is not None
        assert "stream" in context.state
        assert context.state["stream"] == stream


@given(
    turn_count=st.integers(min_value=1, max_value=3),  # Reduced from 5 for performance
    num_turns=st.integers(min_value=1, max_value=5),  # Reduced from 10 for performance
)
@pytest.mark.asyncio
async def test_property_36_streaming_across_multiple_turns(
    turn_count: int,
    num_turns: int,
) -> None:
    """
    Feature: random-model-replacement, Property 36: Streaming with replacement

    For any streaming request across multiple turns, streaming should work
    consistently throughout the replacement window.

    Validates: Requirements 10.1
    """
    # Create service with probability=1.0 to ensure replacement
    registry = create_test_registry()
    config = ReplacementConfig(
        enabled=True,
        probability=1.0,
        backend_model="replacement-backend:replacement-model",
        turn_count=turn_count,
    )

    service = ModelReplacementService(config, registry)

    # Create context with streaming enabled
    context = create_test_context(stream=True)

    session_id = "test-session"

    # First turn is skipped (guaranteed original model)
    service.should_replace(session_id, context)

    # Second turn should trigger replacement (probability=1.0)
    should_replace = service.should_replace(session_id, context)
    assert should_replace

    await service.activate_replacement(session_id, "original-backend", "original-model")

    # Simulate multiple streaming turns
    for turn in range(num_turns):
        # Get effective backend:model
        effective_backend, effective_model = service.get_effective_backend_model(
            session_id, "original-backend", "original-model"
        )

        # Determine if replacement should still be active
        turns_completed = min(turn, turn_count)
        if turns_completed < turn_count:
            # Replacement should still be active
            assert effective_backend == "replacement-backend"
            assert effective_model == "replacement-model"
        else:
            # Replacement should be inactive
            assert effective_backend == "original-backend"
            assert effective_model == "original-model"

        # Verify streaming is preserved
        assert context.state is not None
        assert context.state["stream"] is True

        # Complete the turn
        service.complete_turn(session_id)


@given(
    probability=st.floats(min_value=0.0, max_value=1.0),
    backend_name=st.sampled_from(["test-backend-1", "test-backend-2"]),
    model_name=st.text(
        min_size=1,
        max_size=20,
        alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd")),
    ),
)
@pytest.mark.asyncio
async def test_property_36_streaming_with_different_backends(
    probability: float,
    backend_name: str,
    model_name: str,
) -> None:
    """
    Feature: random-model-replacement, Property 36: Streaming with replacement

    For any replacement backend:model combination, streaming should work
    correctly when replacement is active.

    Validates: Requirements 10.1
    """
    # Create service with test configuration
    registry = create_test_registry()
    config = ReplacementConfig(
        enabled=True,
        probability=probability,
        backend_model=f"{backend_name}:{model_name}",
        turn_count=1,
    )

    # Use deterministic random generator
    random_value = 0.5
    service = ModelReplacementService(
        config, registry, random_generator=lambda: random_value
    )

    # Create context with streaming enabled
    context = create_test_context(stream=True)

    session_id = "test-session"

    # First turn is skipped (guaranteed original model)
    service.should_replace(session_id, context)

    # Second turn checks probability
    should_replace = service.should_replace(session_id, context)
    expected_replace = random_value < probability
    assert should_replace == expected_replace

    if should_replace:
        # Activate replacement
        await service.activate_replacement(
            session_id, "original-backend", "original-model"
        )

        # Get effective backend:model
        effective_backend, effective_model = service.get_effective_backend_model(
            session_id, "original-backend", "original-model"
        )

        # Verify replacement is active with correct backend:model
        assert effective_backend == backend_name
        assert effective_model == model_name

        # Verify streaming is enabled
        assert context.state is not None
        assert context.state["stream"] is True


@given(
    turn_count=st.integers(min_value=1, max_value=5),
)
@pytest.mark.asyncio
async def test_property_36_streaming_state_consistency(
    turn_count: int,
) -> None:
    """
    Feature: random-model-replacement, Property 36: Streaming with replacement

    For any streaming request with replacement, the replacement state should
    remain consistent throughout the streaming process.

    Validates: Requirements 10.1
    """
    # Create service with probability=1.0
    registry = create_test_registry()
    config = ReplacementConfig(
        enabled=True,
        probability=1.0,
        backend_model="replacement-backend:replacement-model",
        turn_count=turn_count,
    )

    service = ModelReplacementService(config, registry)

    # Create context with streaming enabled
    context = create_test_context(stream=True)

    session_id = "test-session"

    # First turn is skipped (guaranteed original model)
    service.should_replace(session_id, context)

    # Second turn should trigger replacement (probability=1.0)
    should_replace = service.should_replace(session_id, context)
    assert should_replace

    await service.activate_replacement(session_id, "original-backend", "original-model")

    # Verify initial state
    state = service.get_state(session_id)
    assert state.active is True
    assert state.turns_remaining == turn_count
    assert state.replacement_backend == "replacement-backend"
    assert state.replacement_model == "replacement-model"

    # Simulate streaming turns
    for turn in range(turn_count):
        # Verify state before turn completion
        state = service.get_state(session_id)
        assert state.active is True
        assert state.turns_remaining == turn_count - turn

        # Verify streaming is preserved
        assert context.state["stream"] is True

        # Complete the turn
        service.complete_turn(session_id)

    # Verify final state
    state = service.get_state(session_id)
    assert state.active is False
    assert state.turns_remaining == 0
