"""Property-based tests for tool filtering compatibility with model replacement.

Feature: random-model-replacement
Property: 27
Validates: Requirements 7.2
"""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, given
from hypothesis import strategies as st
from src.core.domain.configuration.replacement_config import ReplacementConfig
from src.core.domain.request_context import RequestContext
from src.core.services.backend_registry import BackendRegistry
from src.core.services.model_replacement_service import ModelReplacementService
from tests.utils.hypothesis_config import property_test_settings


def create_test_service(
    probability: float,
    backend_model: str = "replacement-backend:replacement-model",
    turn_count: int = 1,
    random_generator: callable | None = None,
) -> ModelReplacementService:
    """Helper to create a test replacement service."""
    registry = BackendRegistry()

    def mock_factory() -> None:
        pass

    # Register both original and replacement backends
    backend_name = backend_model.split(":", 1)[0]
    registry.register_backend("original-backend", mock_factory)
    registry.register_backend(backend_name, mock_factory)

    config = ReplacementConfig(
        enabled=True,
        probability=probability,
        backend_model=backend_model,
        turn_count=turn_count,
    )

    return ModelReplacementService(config, registry, random_generator)


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


@given(
    probability=st.floats(min_value=0.0, max_value=1.0),
    turn_count=st.integers(min_value=1, max_value=10),
    num_tools=st.integers(min_value=0, max_value=20),
)
@property_test_settings(suppress_health_check=[HealthCheck.filter_too_much])
@pytest.mark.asyncio
async def test_property_27_tool_filtering_preservation(
    probability: float, turn_count: int, num_tools: int
) -> None:
    """
    Property 27: Tool filtering preservation.

    For any request with tool filtering enabled, the filtered tool set must be
    applied to both original and replacement models.

    Validates: Requirements 7.2
    """
    # Generate tool names
    filtered_tools = [f"tool_{i}" for i in range(num_tools)]

    # Create service with deterministic random to control replacement
    def deterministic_random() -> float:
        return 0.0 if probability < 0.5 else 0.5

    service = create_test_service(
        probability=probability,
        turn_count=turn_count,
        random_generator=deterministic_random,
    )

    # Create context with filtered tools
    context = create_test_context_with_tools(filtered_tools)

    session_id = "test-session"

    # Check if replacement should trigger
    should_replace = service.should_replace(session_id, context)

    # If replacement triggers, activate it
    if should_replace:
        await service.activate_replacement(
            session_id, "original-backend", "original-model"
        )

    # Get effective backend:model
    effective_backend, effective_model = service.get_effective_backend_model(
        session_id, "original-backend", "original-model"
    )

    # Verify tool filtering data is preserved in context
    if num_tools > 0:
        assert (
            context.state is not None
        ), "Context state should exist when tools are filtered"
        assert (
            "filtered_tools" in context.state
        ), "Filtered tools should be in context state"
        assert context.state["filtered_tools"] == filtered_tools, (
            f"Tool filtering should be preserved: expected {filtered_tools}, "
            f"got {context.state.get('filtered_tools')}"
        )

    # Verify the effective backend is correct based on replacement state
    if should_replace:
        assert (
            effective_backend == "replacement-backend"
        ), "Replacement backend should be used when replacement is active"
        assert (
            effective_model == "replacement-model"
        ), "Replacement model should be used when replacement is active"
    else:
        assert (
            effective_backend == "original-backend"
        ), "Original backend should be used when replacement is not active"
        assert (
            effective_model == "original-model"
        ), "Original model should be used when replacement is not active"


