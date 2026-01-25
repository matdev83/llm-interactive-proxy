"""Property-based tests for streaming error handling with model replacement.

This module contains property-based tests that verify streaming error handling
is consistent when using replacement models.

Feature: random-model-replacement
Property 39: Streaming error handling
Validates: Requirements 10.4
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
    registry.register_backend("error-backend", mock_factory)

    return registry


def create_test_context(
    stream: bool = True, simulate_error: bool = False
) -> RequestContext:
    """Create a test request context with streaming and error simulation."""
    context = RequestContext(
        headers={},
        cookies={},
        state=None,
        app_state=None,
    )

    if context.state is None:
        context.state = {}
    context.state["stream"] = stream
    context.state["simulate_error"] = simulate_error

    return context


@given(
    probability=st.floats(min_value=0.0, max_value=1.0),
    turn_count=st.integers(min_value=1, max_value=5),
    simulate_error=st.booleans(),
)
@pytest.mark.asyncio
async def test_property_39_streaming_error_handling(
    probability: float,
    turn_count: int,
    simulate_error: bool,
) -> None:
    """
    Feature: random-model-replacement, Property 39: Streaming error handling

    For any streaming error with a replacement model, error handling must be
    identical to error handling with the original model.

    Validates: Requirements 10.4
    """
    # Create service with test configuration
    registry = create_test_registry()
    config = ReplacementConfig(
        enabled=True,
        probability=probability,
        backend_model="replacement-backend:replacement-model",
        turn_count=turn_count,
    )

    # Use deterministic random generator
    random_value = 0.5
    service = ModelReplacementService(
        config, registry, random_generator=lambda: random_value
    )

    # Create context with streaming and error simulation
    context = create_test_context(stream=True, simulate_error=simulate_error)

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

        # Verify replacement is active
        assert effective_backend == "replacement-backend"
        assert effective_model == "replacement-model"

        # Simulate error scenario
        if simulate_error:
            # Even with error, turn should be completed
            service.complete_turn(session_id)

            # Verify state was updated despite error
            state = service.get_state(session_id)
            if turn_count == 1:
                assert state.active is False
            else:
                assert state.active is True
                assert state.turns_remaining == turn_count - 1
        else:
            # Normal completion
            service.complete_turn(session_id)

            state = service.get_state(session_id)
            if turn_count == 1:
                assert state.active is False
            else:
                assert state.active is True
                assert state.turns_remaining == turn_count - 1


@given(
    turn_count=st.integers(min_value=1, max_value=5),
)
@pytest.mark.asyncio
async def test_property_39_error_during_streaming_turn(
    turn_count: int,
) -> None:
    """
    Feature: random-model-replacement, Property 39: Streaming error handling

    For any streaming turn that encounters an error, the turn counter should
    still be decremented to maintain consistency.

    Validates: Requirements 10.4
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

    # Create context with streaming and error simulation
    context = create_test_context(stream=True, simulate_error=True)

    session_id = "test-session"

    # First turn is skipped (guaranteed original model)
    service.should_replace(session_id, context)

    # Second turn should trigger replacement (probability=1.0)
    should_replace = service.should_replace(session_id, context)
    assert should_replace

    await service.activate_replacement(session_id, "original-backend", "original-model")

    # Get initial state
    state = service.get_state(session_id)
    assert state.active is True
    assert state.turns_remaining == turn_count

    # Simulate error during first turn
    service.complete_turn(session_id)

    # Verify turn was completed despite error
    state = service.get_state(session_id)
    if turn_count == 1:
        assert state.active is False
        assert state.turns_remaining == 0
    else:
        assert state.active is True
        assert state.turns_remaining == turn_count - 1


