"""Property-based tests for usage attribution compatibility with model replacement.

Feature: random-model-replacement
Property: 29
Validates: Requirements 7.4
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


@given(
    probability=st.floats(min_value=0.0, max_value=1.0),
    turn_count=st.integers(min_value=1, max_value=10),
    prompt_tokens=st.integers(min_value=1, max_value=10000),
    completion_tokens=st.integers(min_value=1, max_value=10000),
)
@property_test_settings(suppress_health_check=[HealthCheck.filter_too_much])
@pytest.mark.asyncio
async def test_property_29_usage_attribution_accuracy(
    probability: float,
    turn_count: int,
    prompt_tokens: int,
    completion_tokens: int,
) -> None:
    """
    Property 29: Usage attribution accuracy.

    For any request, usage accounting must attribute costs to the actual
    backend:model used (replacement if active, original otherwise).

    Validates: Requirements 7.4
    """

    # Create service with deterministic random to control replacement
    def deterministic_random() -> float:
        return 0.0 if probability < 0.5 else 0.5

    service = create_test_service(
        probability=probability,
        turn_count=turn_count,
        random_generator=deterministic_random,
    )

    # Create context with usage tracking
    context = create_test_context_with_usage_tracking()

    session_id = "test-session"

    # First turn is skipped (guaranteed original model)
    service.should_replace(session_id, context)

    # Second turn checks probability
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

    # Simulate recording usage
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

    # Verify usage was attributed correctly
    assert len(context.state["usage_records"]) == 1
    usage_record = context.state["usage_records"][0]

    # Verify token counts are preserved
    assert usage_record["prompt_tokens"] == prompt_tokens
    assert usage_record["completion_tokens"] == completion_tokens
    assert usage_record["total_tokens"] == total_tokens

    # Verify backend:model attribution
    if should_replace:
        assert (
            usage_record["backend"] == "replacement-backend"
        ), "Usage should be attributed to replacement backend when replacement is active"
        assert (
            usage_record["model"] == "replacement-model"
        ), "Usage should be attributed to replacement model when replacement is active"
    else:
        assert (
            usage_record["backend"] == "original-backend"
        ), "Usage should be attributed to original backend when replacement is not active"
        assert (
            usage_record["model"] == "original-model"
        ), "Usage should be attributed to original model when replacement is not active"


@given(
    turn_count=st.integers(min_value=1, max_value=5),
    num_turns=st.integers(min_value=1, max_value=10),
)
@property_test_settings(suppress_health_check=[HealthCheck.filter_too_much])
@pytest.mark.asyncio
async def test_usage_attribution_across_replacement_window(
    turn_count: int, num_turns: int
) -> None:
    """
    Test that usage attribution is correct throughout replacement window.

    For any replacement window with multiple turns, usage should be correctly
    attributed to the replacement backend for all turns in the window, and to
    the original backend after the window expires.

    Validates: Requirements 7.4
    """
    # Create service with probability=1.0 to ensure replacement triggers
    service = create_test_service(probability=1.0, turn_count=turn_count)

    # Create context with usage tracking
    context = create_test_context_with_usage_tracking()

    session_id = "test-session"

    # First turn is skipped (guaranteed original model)
    service.should_replace(session_id, context)

    # Second turn should trigger replacement (probability=1.0)
    should_replace = service.should_replace(session_id, context)
    assert should_replace

    await service.activate_replacement(session_id, "original-backend", "original-model")

    # Simulate multiple turns
    for turn in range(num_turns):
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
                "total_tokens": 100,
            }
        )

        # Complete the turn
        service.complete_turn(session_id)

    # Verify all usage records were created
    assert len(context.state["usage_records"]) == num_turns

    # Verify attribution for each turn
    for i, record in enumerate(context.state["usage_records"]):
        if i < turn_count:
            # Within replacement window - should use replacement
            assert (
                record["backend"] == "replacement-backend"
            ), f"Turn {i + 1} should use replacement backend (within window of {turn_count})"
            assert record["model"] == "replacement-model"
        else:
            # After replacement window - should use original
            assert (
                record["backend"] == "original-backend"
            ), f"Turn {i + 1} should use original backend (after window of {turn_count})"
            assert record["model"] == "original-model"


@given(
    probability=st.floats(min_value=0.0, max_value=1.0),
    turn_count=st.integers(min_value=1, max_value=10),
)
@property_test_settings(suppress_health_check=[HealthCheck.filter_too_much])
@pytest.mark.asyncio
async def test_usage_attribution_without_tracking(
    probability: float, turn_count: int
) -> None:
    """
    Test that replacement works when usage tracking is not configured.

    For any request without usage tracking, replacement should work normally.

    Validates: Requirements 7.4
    """

    # Create service
    def deterministic_random() -> float:
        return 0.0 if probability < 0.5 else 0.5

    service = create_test_service(
        probability=probability,
        turn_count=turn_count,
        random_generator=deterministic_random,
    )

    # Create context without usage tracking
    context = RequestContext(
        headers={},
        cookies={},
        state=None,
        app_state=None,
    )

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
    num_requests=st.integers(min_value=1, max_value=5),
)
@property_test_settings(suppress_health_check=[HealthCheck.filter_too_much])
@pytest.mark.asyncio
async def test_usage_attribution_consistency(
    probability: float, turn_count: int, num_requests: int
) -> None:
    """
    Test that usage attribution is consistent across multiple requests.

    For any sequence of requests, usage attribution should consistently match
    the effective backend:model for each request.

    Validates: Requirements 7.4
    """

    # Create service
    def deterministic_random() -> float:
        return 0.0 if probability < 0.5 else 0.5

    service = create_test_service(
        probability=probability,
        turn_count=turn_count,
        random_generator=deterministic_random,
    )

    # Create context with usage tracking
    context = create_test_context_with_usage_tracking()

    session_id = "test-session"

    # Process multiple requests
    for request_num in range(num_requests):
        # Check if replacement should trigger
        should_replace = service.should_replace(session_id, context)

        # If replacement triggers and not already active, activate it
        state = service.get_state(session_id)
        if should_replace and not state.active:
            await service.activate_replacement(
                session_id, "original-backend", "original-model"
            )

        # Get effective backend:model
        effective_backend, effective_model = service.get_effective_backend_model(
            session_id, "original-backend", "original-model"
        )

        # Record usage
        context.state["usage_records"].append(
            {
                "backend": effective_backend,
                "model": effective_model,
                "request_num": request_num + 1,
                "total_tokens": 100,
            }
        )

        # Complete the turn
        service.complete_turn(session_id)

    # Verify all usage records have consistent attribution
    for _i, record in enumerate(context.state["usage_records"]):
        # Each record should have valid backend:model
        assert record["backend"] in ["original-backend", "replacement-backend"]
        assert record["model"] in ["original-model", "replacement-model"]

        # Backend and model should match
        if record["backend"] == "replacement-backend":
            assert record["model"] == "replacement-model"
        else:
            assert record["model"] == "original-model"