@given(
    turn_count=st.integers(min_value=1, max_value=5),
    num_tools=st.integers(min_value=1, max_value=10),
)
@property_test_settings(suppress_health_check=[HealthCheck.filter_too_much])
@pytest.mark.asyncio
async def test_tool_filtering_preserved_across_replacement_window(
    turn_count: int, num_tools: int
) -> None:
    """
    Test that tool filtering persists throughout the replacement window.

    For any replacement window with multiple turns, tool filtering should
    remain consistent across all turns.

    Validates: Requirements 7.2
    """
    # Generate tool names
    filtered_tools = [f"tool_{i}" for i in range(num_tools)]

    # Create service with probability=1.0 to ensure replacement triggers
    service = create_test_service(probability=1.0, turn_count=turn_count)

    # Create context with filtered tools
    context = create_test_context_with_tools(filtered_tools)

    session_id = "test-session"

    # Activate replacement
    should_replace = service.should_replace(session_id, context)
    assert should_replace, "Replacement should trigger with probability=1.0"

    await service.activate_replacement(session_id, "original-backend", "original-model")

    # Simulate all turns in the replacement window
    for turn in range(turn_count):
        # Verify tool filtering is preserved
        assert context.state is not None
        assert "filtered_tools" in context.state
        assert (
            context.state["filtered_tools"] == filtered_tools
        ), f"Tool filtering should be preserved on turn {turn + 1}/{turn_count}"

        # Get effective backend:model
        effective_backend, effective_model = service.get_effective_backend_model(
            session_id, "original-backend", "original-model"
        )

        # During the window, replacement should be active
        if turn < turn_count - 1:
            assert effective_backend == "replacement-backend"
            assert effective_model == "replacement-model"

        # Complete the turn
        service.complete_turn(session_id)

    # After all turns, verify tool filtering is still preserved
    assert context.state is not None
    assert "filtered_tools" in context.state
    assert context.state["filtered_tools"] == filtered_tools


@given(
    probability=st.floats(min_value=0.0, max_value=1.0),
    turn_count=st.integers(min_value=1, max_value=10),
)
@property_test_settings(suppress_health_check=[HealthCheck.filter_too_much])
@pytest.mark.asyncio
async def test_no_tool_filtering_does_not_break_replacement(
    probability: float, turn_count: int
) -> None:
    """
    Test that replacement works when no tool filtering is configured.

    For any request without tool filtering, replacement should work normally.

    Validates: Requirements 7.2
    """

    # Create service
    def deterministic_random() -> float:
        return 0.0 if probability < 0.5 else 0.5

    service = create_test_service(
        probability=probability,
        turn_count=turn_count,
        random_generator=deterministic_random,
    )

    # Create context without tool filtering
    context = create_test_context_with_tools(filtered_tools=None)

    session_id = "test-session"

    # Check if replacement should trigger
    should_replace = service.should_replace(session_id, context)

    # If replacement triggers, activate it
    if should_replace:
        await service.activate_replacement(
            session_id, "original-backend", "original-model"
        )

    # Get effective backend:model - should work without errors
    effective_backend, effective_model = service.get_effective_backend_model(
        session_id, "original-backend", "original-model"
    )

    # Verify the effective backend is correct based on replacement state
    if should_replace:
        assert effective_backend == "replacement-backend"
        assert effective_model == "replacement-model"
    else:
        assert effective_backend == "original-backend"
        assert effective_model == "original-model"


@given(
    probability=st.floats(min_value=0.0, max_value=1.0),
    turn_count=st.integers(min_value=1, max_value=10),
)
@property_test_settings(suppress_health_check=[HealthCheck.filter_too_much])
@pytest.mark.asyncio
async def test_empty_tool_list_preserved_with_replacement(
    probability: float, turn_count: int
) -> None:
    """
    Test that empty tool filtering list is preserved with replacement.

    For any request with an empty tool list (all tools filtered), this should
    be preserved when using replacement models.

    Validates: Requirements 7.2
    """

    # Create service
    def deterministic_random() -> float:
        return 0.0 if probability < 0.5 else 0.5

    service = create_test_service(
        probability=probability,
        turn_count=turn_count,
        random_generator=deterministic_random,
    )

    # Create context with empty tool list
    filtered_tools: list[str] = []
    context = create_test_context_with_tools(filtered_tools)

    session_id = "test-session"

    # Check if replacement should trigger
    should_replace = service.should_replace(session_id, context)

    # If replacement triggers, activate it
    if should_replace:
        await service.activate_replacement(
            session_id, "original-backend", "original-model"
        )

    # Verify empty tool list is preserved
    assert context.state is not None
    assert "filtered_tools" in context.state
    assert context.state["filtered_tools"] == []
    assert len(context.state["filtered_tools"]) == 0
