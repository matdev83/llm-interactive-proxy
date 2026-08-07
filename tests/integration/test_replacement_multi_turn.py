"""Integration tests for multi-turn model replacement.

This module tests that replacement persists for the configured turn count,
verifying that the counter decrements correctly and deactivation occurs after
turns expire.

Feature: random-model-replacement
Validates: Requirements 4.1, 4.2, 4.3
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


def create_test_context() -> RequestContext:
    """Helper to create a test request context."""
    return RequestContext(
        headers={},
        cookies={},
        state=None,
        app_state=None,
    )


@pytest.mark.asyncio
async def test_replacement_persists_for_configured_turns() -> None:
    """Test that replacement persists for the configured number of turns.

    When replacement is activated with a turn count of N, it should remain
    active for exactly N turns before deactivating.

    Validates: Requirements 4.1, 4.2
    """
    # Create service with 5-turn window
    turn_count = 5
    service = create_test_service(probability=1.0, turn_count=turn_count)

    context = create_test_context()
    session_id = "test-session"

    # Activate replacement
    service.should_replace(session_id, context)  # First turn skip
    should_replace = service.should_replace(session_id, context)
    assert should_replace

    await service.activate_replacement(session_id, "original-backend", "original-model")

    # Verify initial state
    state = service.get_state(session_id)
    assert state.active
    assert state.turns_remaining == turn_count

    # Process turns and verify replacement persists
    for turn in range(turn_count):
        # Verify replacement is active
        effective_backend, effective_model = service.get_effective_backend_model(
            session_id, "original-backend", "original-model"
        )
        assert effective_backend == "replacement-backend"
        assert effective_model == "replacement-model"

        # Complete the turn
        service.complete_turn(session_id)

        # Verify turn counter decremented
        state = service.get_state(session_id)
        expected_remaining = turn_count - (turn + 1)
        assert state.turns_remaining == expected_remaining

        # Verify active status
        if expected_remaining > 0:
            assert (
                state.active
            ), f"Should be active with {expected_remaining} turns remaining"
        else:
            assert not state.active, "Should be inactive after all turns complete"

    # Verify replacement is deactivated after all turns
    state = service.get_state(session_id)
    assert not state.active
    assert state.turns_remaining == 0


@pytest.mark.asyncio
async def test_counter_decrements_correctly() -> None:
    """Test that the turn counter decrements by exactly 1 per turn.

    Each completed turn should decrement the counter by exactly 1, ensuring
    accurate tracking of remaining turns.

    Validates: Requirements 4.1
    """
    # Create service with 10-turn window
    turn_count = 10
    service = create_test_service(probability=1.0, turn_count=turn_count)

    context = create_test_context()
    session_id = "test-session"

    # Activate replacement
    service.should_replace(session_id, context)  # First turn skip
    should_replace = service.should_replace(session_id, context)
    assert should_replace

    await service.activate_replacement(session_id, "original-backend", "original-model")

    # Track counter values
    counter_values = []

    # Process all turns
    for _turn in range(turn_count):
        state = service.get_state(session_id)
        counter_values.append(state.turns_remaining)
        service.complete_turn(session_id)

    # Verify counter decremented by 1 each time
    expected_values = list(range(turn_count, 0, -1))
    assert (
        counter_values == expected_values
    ), f"Expected {expected_values}, got {counter_values}"

    # Verify final state
    state = service.get_state(session_id)
    assert state.turns_remaining == 0
    assert not state.active


@pytest.mark.asyncio
async def test_deactivation_after_turns_expire() -> None:
    """Test that replacement deactivates when turn counter reaches zero.

    When the turn counter reaches zero, replacement should automatically
    deactivate and subsequent requests should use the original backend.

    Validates: Requirements 4.2, 4.3
    """
    # Create service with 3-turn window
    service = create_test_service(probability=1.0, turn_count=3)

    context = create_test_context()
    session_id = "test-session"

    # Activate replacement
    service.should_replace(session_id, context)  # First turn skip
    should_replace = service.should_replace(session_id, context)
    assert should_replace

    await service.activate_replacement(session_id, "original-backend", "original-model")

    # Complete 3 turns
    for _ in range(3):
        service.complete_turn(session_id)

    # Verify replacement is deactivated
    state = service.get_state(session_id)
    assert not state.active, "Replacement should be deactivated"
    assert state.turns_remaining == 0

    # Verify subsequent requests use original backend
    effective_backend, effective_model = service.get_effective_backend_model(
        session_id, "original-backend", "original-model"
    )
    assert effective_backend == "original-backend"
    assert effective_model == "original-model"


@pytest.mark.asyncio
async def test_single_turn_replacement() -> None:
    """Test replacement with turn_count=1.

    When turn_count is 1, replacement should activate for one turn and then
    immediately deactivate.

    Validates: Requirements 4.1, 4.2, 4.3
    """
    # Create service with 1-turn window
    service = create_test_service(probability=1.0, turn_count=1)

    context = create_test_context()
    session_id = "test-session"

    # Activate replacement
    service.should_replace(session_id, context)  # First turn skip
    should_replace = service.should_replace(session_id, context)
    assert should_replace

    await service.activate_replacement(session_id, "original-backend", "original-model")

    # Verify replacement is active
    state = service.get_state(session_id)
    assert state.active
    assert state.turns_remaining == 1

    # Verify first request uses replacement
    effective_backend, effective_model = service.get_effective_backend_model(
        session_id, "original-backend", "original-model"
    )
    assert effective_backend == "replacement-backend"
    assert effective_model == "replacement-model"

    # Complete the turn
    service.complete_turn(session_id)

    # Verify replacement is deactivated
    state = service.get_state(session_id)
    assert not state.active
    assert state.turns_remaining == 0

    # Verify second request uses original
    effective_backend, effective_model = service.get_effective_backend_model(
        session_id, "original-backend", "original-model"
    )
    assert effective_backend == "original-backend"
    assert effective_model == "original-model"


@pytest.mark.asyncio
async def test_replacement_window_with_multiple_activations() -> None:
    """Test that replacement can be activated multiple times in a session.

    After a replacement window expires, replacement should be able to activate
    again if the probability check passes.

    Validates: Requirements 4.1, 4.2, 4.3
    """
    # Create service with 2-turn window
    service = create_test_service(probability=1.0, turn_count=2)

    context = create_test_context()
    session_id = "test-session"

    # First activation
    service.should_replace(session_id, context)  # First turn skip
    should_replace = service.should_replace(session_id, context)
    assert should_replace

    await service.activate_replacement(session_id, "original-backend", "original-model")

    # Complete 2 turns
    for _ in range(2):
        service.complete_turn(session_id)

    # Verify replacement is deactivated
    state = service.get_state(session_id)
    assert not state.active

    # Second activation
    service.should_replace(session_id, context)  # Consume cool-down
    should_replace = service.should_replace(session_id, context)
    assert should_replace

    await service.activate_replacement(session_id, "original-backend", "original-model")

    # Verify replacement is active again
    state = service.get_state(session_id)
    assert state.active
    assert state.turns_remaining == 2

    # Verify replacement is used
    effective_backend, effective_model = service.get_effective_backend_model(
        session_id, "original-backend", "original-model"
    )
    assert effective_backend == "replacement-backend"
    assert effective_model == "replacement-model"


@pytest.mark.asyncio
async def test_turn_counter_does_not_go_negative() -> None:
    """Test that turn counter does not go below zero.

    Even if complete_turn is called more times than expected, the counter
    should not go negative.

    Validates: Requirements 4.1
    """
    # Create service with 2-turn window
    service = create_test_service(probability=1.0, turn_count=2)

    context = create_test_context()
    session_id = "test-session"

    # Activate replacement
    service.should_replace(session_id, context)  # First turn skip
    should_replace = service.should_replace(session_id, context)
    assert should_replace

    await service.activate_replacement(session_id, "original-backend", "original-model")

    # Complete more turns than configured
    for _ in range(5):
        service.complete_turn(session_id)

    # Verify counter is 0, not negative
    state = service.get_state(session_id)
    assert state.turns_remaining == 0
    assert not state.active


@pytest.mark.asyncio
async def test_replacement_routing_throughout_window() -> None:
    """Test that routing uses replacement backend throughout the entire window.

    For all turns in the replacement window, requests should be routed to the
    replacement backend, not the original.

    Validates: Requirements 4.1, 4.3
    """
    # Create service with 4-turn window
    service = create_test_service(probability=1.0, turn_count=4)

    context = create_test_context()
    session_id = "test-session"

    # Activate replacement
    service.should_replace(session_id, context)  # First turn skip
    should_replace = service.should_replace(session_id, context)
    assert should_replace

    await service.activate_replacement(session_id, "original-backend", "original-model")

    # Track routing decisions
    routing_decisions = []

    # Process 4 turns
    for _turn in range(4):
        effective_backend, effective_model = service.get_effective_backend_model(
            session_id, "original-backend", "original-model"
        )
        routing_decisions.append((effective_backend, effective_model))
        service.complete_turn(session_id)

    # Verify all turns used replacement
    for backend, model in routing_decisions:
        assert backend == "replacement-backend"
        assert model == "replacement-model"

    # Verify next turn uses original
    effective_backend, effective_model = service.get_effective_backend_model(
        session_id, "original-backend", "original-model"
    )
    assert effective_backend == "original-backend"
    assert effective_model == "original-model"


@pytest.mark.asyncio
async def test_long_replacement_window() -> None:
    """Test replacement with a long turn window.

    Replacement should work correctly even with large turn counts, maintaining
    accurate state throughout.

    Validates: Requirements 4.1, 4.2
    """
    # Create service with 100-turn window
    turn_count = 100
    service = create_test_service(probability=1.0, turn_count=turn_count)

    context = create_test_context()
    session_id = "test-session"

    # Activate replacement
    service.should_replace(session_id, context)  # First turn skip
    should_replace = service.should_replace(session_id, context)
    assert should_replace

    await service.activate_replacement(session_id, "original-backend", "original-model")

    # Process all turns
    for turn in range(turn_count):
        state = service.get_state(session_id)
        assert state.active
        assert state.turns_remaining == turn_count - turn

        service.complete_turn(session_id)

    # Verify final state
    state = service.get_state(session_id)
    assert not state.active
    assert state.turns_remaining == 0
