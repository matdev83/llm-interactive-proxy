"""Property-based tests for opt-out header functionality.

Feature: random-model-replacement
Properties: 31, 33, 34
Validates: Requirements 9.1, 9.3, 9.4
"""

from __future__ import annotations

from hypothesis import HealthCheck, given
from hypothesis import strategies as st
from src.core.domain.configuration.replacement_config import ReplacementConfig
from src.core.domain.request_context import RequestContext
from src.core.services.backend_registry import BackendRegistry
from src.core.services.model_replacement_service import ModelReplacementService
from tests.utils.hypothesis_config import property_test_settings


def create_test_service(
    probability: float = 1.0,
    backend_model: str = "test-backend:test-model",
    turn_count: int = 1,
    random_generator: callable | None = None,
) -> ModelReplacementService:
    """Helper to create a test replacement service."""
    registry = BackendRegistry()

    def mock_factory() -> None:
        pass

    # Register the test backend
    backend_name = backend_model.split(":", 1)[0]
    registry.register_backend(backend_name, mock_factory)

    config = ReplacementConfig(
        enabled=True,
        probability=probability,
        backend_model=backend_model,
        turn_count=turn_count,
    )

    return ModelReplacementService(config, registry, random_generator)


def create_test_context(headers: dict[str, str] | None = None) -> RequestContext:
    """Helper to create a test request context with optional headers."""
    return RequestContext(
        headers=headers or {},
        cookies={},
        state=None,
        app_state=None,
    )


@given(
    probability=st.floats(min_value=0.0, max_value=1.0),
    turn_count=st.integers(min_value=1, max_value=100),
    header_value=st.sampled_from(["true", "True", "TRUE", "TrUe"]),
)
@property_test_settings(suppress_health_check=[HealthCheck.filter_too_much])
def test_property_31_header_based_opt_out(
    probability: float, turn_count: int, header_value: str
) -> None:
    """
    Property 31: Header-based opt-out.

    For any request with header "X-Disable-Replacement: true", replacement
    logic must be skipped and the original backend:model must be used.

    Feature: random-model-replacement, Property 31
    Validates: Requirements 9.1
    """
    # Create service with high probability to ensure it would normally trigger
    service = create_test_service(
        probability=1.0,  # Would always trigger without opt-out
        turn_count=turn_count,
    )

    # Create context with opt-out header (case-insensitive)
    context = create_test_context(headers={"x-disable-replacement": header_value})

    # Check that replacement is skipped
    session_id = "test-session"
    should_replace = service.should_replace(session_id, context)

    assert not should_replace, (
        f"Replacement triggered despite opt-out header "
        f"(header value: {header_value})"
    )


@given(
    probability=st.floats(min_value=0.0, max_value=1.0),
    turn_count=st.integers(min_value=1, max_value=100),
    header_key_variant=st.sampled_from(
        [
            "x-disable-replacement",
            "X-Disable-Replacement",
            "X-DISABLE-REPLACEMENT",
            "x-DISABLE-replacement",
        ]
    ),
)
@property_test_settings(suppress_health_check=[HealthCheck.filter_too_much])
def test_property_31_header_case_insensitive(
    probability: float, turn_count: int, header_key_variant: str
) -> None:
    """
    Property 31: Header-based opt-out (case-insensitive header name).

    For any request with header "X-Disable-Replacement: true" (in any case),
    replacement logic must be skipped.

    Feature: random-model-replacement, Property 31
    Validates: Requirements 9.1
    """
    # Create service with probability=1.0 to ensure it would trigger
    service = create_test_service(probability=1.0, turn_count=turn_count)

    # Create context with opt-out header (various case combinations)
    context = create_test_context(headers={header_key_variant: "true"})

    # Check that replacement is skipped
    session_id = "test-session"
    should_replace = service.should_replace(session_id, context)

    assert not should_replace, (
        f"Replacement triggered despite opt-out header "
        f"(header key: {header_key_variant})"
    )


