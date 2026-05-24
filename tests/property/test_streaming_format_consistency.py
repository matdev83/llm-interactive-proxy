"""Property-based tests for streaming format consistency with model replacement.

This module contains property-based tests that verify streaming format remains
consistent when using replacement models.

Feature: random-model-replacement
Property 37: Streaming format consistency
Validates: Requirements 10.2
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
    registry.register_backend("backend-a", mock_factory)
    registry.register_backend("backend-b", mock_factory)

    return registry


def create_test_context(
    stream: bool = True, format_type: str = "json"
) -> RequestContext:
    """Create a test request context with streaming and format information."""
    context = RequestContext(
        headers={},
        cookies={},
        state=None,
        app_state=None,
    )

    if context.state is None:
        context.state = {}
    context.state["stream"] = stream
    context.state["format"] = format_type

    return context


@given(
    probability=st.floats(min_value=0.0, max_value=1.0),
    turn_count=st.integers(min_value=1, max_value=5),
    format_type=st.sampled_from(["json", "text", "binary"]),
)
@pytest.mark.asyncio
async def test_property_37_streaming_format_consistency(
    probability: float,
    turn_count: int,
    format_type: str,
) -> None:
    """
    Feature: random-model-replacement, Property 37: Streaming format consistency

    For any streaming response from a replacement model, the streaming format
    must match the format used by the original backend.

    Validates: Requirements 10.2
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

    # Create context with streaming and format
    context = create_test_context(stream=True, format_type=format_type)

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

        # Verify format is preserved in context
        assert context.state is not None
        assert "format" in context.state
        assert context.state["format"] == format_type

        # The format should remain consistent throughout
        # This is ensured by the replacement service not modifying format
        assert context.state["stream"] is True
        assert context.state["format"] == format_type
    else:
        # If replacement doesn't trigger, format should still be preserved
        assert context.state is not None
        assert "format" in context.state
        assert context.state["format"] == format_type


@given(
    turn_count=st.integers(min_value=1, max_value=5),
    format_type=st.sampled_from(["json", "text", "binary"]),
)
@pytest.mark.asyncio
async def test_property_37_format_preserved_across_turns(
    turn_count: int,
    format_type: str,
) -> None:
    """
    Feature: random-model-replacement, Property 37: Streaming format consistency

    For any streaming request across multiple turns, the format should remain
    consistent throughout the replacement window.

    Validates: Requirements 10.2
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

    # Create context with streaming and format
    context = create_test_context(stream=True, format_type=format_type)

    session_id = "test-session"

    # First turn is skipped (guaranteed original model)
    service.should_replace(session_id, context)

    # Second turn should trigger replacement (probability=1.0)
    should_replace = service.should_replace(session_id, context)
    assert should_replace

    await service.activate_replacement(session_id, "original-backend", "original-model")

    # Simulate multiple turns
    for _turn in range(turn_count):
        # Verify format is preserved
        assert context.state is not None
        assert "format" in context.state
        assert context.state["format"] == format_type
        assert context.state["stream"] is True

        # Get effective backend:model
        effective_backend, effective_model = service.get_effective_backend_model(
            session_id, "original-backend", "original-model"
        )

        # Verify replacement is active
        assert effective_backend == "replacement-backend"
        assert effective_model == "replacement-model"

        # Complete the turn
        service.complete_turn(session_id)

    # After all turns, format should still be preserved
    assert context.state["format"] == format_type


@given(
    backend_name=st.sampled_from(["backend-a", "backend-b"]),
    model_name=st.text(
        min_size=1,
        max_size=20,
        alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd")),
    ),
    format_type=st.sampled_from(["json", "text", "binary"]),
)
@pytest.mark.asyncio
async def test_property_37_format_with_different_backends(
    backend_name: str,
    model_name: str,
    format_type: str,
) -> None:
    """
    Feature: random-model-replacement, Property 37: Streaming format consistency

    For any replacement backend:model combination, the streaming format should
    remain consistent with the original format.

    Validates: Requirements 10.2
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

    # Create context with streaming and format
    context = create_test_context(stream=True, format_type=format_type)

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

    # Verify replacement is active with correct backend:model
    assert effective_backend == backend_name
    assert effective_model == model_name

    # Verify format is preserved
    assert context.state is not None
    assert "format" in context.state
    assert context.state["format"] == format_type
    assert context.state["stream"] is True


@given(
    probability=st.floats(min_value=0.0, max_value=1.0),
    format_type=st.sampled_from(["json", "text", "binary"]),
)
@pytest.mark.asyncio
async def test_property_37_format_consistency_with_deactivation(
    probability: float,
    format_type: str,
) -> None:
    """
    Feature: random-model-replacement, Property 37: Streaming format consistency

    For any streaming request, the format should remain consistent even when
    replacement is deactivated.

    Validates: Requirements 10.2
    """
    # Create service with 1-turn window
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

    # Create context with streaming and format
    context = create_test_context(stream=True, format_type=format_type)

    session_id = "test-session"

    # Check if replacement should trigger
    service.should_replace(session_id, context)
    expected_replace = random_value < probability

    if expected_replace:
        # Activate replacement
        await service.activate_replacement(
            session_id, "original-backend", "original-model"
        )

        # Verify format before deactivation
        assert context.state["format"] == format_type

        # Complete turn to deactivate
        service.complete_turn(session_id)

        # Verify format after deactivation
        assert context.state["format"] == format_type

        # Get effective backend:model (should be original now)
        effective_backend, effective_model = service.get_effective_backend_model(
            session_id, "original-backend", "original-model"
        )

        assert effective_backend == "original-backend"
        assert effective_model == "original-model"

        # Format should still be preserved
        assert context.state["format"] == format_type
    else:
        # If replacement doesn't trigger, format should be preserved
        assert context.state["format"] == format_type


@given(
    turn_count=st.integers(min_value=1, max_value=3),
)
@pytest.mark.asyncio
async def test_property_37_format_not_modified_by_service(
    turn_count: int,
) -> None:
    """
    Feature: random-model-replacement, Property 37: Streaming format consistency

    For any streaming request, the replacement service must not modify the
    format information in the context.

    Validates: Requirements 10.2
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

    # Create context with streaming and format
    original_format = "json"
    context = create_test_context(stream=True, format_type=original_format)

    session_id = "test-session"

    # Store original format
    original_format_value = context.state["format"]

    # First turn is skipped (guaranteed original model)
    service.should_replace(session_id, context)

    # Second turn should trigger replacement (probability=1.0)
    should_replace = service.should_replace(session_id, context)
    assert should_replace

    await service.activate_replacement(session_id, "original-backend", "original-model")

    # Verify format was not modified
    assert context.state["format"] == original_format_value

    # Simulate turns
    for _ in range(turn_count):
        # Verify format remains unchanged
        assert context.state["format"] == original_format_value

        # Complete turn
        service.complete_turn(session_id)

    # Verify format is still unchanged after all turns
    assert context.state["format"] == original_format_value
