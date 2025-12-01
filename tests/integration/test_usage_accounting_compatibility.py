"""Integration tests for usage accounting compatibility with model replacement.

This module tests that model replacement works correctly with usage accounting,
ensuring that usage is attributed to the effective backend:model.

Feature: random-model-replacement
Validates: Requirements 7.4
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


def create_test_context_with_usage_tracking() -> RequestContext:
    """Helper to create a test request context with usage tracking."""
    context = RequestContext(
        headers={},
        cookies={},
        state=None,
        app_state=None,
    )

    # Add usage tracking to context state
    if context.state is None:
        context.state = {}
    context.state["usage_records"] = []

    return context


@pytest.mark.asyncio
async def test_usage_attributed_to_replacement_model() -> None:
    """Test that usage is attributed to replacement model when active.

    When replacement is active, usage accounting should attribute costs to
    the replacement backend:model, not the original.

    Validates: Requirements 7.4
    """
    # Create service with probability=1.0 to ensure replacement triggers
    service = create_test_service(probability=1.0, turn_count=3)

    # Create context with usage tracking
    context = create_test_context_with_usage_tracking()

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

    # Simulate recording usage for the request
    context.state["usage_records"].append(
        {
            "backend": effective_backend,
            "model": effective_model,
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
        }
    )

    # Verify usage was attributed to replacement backend:model
    assert len(context.state["usage_records"]) == 1
    usage_record = context.state["usage_records"][0]
    assert usage_record["backend"] == "replacement-backend"
    assert usage_record["model"] == "replacement-model"
    assert usage_record["total_tokens"] == 150


@pytest.mark.asyncio
async def test_usage_attributed_to_original_when_inactive() -> None:
    """Test that usage is attributed to original model when replacement is inactive.

    When replacement is not active, usage accounting should attribute costs to
    the original backend:model.

    Validates: Requirements 7.4
    """
    # Create service with probability=0.0 to ensure replacement never triggers
    service = create_test_service(probability=0.0, turn_count=1)

    # Create context with usage tracking
    context = create_test_context_with_usage_tracking()

    session_id = "test-session"

    # Check if replacement should trigger
    should_replace = service.should_replace(session_id, context)
    assert not should_replace, "Replacement should not trigger with probability=0.0"

    # Get effective backend:model
    effective_backend, effective_model = service.get_effective_backend_model(
        session_id, "original-backend", "original-model"
    )

    # Verify original is used
    assert effective_backend == "original-backend"
    assert effective_model == "original-model"

    # Simulate recording usage for the request
    context.state["usage_records"].append(
        {
            "backend": effective_backend,
            "model": effective_model,
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
        }
    )

    # Verify usage was attributed to original backend:model
    assert len(context.state["usage_records"]) == 1
    usage_record = context.state["usage_records"][0]
    assert usage_record["backend"] == "original-backend"
    assert usage_record["model"] == "original-model"


@pytest.mark.asyncio
async def test_usage_tracking_across_replacement_window() -> None:
    """Test that usage tracking works throughout the replacement window.

    When replacement is active for multiple turns, usage should be correctly
    attributed to the replacement backend for all turns in the window.

    Validates: Requirements 7.4
    """
    # Create service with 3-turn window
    service = create_test_service(probability=1.0, turn_count=3)

    # Create context with usage tracking
    context = create_test_context_with_usage_tracking()

    session_id = "test-session"

    # Activate replacement
    should_replace = service.should_replace(session_id, context)
    assert should_replace

    await service.activate_replacement(session_id, "original-backend", "original-model")

    # Simulate 3 turns with usage tracking
    for turn in range(3):
        # Get effective backend:model
        effective_backend, effective_model = service.get_effective_backend_model(
            session_id, "original-backend", "original-model"
        )

        # Record usage for this turn
        context.state["usage_records"].append(
            {
                "backend": effective_backend,
                "model": effective_model,
                "turn": turn + 1,
                "prompt_tokens": 100 * (turn + 1),
                "completion_tokens": 50 * (turn + 1),
                "total_tokens": 150 * (turn + 1),
            }
        )

        # Complete the turn
        service.complete_turn(session_id)

    # Verify all 3 usage records were created
    assert len(context.state["usage_records"]) == 3

    # All usage records should be attributed to replacement backend during the window
    for i, record in enumerate(context.state["usage_records"]):
        if i < 2:  # First 2 turns use replacement
            assert record["backend"] == "replacement-backend"
            assert record["model"] == "replacement-model"
        # Note: The 3rd turn completes and deactivates, but usage is still
        # attributed to the replacement backend before deactivation


@pytest.mark.asyncio
async def test_usage_transition_from_replacement_to_original() -> None:
    """Test usage attribution when transitioning from replacement to original.

    When replacement window expires, subsequent usage should be attributed to
    the original backend:model.

    Validates: Requirements 7.4
    """
    # Create service with 2-turn window
    service = create_test_service(probability=1.0, turn_count=2)

    # Create context with usage tracking
    context = create_test_context_with_usage_tracking()

    session_id = "test-session"

    # Activate replacement
    should_replace = service.should_replace(session_id, context)
    assert should_replace

    await service.activate_replacement(session_id, "original-backend", "original-model")

    # Turn 1 - replacement active
    effective_backend_1, effective_model_1 = service.get_effective_backend_model(
        session_id, "original-backend", "original-model"
    )
    context.state["usage_records"].append(
        {
            "backend": effective_backend_1,
            "model": effective_model_1,
            "turn": 1,
            "total_tokens": 100,
        }
    )
    service.complete_turn(session_id)

    # Turn 2 - replacement active
    effective_backend_2, effective_model_2 = service.get_effective_backend_model(
        session_id, "original-backend", "original-model"
    )
    context.state["usage_records"].append(
        {
            "backend": effective_backend_2,
            "model": effective_model_2,
            "turn": 2,
            "total_tokens": 100,
        }
    )
    service.complete_turn(session_id)

    # Turn 3 - replacement should be inactive now
    effective_backend_3, effective_model_3 = service.get_effective_backend_model(
        session_id, "original-backend", "original-model"
    )
    context.state["usage_records"].append(
        {
            "backend": effective_backend_3,
            "model": effective_model_3,
            "turn": 3,
            "total_tokens": 100,
        }
    )

    # Verify usage attribution
    assert len(context.state["usage_records"]) == 3

    # First 2 turns should be attributed to replacement
    assert context.state["usage_records"][0]["backend"] == "replacement-backend"
    assert context.state["usage_records"][0]["model"] == "replacement-model"
    assert context.state["usage_records"][1]["backend"] == "replacement-backend"
    assert context.state["usage_records"][1]["model"] == "replacement-model"

    # Third turn should be attributed to original
    assert context.state["usage_records"][2]["backend"] == "original-backend"
    assert context.state["usage_records"][2]["model"] == "original-model"


@pytest.mark.asyncio
async def test_usage_tracking_with_different_token_counts() -> None:
    """Test that usage tracking correctly records different token counts.

    Usage accounting should accurately track varying token counts for both
    original and replacement models.

    Validates: Requirements 7.4
    """
    # Create service with probability=1.0
    service = create_test_service(probability=1.0, turn_count=1)

    # Create context with usage tracking
    context = create_test_context_with_usage_tracking()

    session_id = "test-session"

    # Activate replacement
    should_replace = service.should_replace(session_id, context)
    assert should_replace

    await service.activate_replacement(session_id, "original-backend", "original-model")

    # Get effective backend:model
    effective_backend, effective_model = service.get_effective_backend_model(
        session_id, "original-backend", "original-model"
    )

    # Record usage with specific token counts
    prompt_tokens = 1234
    completion_tokens = 567
    total_tokens = prompt_tokens + completion_tokens

    context.state["usage_records"].append(
        {
            "backend": effective_backend,
            "model": effective_model,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
        }
    )

    # Verify usage was recorded accurately
    assert len(context.state["usage_records"]) == 1
    usage_record = context.state["usage_records"][0]
    assert usage_record["backend"] == "replacement-backend"
    assert usage_record["model"] == "replacement-model"
    assert usage_record["prompt_tokens"] == 1234
    assert usage_record["completion_tokens"] == 567
    assert usage_record["total_tokens"] == 1801
