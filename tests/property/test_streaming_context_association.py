"""Property-based tests for streaming context association with model replacement.

This module contains property-based tests that verify streaming context is
correctly associated with the effective backend:model.

Feature: random-model-replacement
Property 40: Streaming context association
Validates: Requirements 10.5
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
    registry.register_backend("backend-x", mock_factory)
    registry.register_backend("backend-y", mock_factory)

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
    turn_count=st.integers(min_value=1, max_value=5),
)
@pytest.mark.asyncio
async def test_property_40_streaming_context_association(
    probability: float,
    turn_count: int,
) -> None:
    """
    Feature: random-model-replacement, Property 40: Streaming context association

    For any streaming request, the streaming context must be associated with
    the effective backend:model (replacement if active, original otherwise).

    Validates: Requirements 10.5
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

        # Verify streaming context is associated with replacement
        assert effective_backend == "replacement-backend"
        assert effective_model == "replacement-model"

        # Verify state contains correct backend:model association
        state = service.get_state(session_id)
        assert state.active is True
        assert state.replacement_backend == "replacement-backend"
        assert state.replacement_model == "replacement-model"
    else:
        # Get effective backend:model
        effective_backend, effective_model = service.get_effective_backend_model(
            session_id, "original-backend", "original-model"
        )

        # Verify streaming context is associated with original
        assert effective_backend == "original-backend"
        assert effective_model == "original-model"


@given(
    turn_count=st.integers(min_value=1, max_value=5),
)
@pytest.mark.asyncio
async def test_property_40_context_association_across_turns(
    turn_count: int,
) -> None:
    """
    Feature: random-model-replacement, Property 40: Streaming context association

    For any streaming session across multiple turns, the context should remain
    associated with the correct backend:model throughout.

    Validates: Requirements 10.5
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

    # Simulate multiple turns
    for _turn in range(turn_count):
        # Get effective backend:model
        effective_backend, effective_model = service.get_effective_backend_model(
            session_id, "original-backend", "original-model"
        )

        # Verify context is associated with replacement during window
        assert effective_backend == "replacement-backend"
        assert effective_model == "replacement-model"

        # Verify state maintains correct association
        state = service.get_state(session_id)
        assert state.replacement_backend == "replacement-backend"
        assert state.replacement_model == "replacement-model"

        # Complete the turn
        service.complete_turn(session_id)

    # After all turns, context should be associated with original
    effective_backend, effective_model = service.get_effective_backend_model(
        session_id, "original-backend", "original-model"
    )
    assert effective_backend == "original-backend"
    assert effective_model == "original-model"


@given(
    backend_name=st.sampled_from(["backend-x", "backend-y"]),
    model_name=st.text(
        min_size=1,
        max_size=20,
        alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd")),
    ),
)
@pytest.mark.asyncio
async def test_property_40_context_with_different_backends(
    backend_name: str,
    model_name: str,
) -> None:
    """
    Feature: random-model-replacement, Property 40: Streaming context association

    For any replacement backend:model combination, the streaming context should
    be correctly associated with that specific backend:model.

    Validates: Requirements 10.5
    """
    # Create service with test configuration
    registry = create_test_registry()
    config = ReplacementConfig(
        enabled=True,
        probability=1.0,
        backend_model=f"{backend_name}:{model_name}",
        turn_count=1,
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

    # Get effective backend:model
    effective_backend, effective_model = service.get_effective_backend_model(
        session_id, "original-backend", "original-model"
    )

    # Verify context is associated with correct replacement backend:model
    assert effective_backend == backend_name
    assert effective_model == model_name

    # Verify state contains correct association
    state = service.get_state(session_id)
    assert state.replacement_backend == backend_name
    assert state.replacement_model == model_name


@given(
    turn_count=st.integers(min_value=1, max_value=5),
)
@pytest.mark.asyncio
async def test_property_40_context_transition_on_deactivation(
    turn_count: int,
) -> None:
    """
    Feature: random-model-replacement, Property 40: Streaming context association

    For any streaming session, when replacement is deactivated, the context
    should transition to be associated with the original backend:model.

    Validates: Requirements 10.5
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

    # Verify context is associated with replacement before deactivation
    effective_backend, effective_model = service.get_effective_backend_model(
        session_id, "original-backend", "original-model"
    )
    assert effective_backend == "replacement-backend"
    assert effective_model == "replacement-model"

    # Complete all turns to deactivate
    for _ in range(turn_count):
        service.complete_turn(session_id)

    # Verify context is now associated with original after deactivation
    effective_backend, effective_model = service.get_effective_backend_model(
        session_id, "original-backend", "original-model"
    )
    assert effective_backend == "original-backend"
    assert effective_model == "original-model"

    # Verify state reflects deactivation
    state = service.get_state(session_id)
    assert state.active is False


@given(
    probability=st.floats(min_value=0.0, max_value=1.0),
    turn_count=st.integers(min_value=1, max_value=5),
)
@pytest.mark.asyncio
async def test_property_40_context_consistency_with_state(
    probability: float,
    turn_count: int,
) -> None:
    """
    Feature: random-model-replacement, Property 40: Streaming context association

    For any streaming request, the context association must be consistent with
    the replacement state (active/inactive).

    Validates: Requirements 10.5
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

    # Create context with streaming enabled
    context = create_test_context(stream=True)

    session_id = "test-session"

    # Check if replacement should trigger
    service.should_replace(session_id, context)
    expected_replace = random_value < probability

    if expected_replace:
        # Activate replacement
        await service.activate_replacement(
            session_id, "original-backend", "original-model"
        )

        # Get state and effective backend:model
        state = service.get_state(session_id)
        effective_backend, effective_model = service.get_effective_backend_model(
            session_id, "original-backend", "original-model"
        )

        # Verify consistency: if state is active, context should use replacement
        if state.active:
            assert effective_backend == state.replacement_backend
            assert effective_model == state.replacement_model
        else:
            assert effective_backend == "original-backend"
            assert effective_model == "original-model"
    else:
        # Get state and effective backend:model
        state = service.get_state(session_id)
        effective_backend, effective_model = service.get_effective_backend_model(
            session_id, "original-backend", "original-model"
        )

        # Verify consistency: if state is inactive, context should use original
        assert state.active is False
        assert effective_backend == "original-backend"
        assert effective_model == "original-model"
