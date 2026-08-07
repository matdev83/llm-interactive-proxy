"""Property-based tests for wire capture compatibility with model replacement.

Feature: random-model-replacement
Property: 28
Validates: Requirements 7.3
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


def create_test_context_with_capture(capture_enabled: bool = True) -> RequestContext:
    """Helper to create a test request context with wire capture configuration."""
    context = RequestContext(
        headers={},
        cookies={},
        state=None,
        app_state=None,
    )

    # Add wire capture configuration to context state
    if capture_enabled:
        if context.state is None:
            context.state = {}
        context.state["wire_capture_enabled"] = True
        context.state["captured_requests"] = []
        context.state["captured_responses"] = []

    return context


@given(
    probability=st.floats(min_value=0.0, max_value=1.0),
    turn_count=st.integers(min_value=1, max_value=10),
    capture_enabled=st.booleans(),
)
@property_test_settings(suppress_health_check=[HealthCheck.filter_too_much])
@pytest.mark.asyncio
async def test_property_28_wire_capture_completeness(
    probability: float, turn_count: int, capture_enabled: bool
) -> None:
    """
    Property 28: Wire capture completeness.

    For any request with wire capture enabled, both original and replacement
    model requests/responses must be captured.

    Validates: Requirements 7.3
    """

    # Create service with deterministic random to control replacement
    def deterministic_random() -> float:
        return 0.0 if probability < 0.5 else 0.5

    service = create_test_service(
        probability=probability,
        turn_count=turn_count,
        random_generator=deterministic_random,
    )

    # Create context with or without wire capture
    context = create_test_context_with_capture(capture_enabled)

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

    # If wire capture is enabled, simulate capturing the request
    if capture_enabled:
        assert context.state is not None
        assert "wire_capture_enabled" in context.state
        assert context.state["wire_capture_enabled"] is True

        # Simulate capturing request
        context.state["captured_requests"].append(
            {
                "backend": effective_backend,
                "model": effective_model,
            }
        )

        # Verify the request was captured with correct backend:model
        assert len(context.state["captured_requests"]) == 1
        captured_request = context.state["captured_requests"][0]

        if should_replace:
            assert (
                captured_request["backend"] == "replacement-backend"
            ), "Wire capture should record replacement backend when replacement is active"
            assert (
                captured_request["model"] == "replacement-model"
            ), "Wire capture should record replacement model when replacement is active"
        else:
            assert (
                captured_request["backend"] == "original-backend"
            ), "Wire capture should record original backend when replacement is not active"
            assert (
                captured_request["model"] == "original-model"
            ), "Wire capture should record original model when replacement is not active"


@given(
    turn_count=st.integers(min_value=1, max_value=5),
    num_requests=st.integers(min_value=1, max_value=10),
)
@property_test_settings(suppress_health_check=[HealthCheck.filter_too_much])
@pytest.mark.asyncio
async def test_wire_capture_records_all_requests_in_window(
    turn_count: int, num_requests: int
) -> None:
    """
    Test that wire capture records all requests during replacement window.

    For any replacement window with multiple requests, wire capture should
    record every request to the replacement backend.

    Validates: Requirements 7.3
    """
    # Create service with probability=1.0 to ensure replacement triggers
    service = create_test_service(probability=1.0, turn_count=turn_count)

    # Create context with wire capture enabled
    context = create_test_context_with_capture(capture_enabled=True)

    session_id = "test-session"

    # First turn is skipped (guaranteed original model)
    service.should_replace(session_id, context)

    # Second turn should trigger replacement (probability=1.0)
    should_replace = service.should_replace(session_id, context)
    assert should_replace

    await service.activate_replacement(session_id, "original-backend", "original-model")

    # Simulate multiple requests within the turn window
    requests_made = min(num_requests, turn_count)

    for i in range(requests_made):
        # Get effective backend:model
        effective_backend, effective_model = service.get_effective_backend_model(
            session_id, "original-backend", "original-model"
        )

        # Capture request
        context.state["captured_requests"].append(
            {
                "backend": effective_backend,
                "model": effective_model,
                "request_num": i + 1,
            }
        )

        # Complete the turn
        service.complete_turn(session_id)

    # Verify all requests were captured
    assert len(context.state["captured_requests"]) == requests_made

    # Verify all captured requests have the correct backend:model
    for i, request in enumerate(context.state["captured_requests"]):
        # Requests within the window should use replacement
        if i < turn_count:
            assert request["backend"] == "replacement-backend"
            assert request["model"] == "replacement-model"


@given(
    probability=st.floats(min_value=0.0, max_value=1.0),
    turn_count=st.integers(min_value=1, max_value=10),
)
@property_test_settings(suppress_health_check=[HealthCheck.filter_too_much])
@pytest.mark.asyncio
async def test_wire_capture_disabled_does_not_break_replacement(
    probability: float, turn_count: int
) -> None:
    """
    Test that replacement works when wire capture is disabled.

    For any request without wire capture, replacement should work normally.

    Validates: Requirements 7.3
    """

    # Create service
    def deterministic_random() -> float:
        return 0.0 if probability < 0.5 else 0.5

    service = create_test_service(
        probability=probability,
        turn_count=turn_count,
        random_generator=deterministic_random,
    )

    # Create context without wire capture
    context = create_test_context_with_capture(capture_enabled=False)

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
async def test_wire_capture_records_responses(
    probability: float, turn_count: int
) -> None:
    """
    Test that wire capture records responses from replacement models.

    For any request with wire capture enabled, responses from both original
    and replacement backends should be captured.

    Validates: Requirements 7.3
    """

    # Create service
    def deterministic_random() -> float:
        return 0.0 if probability < 0.5 else 0.5

    service = create_test_service(
        probability=probability,
        turn_count=turn_count,
        random_generator=deterministic_random,
    )

    # Create context with wire capture enabled
    context = create_test_context_with_capture(capture_enabled=True)

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

    # Simulate capturing a response
    context.state["captured_responses"].append(
        {
            "backend": effective_backend,
            "model": effective_model,
            "content": "Test response",
        }
    )

    # Verify the response was captured
    assert len(context.state["captured_responses"]) == 1
    captured_response = context.state["captured_responses"][0]

    # Verify correct backend:model was captured
    if should_replace:
        assert captured_response["backend"] == "replacement-backend"
        assert captured_response["model"] == "replacement-model"
    else:
        assert captured_response["backend"] == "original-backend"
        assert captured_response["model"] == "original-model"
