"""Integration tests for full request flow with model replacement.

This module tests the complete request processing flow with model replacement,
verifying that requests reach the correct backend and responses are returned correctly.

Feature: random-model-replacement
Validates: Requirements 3.2, 3.3, 4.1
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
async def test_full_request_flow_with_replacement_active() -> None:
    """Test complete request processing with replacement active.

    When replacement is triggered, the request should be routed to the
    replacement backend and a response should be returned correctly.

    Validates: Requirements 3.2, 3.3
    """
    # Create replacement service with probability=1.0
    service = create_test_service(probability=1.0, turn_count=3)

    context = create_test_context()
    session_id = "test-session"

    # Check if replacement should trigger
    should_replace = service.should_replace(session_id, context)
    assert should_replace, "Replacement should trigger with probability=1.0"

    # Activate replacement
    await service.activate_replacement(session_id, "original-backend", "original-model")

    # Verify replacement was activated
    state = service.get_state(session_id)
    assert state.active, "Replacement should be active"
    assert state.replacement_backend == "replacement-backend"
    assert state.replacement_model == "replacement-model"
    assert state.turns_remaining == 3

    # Verify request would be routed to replacement backend
    effective_backend, effective_model = service.get_effective_backend_model(
        session_id, "original-backend", "original-model"
    )
    assert effective_backend == "replacement-backend"
    assert effective_model == "replacement-model"


@pytest.mark.asyncio
async def test_full_request_flow_without_replacement() -> None:
    """Test complete request processing without replacement.

    When replacement is not triggered, the request should be routed to the
    original backend and a response should be returned correctly.

    Validates: Requirements 3.2, 3.3
    """
    # Create replacement service with probability=0.0
    service = create_test_service(probability=0.0, turn_count=1)

    context = create_test_context()
    session_id = "test-session"

    # Check if replacement should trigger
    should_replace = service.should_replace(session_id, context)
    assert not should_replace, "Replacement should not trigger with probability=0.0"

    # Verify replacement was not activated
    state = service.get_state(session_id)
    assert not state.active, "Replacement should not be active"

    # Verify request would be routed to original backend
    effective_backend, effective_model = service.get_effective_backend_model(
        session_id, "original-backend", "original-model"
    )
    assert effective_backend == "original-backend"
    assert effective_model == "original-model"


@pytest.mark.asyncio
async def test_turn_completion_after_successful_response() -> None:
    """Test that turn counter is decremented after successful response.

    When a request completes successfully with replacement active, the turn
    counter should be decremented.

    Validates: Requirements 4.1
    """
    # Create replacement service with 3-turn window
    service = create_test_service(probability=1.0, turn_count=3)

    create_test_context()
    session_id = "test-session"

    # Activate replacement
    await service.activate_replacement(session_id, "original-backend", "original-model")

    # Verify initial state
    state = service.get_state(session_id)
    assert state.active
    assert state.turns_remaining == 3

    # Complete first turn
    service.complete_turn(session_id)
    state = service.get_state(session_id)
    assert state.active
    assert (
        state.turns_remaining == 2
    ), "Turn counter should be decremented to 2 after first turn"

    # Complete second turn
    service.complete_turn(session_id)
    state = service.get_state(session_id)
    assert state.active
    assert (
        state.turns_remaining == 1
    ), "Turn counter should be decremented to 1 after second turn"

    # Complete third turn
    service.complete_turn(session_id)
    state = service.get_state(session_id)
    assert not state.active, "Replacement should be deactivated after 3 turns"
    assert state.turns_remaining == 0


@pytest.mark.asyncio
async def test_turn_completion_consistency() -> None:
    """Test that turn counter management is consistent.

    The turn counter should be properly managed throughout the replacement
    window, ensuring consistent state transitions.

    Validates: Requirements 4.1
    """
    # Create replacement service with 2-turn window
    service = create_test_service(probability=1.0, turn_count=2)

    create_test_context()
    session_id = "test-session"

    # Activate replacement
    await service.activate_replacement(session_id, "original-backend", "original-model")

    # Verify initial state
    state = service.get_state(session_id)
    assert state.active
    assert state.turns_remaining == 2

    # Complete first turn
    service.complete_turn(session_id)
    state = service.get_state(session_id)
    assert state.active, "Replacement should still be active"
    assert state.turns_remaining == 1, "Turn counter should be decremented"

    # Complete second turn
    service.complete_turn(session_id)
    state = service.get_state(session_id)
    assert not state.active, "Replacement should be deactivated"
    assert state.turns_remaining == 0


@pytest.mark.asyncio
async def test_replacement_activation_and_routing() -> None:
    """Test that replacement activation correctly updates routing.

    When replacement is activated, subsequent routing decisions should use
    the replacement backend:model.

    Validates: Requirements 3.2, 3.3
    """
    # Create replacement service
    service = create_test_service(probability=1.0, turn_count=5)

    create_test_context()
    session_id = "test-session"

    # Before activation, should use original
    effective_backend, effective_model = service.get_effective_backend_model(
        session_id, "original-backend", "original-model"
    )
    assert effective_backend == "original-backend"
    assert effective_model == "original-model"

    # Activate replacement
    await service.activate_replacement(session_id, "original-backend", "original-model")

    # After activation, should use replacement
    effective_backend, effective_model = service.get_effective_backend_model(
        session_id, "original-backend", "original-model"
    )
    assert effective_backend == "replacement-backend"
    assert effective_model == "replacement-model"

    # Complete all turns
    for _ in range(5):
        service.complete_turn(session_id)

    # After deactivation, should use original again
    effective_backend, effective_model = service.get_effective_backend_model(
        session_id, "original-backend", "original-model"
    )
    assert effective_backend == "original-backend"
    assert effective_model == "original-model"