@given(
    probability=st.floats(min_value=0.0, max_value=1.0),
    turn_count=st.integers(min_value=1, max_value=100),
    non_opt_out_value=st.sampled_from(["false", "False", "0", "no", "", "yes", "1"]),
)
@property_test_settings(suppress_health_check=[HealthCheck.filter_too_much])
def test_property_31_header_non_true_values(
    probability: float, turn_count: int, non_opt_out_value: str
) -> None:
    """
    Property 31: Header-based opt-out (only "true" triggers opt-out).

    For any request with header "X-Disable-Replacement" set to a value other
    than "true" (case-insensitive), replacement logic should proceed normally.

    Feature: random-model-replacement, Property 31
    Validates: Requirements 9.1
    """
    # Create service with probability=1.0
    service = create_test_service(probability=1.0, turn_count=turn_count)

    # Create context with non-opt-out header value
    context = create_test_context(headers={"x-disable-replacement": non_opt_out_value})

    session_id = "test-session"

    # First turn is skipped (guaranteed original model)
    service.should_replace(session_id, context)

    # Second turn should trigger with probability=1.0
    should_replace = service.should_replace(session_id, context)

    # With probability=1.0, should always trigger unless opt-out
    assert should_replace, (
        f"Replacement did not trigger with probability=1.0 and "
        f"non-opt-out header value: {non_opt_out_value}"
    )


@given(
    probability=st.floats(min_value=0.0, max_value=1.0),
    turn_count=st.integers(min_value=1, max_value=100),
)
@property_test_settings(
    max_examples=15,  # Reduced from default for performance
    suppress_health_check=[HealthCheck.filter_too_much],
)
def test_property_33_opt_out_logging(probability: float, turn_count: int) -> None:
    """
    Property 33: Opt-out logging.

    For any request where replacement is skipped due to opt-out, a DEBUG log
    message must be emitted indicating replacement was skipped.

    Feature: random-model-replacement, Property 33
    Validates: Requirements 9.3
    """
    from unittest.mock import patch

    # Create service
    service = create_test_service(probability=probability, turn_count=turn_count)

    # Create context with opt-out header
    context = create_test_context(headers={"x-disable-replacement": "true"})

    # Mock the logger to capture log calls
    with patch("src.core.services.model_replacement_service.logger") as mock_logger:
        session_id = "test-session"
        service.should_replace(session_id, context)

        # Verify DEBUG log was called with opt-out message
        debug_calls = list(mock_logger.debug.call_args_list)

        # Should have at least one DEBUG log about opt-out
        opt_out_logs = [
            call
            for call in debug_calls
            if len(call[0]) > 0
            and "disabled by header" in str(call[0][0]).lower()
            and session_id in str(call[0][0])
        ]

        assert len(opt_out_logs) > 0, (
            "No DEBUG log emitted for opt-out header. "
            f"Found DEBUG calls: {[str(call) for call in debug_calls]}"
        )


@given(
    original_backend=st.text(
        alphabet=st.characters(min_codepoint=97, max_codepoint=122),
        min_size=3,
        max_size=20,
    ),
    original_model=st.text(
        alphabet=st.characters(min_codepoint=97, max_codepoint=122),
        min_size=3,
        max_size=20,
    ),
    turn_count=st.integers(min_value=1, max_value=100),
)
@property_test_settings(suppress_health_check=[HealthCheck.filter_too_much])
def test_property_34_opt_out_routing_guarantee(
    original_backend: str, original_model: str, turn_count: int
) -> None:
    """
    Property 34: Opt-out routing guarantee.

    For any request where replacement is disabled (by header or session flag),
    the effective backend:model must equal the user-specified backend:model.

    Feature: random-model-replacement, Property 34
    Validates: Requirements 9.4
    """
    # Create service with probability=1.0 to ensure it would trigger
    service = create_test_service(
        probability=1.0,
        backend_model="replacement-backend:replacement-model",
        turn_count=turn_count,
    )

    # Create context with opt-out header
    context = create_test_context(headers={"x-disable-replacement": "true"})

    # Check that replacement is skipped
    session_id = "test-session"
    should_replace = service.should_replace(session_id, context)
    assert not should_replace, "Replacement should be skipped with opt-out header"

    # Get effective backend:model
    effective_backend, effective_model = service.get_effective_backend_model(
        session_id, original_backend, original_model
    )

    # Verify original backend:model is used
    assert (
        effective_backend == original_backend
    ), f"Backend mismatch: expected {original_backend}, got {effective_backend}"
    assert (
        effective_model == original_model
    ), f"Model mismatch: expected {original_model}, got {effective_model}"


