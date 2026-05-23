"""Integration tests for tool filtering compatibility with model replacement.

This module tests that model replacement works correctly with tool filtering,
ensuring that filtered tools are properly passed to replacement backends.

Feature: random-model-replacement
Validates: Requirements 7.2
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


def create_test_context_with_tools(
    filtered_tools: list[str] | None = None,
) -> RequestContext:
    """Helper to create a test request context with tool filtering data."""
    context = RequestContext(
        headers={},
        cookies={},
        state=None,
        app_state=None,
    )

    # Add tool filtering data to context state if provided
    if filtered_tools is not None:
        if context.state is None:
            context.state = {}
        context.state["filtered_tools"] = filtered_tools

    return context


@pytest.mark.asyncio
async def test_tool_filtering_preserved_with_replacement() -> None:
    """Test that tool filtering is applied to replacement models.

    When replacement is active and tool filtering is configured, the filtered
    tool set should be preserved and applied to the replacement backend.

    Validates: Requirements 7.2
    """
    # Create service with probability=1.0 to ensure replacement triggers
    service = create_test_service(probability=1.0, turn_count=3)

    # Create context with filtered tools
    filtered_tools = ["tool1", "tool2", "tool3"]
    context = create_test_context_with_tools(filtered_tools)

    session_id = "test-session"

    # Check if replacement should trigger
    service.should_replace(session_id, context)  # First turn skip
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

    # Verify tool filtering data is still in context
    assert context.state is not None
    assert "filtered_tools" in context.state
    assert context.state["filtered_tools"] == filtered_tools


@pytest.mark.asyncio
async def test_tool_filtering_preserved_across_turns() -> None:
    """Test that tool filtering persists across multiple replacement turns.

    When replacement is active for multiple turns, tool filtering should
    remain consistent throughout the replacement window.

    Validates: Requirements 7.2
    """
    # Create service with 3-turn window
    service = create_test_service(probability=1.0, turn_count=3)

    # Create context with filtered tools
    filtered_tools = ["tool_a", "tool_b"]
    context = create_test_context_with_tools(filtered_tools)

    session_id = "test-session"

    # Activate replacement
    service.should_replace(session_id, context)  # First turn skip
    should_replace = service.should_replace(session_id, context)
    assert should_replace

    await service.activate_replacement(session_id, "original-backend", "original-model")

    # Simulate 3 turns
    for turn in range(3):
        # Verify replacement is active
        effective_backend, effective_model = service.get_effective_backend_model(
            session_id, "original-backend", "original-model"
        )

        if turn < 2:  # First 2 turns should use replacement
            assert effective_backend == "replacement-backend"
            assert effective_model == "replacement-model"
        else:  # Last turn completes and deactivates
            # After complete_turn is called, it should deactivate
            pass

        # Verify tool filtering is still present
        assert context.state is not None
        assert "filtered_tools" in context.state
        assert context.state["filtered_tools"] == filtered_tools

        # Complete the turn
        service.complete_turn(session_id)

    # After all turns, replacement should be inactive
    effective_backend, effective_model = service.get_effective_backend_model(
        session_id, "original-backend", "original-model"
    )
    assert effective_backend == "original-backend"
    assert effective_model == "original-model"

    # Tool filtering should still be preserved
    assert context.state is not None
    assert "filtered_tools" in context.state
    assert context.state["filtered_tools"] == filtered_tools


@pytest.mark.asyncio
async def test_no_tool_filtering_with_replacement() -> None:
    """Test that replacement works when no tool filtering is configured.

    When tool filtering is not configured, replacement should work normally
    without requiring tool filtering data.

    Validates: Requirements 7.2
    """
    # Create service with probability=1.0
    service = create_test_service(probability=1.0, turn_count=1)

    # Create context without tool filtering
    context = create_test_context_with_tools(filtered_tools=None)

    session_id = "test-session"

    # Check if replacement should trigger
    service.should_replace(session_id, context)  # First turn skip
    should_replace = service.should_replace(session_id, context)
    assert should_replace

    # Activate replacement
    await service.activate_replacement(session_id, "original-backend", "original-model")

    # Get effective backend:model
    effective_backend, effective_model = service.get_effective_backend_model(
        session_id, "original-backend", "original-model"
    )

    # Verify replacement is active
    assert effective_backend == "replacement-backend"
    assert effective_model == "replacement-model"


@pytest.mark.asyncio
async def test_empty_tool_list_preserved() -> None:
    """Test that empty tool filtering list is preserved with replacement.

    When tool filtering is configured with an empty list (all tools filtered),
    this should be preserved when using replacement models.

    Validates: Requirements 7.2
    """
    # Create service with probability=1.0
    service = create_test_service(probability=1.0, turn_count=1)

    # Create context with empty tool list
    filtered_tools: list[str] = []
    context = create_test_context_with_tools(filtered_tools)

    session_id = "test-session"

    # Activate replacement
    service.should_replace(session_id, context)  # First turn skip
    should_replace = service.should_replace(session_id, context)
    assert should_replace

    await service.activate_replacement(session_id, "original-backend", "original-model")

    # Verify replacement is active
    effective_backend, effective_model = service.get_effective_backend_model(
        session_id, "original-backend", "original-model"
    )
    assert effective_backend == "replacement-backend"
    assert effective_model == "replacement-model"

    # Verify empty tool list is preserved
    assert context.state is not None
    assert "filtered_tools" in context.state
    assert context.state["filtered_tools"] == []
    assert len(context.state["filtered_tools"]) == 0