@given(
    turn_count=st.integers(min_value=2, max_value=5),
    error_turn=st.integers(min_value=0, max_value=4),
)
@pytest.mark.asyncio
async def test_property_39_error_at_specific_turn(
    turn_count: int,
    error_turn: int,
) -> None:
    """
    Feature: random-model-replacement, Property 39: Streaming error handling

    For any streaming session, an error at a specific turn should not affect
    the error handling of subsequent turns.

    Validates: Requirements 10.4
    """
    # Ensure error_turn is within valid range
    if error_turn >= turn_count:
        error_turn = turn_count - 1

    # Create service with probability=1.0
    registry = create_test_registry()
    config = ReplacementConfig(
        enabled=True,
        probability=1.0,
        backend_model="replacement-backend:replacement-model",
        turn_count=turn_count,
    )

    service = ModelReplacementService(config, registry)

    session_id = "test-session"

    # First turn is skipped (guaranteed original model)
    context = create_test_context(stream=True, simulate_error=False)
    service.should_replace(session_id, context)

    # Second turn should trigger replacement (probability=1.0)
    should_replace = service.should_replace(session_id, context)
    assert should_replace

    await service.activate_replacement(session_id, "original-backend", "original-model")

    # Simulate turns with error at specific turn
    for turn in range(turn_count):
        # Simulate error at specific turn
        if turn == error_turn:
            context.state["simulate_error"] = True
        else:
            context.state["simulate_error"] = False

        # Complete turn (with or without error)
        service.complete_turn(session_id)

        # Verify state is consistent
        state = service.get_state(session_id)
        remaining_turns = turn_count - turn - 1

        if remaining_turns > 0:
            assert state.active is True
            assert state.turns_remaining == remaining_turns
        else:
            assert state.active is False
            assert state.turns_remaining == 0


@given(
    probability=st.floats(min_value=0.0, max_value=1.0),
)
@pytest.mark.asyncio
async def test_property_39_error_handling_consistency_across_backends(
    probability: float,
) -> None:
    """
    Feature: random-model-replacement, Property 39: Streaming error handling

    For any streaming error, the error handling should be consistent regardless
    of whether the original or replacement backend is used.

    Validates: Requirements 10.4
    """
    # Create service with test configuration
    registry = create_test_registry()
    config = ReplacementConfig(
        enabled=True,
        probability=probability,
        backend_model="replacement-backend:replacement-model",
        turn_count=1,
    )

    # Use deterministic random generator
    random_value = 0.5
    service = ModelReplacementService(
        config, registry, random_generator=lambda: random_value
    )

    # Create context with streaming and error simulation
    context = create_test_context(stream=True, simulate_error=True)

    session_id = "test-session"

    # Check if replacement should trigger
    service.should_replace(session_id, context)
    expected_replace = random_value < probability

    if expected_replace:
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
    else:
        # Original backend should be used
        effective_backend, effective_model = service.get_effective_backend_model(
            session_id, "original-backend", "original-model"
        )

        assert effective_backend == "original-backend"
        assert effective_model == "original-model"

    # Complete turn with error (should work the same for both backends)
    service.complete_turn(session_id)

    # Verify state is consistent regardless of backend
    state = service.get_state(session_id)
    assert state.active is False
    assert state.turns_remaining == 0


@given(
    turn_count=st.integers(min_value=1, max_value=5),
)
@pytest.mark.asyncio
async def test_property_39_state_consistency_after_error(
    turn_count: int,
) -> None:
    """
    Feature: random-model-replacement, Property 39: Streaming error handling

    For any streaming error, the replacement state should remain consistent
    and not be corrupted by the error.

    Validates: Requirements 10.4
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

    # Create context with streaming and error simulation
    context = create_test_context(stream=True, simulate_error=True)

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
    assert state.original_backend == "original-backend"
    assert state.original_model == "original-model"
    assert state.replacement_backend == "replacement-backend"
    assert state.replacement_model == "replacement-model"

    # Simulate error during turn
    service.complete_turn(session_id)

    # Verify state is still consistent after error
    state = service.get_state(session_id)
    assert state.original_backend == "original-backend"
    assert state.original_model == "original-model"
    assert state.replacement_backend == "replacement-backend"
    assert state.replacement_model == "replacement-model"

    # Verify turn counter was updated
    if turn_count == 1:
        assert state.active is False
        assert state.turns_remaining == 0
    else:
        assert state.active is True
        assert state.turns_remaining == turn_count - 1