@given(
    turn_count=st.integers(min_value=1, max_value=100),
)
@property_test_settings(suppress_health_check=[HealthCheck.filter_too_much])
def test_property_34_session_level_opt_out_routing(turn_count: int) -> None:
    """
    Property 34: Opt-out routing guarantee (session-level).

    For any session marked as replacement-disabled, the effective backend:model
    must equal the user-specified backend:model.

    Feature: random-model-replacement, Property 34
    Validates: Requirements 9.4
    """
    # Create service with probability=1.0
    service = create_test_service(probability=1.0, turn_count=turn_count)

    # Disable replacement for session
    session_id = "test-session"
    service.disable_for_session(session_id)

    # Create context without opt-out header
    context = create_test_context()

    # Check that replacement is skipped
    should_replace = service.should_replace(session_id, context)
    assert not should_replace, "Replacement should be skipped for disabled session"

    # Get effective backend:model
    original_backend = "original-backend"
    original_model = "original-model"
    effective_backend, effective_model = service.get_effective_backend_model(
        session_id, original_backend, original_model
    )

    # Verify original backend:model is used
    assert effective_backend == original_backend
    assert effective_model == original_model


@given(
    probability=st.floats(min_value=0.0, max_value=1.0),
    turn_count=st.integers(min_value=1, max_value=100),
)
@property_test_settings(suppress_health_check=[HealthCheck.filter_too_much])
def test_opt_out_header_without_replacement_active(
    probability: float, turn_count: int
) -> None:
    """
    Test that opt-out header works even when replacement is not active.

    This ensures the opt-out check happens before probability evaluation.
    """
    # Create service with given probability
    service = create_test_service(probability=probability, turn_count=turn_count)

    # Create context with opt-out header
    context = create_test_context(headers={"x-disable-replacement": "true"})

    # Check multiple times - should never trigger
    for i in range(10):
        session_id = f"test-session-{i}"
        should_replace = service.should_replace(session_id, context)
        assert (
            not should_replace
        ), f"Replacement triggered with opt-out header on check {i}"


@given(
    turn_count=st.integers(min_value=2, max_value=100),
)
@property_test_settings(suppress_health_check=[HealthCheck.filter_too_much])
async def test_opt_out_header_with_active_replacement(turn_count: int) -> None:
    """
    Test that opt-out header prevents replacement even when already active.

    This verifies that the opt-out check happens before the active state check.
    """
    # Create service with probability=1.0
    service = create_test_service(probability=1.0, turn_count=turn_count)

    session_id = "test-session"
    context_no_opt_out = create_test_context()

    # First turn is skipped (guaranteed original model)
    service.should_replace(session_id, context_no_opt_out)

    # Second request without opt-out - should activate
    should_replace = service.should_replace(session_id, context_no_opt_out)
    assert should_replace, "Replacement should trigger on second request"

    # Activate replacement
    await service.activate_replacement(session_id, "original-backend", "original-model")

    # Verify replacement is active
    state = service.get_state(session_id)
    assert state.active, "Replacement should be active"

    # Third request with opt-out header - should not replace
    context_with_opt_out = create_test_context(
        headers={"x-disable-replacement": "true"}
    )
    should_replace = service.should_replace(session_id, context_with_opt_out)
    assert (
        not should_replace
    ), "Replacement should be skipped with opt-out header even when active"
