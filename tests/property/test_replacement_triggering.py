"""Property-based tests for replacement triggering logic.

Feature: random-model-replacement
Properties: 6, 7, 8, 9
Validates: Requirements 1.4, 1.5, 3.1, 3.2
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
    probability: float,
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


def create_test_context() -> RequestContext:
    """Helper to create a test request context."""
    return RequestContext(
        headers={},
        cookies={},
        state=None,
        app_state=None,
    )


@given(
    turn_count=st.integers(min_value=1, max_value=100),
    num_checks=st.integers(min_value=1, max_value=50),
)
@property_test_settings(suppress_health_check=[HealthCheck.filter_too_much])
def test_property_6_probability_zero_never_triggers(
    turn_count: int, num_checks: int
) -> None:
    """
    Property 6: Probability zero never triggers.

    For any session with replacement_probability=0.0, replacement mode must
    never activate regardless of the number of turns.

    Validates: Requirements 1.4
    """
    # Create service with probability=0.0
    service = create_test_service(probability=0.0, turn_count=turn_count)
    context = create_test_context()

    # Check multiple times - should never trigger
    for i in range(num_checks):
        session_id = f"test-session-{i}"
        should_replace = service.should_replace(session_id, context)
        assert (
            not should_replace
        ), f"Replacement triggered with probability=0.0 on check {i}"


@given(
    turn_count=st.integers(min_value=1, max_value=100),
)
@property_test_settings(suppress_health_check=[HealthCheck.filter_too_much])
def test_property_7_probability_one_always_triggers(turn_count: int) -> None:
    """
    Property 7: Probability one always triggers.

    For any session with replacement_probability=1.0 and replacement not
    currently active, replacement mode must activate on the next eligible turn.

    Note: First turn is always skipped (guaranteed original model), so replacement
    triggers on the second turn.

    Validates: Requirements 1.5
    """
    # Create service with probability=1.0
    service = create_test_service(probability=1.0, turn_count=turn_count)
    context = create_test_context()

    session_id = "test-session"

    # First turn is skipped (guaranteed original model)
    first_turn = service.should_replace(session_id, context)
    assert not first_turn, "First turn should not trigger replacement"

    # Second turn should always trigger with probability=1.0
    should_replace = service.should_replace(session_id, context)
    assert (
        should_replace
    ), "Replacement did not trigger with probability=1.0 on second turn"


@given(
    probability=st.floats(min_value=0.0, max_value=1.0),
    turn_count=st.integers(min_value=1, max_value=100),
    num_checks=st.integers(min_value=10, max_value=100),
)
@property_test_settings(suppress_health_check=[HealthCheck.filter_too_much])
def test_property_8_random_number_range(
    probability: float, turn_count: int, num_checks: int
) -> None:
    """
    Property 8: Random number range.

    For any replacement probability check, the generated random number must be
    between 0.0 and 1.0 inclusive.

    Validates: Requirements 3.1
    """
    # Track all random values generated
    random_values: list[float] = []

    def tracking_random_generator() -> float:
        import random

        value = random.random()
        random_values.append(value)
        return value

    # Create service with tracking random generator
    service = create_test_service(
        probability=probability,
        turn_count=turn_count,
        random_generator=tracking_random_generator,
    )
    context = create_test_context()

    # Perform multiple checks to generate random numbers
    for i in range(num_checks):
        session_id = f"test-session-{i}"
        service.should_replace(session_id, context)

    # Verify all random values are in valid range
    for value in random_values:
        assert 0.0 <= value <= 1.0, f"Random value {value} is outside [0.0, 1.0]"


@given(
    probability=st.floats(min_value=0.01, max_value=0.99),
    turn_count=st.integers(min_value=1, max_value=100),
    random_value=st.floats(min_value=0.0, max_value=1.0),
)
@property_test_settings(suppress_health_check=[HealthCheck.filter_too_much])
def test_property_9_probability_threshold_activation(
    probability: float, turn_count: int, random_value: float
) -> None:
    """
    Property 9: Probability threshold activation.

    For any turn where replacement is not active, if the generated random
    number is less than replacement_probability, then replacement mode must
    activate.

    Note: First turn is always skipped (guaranteed original model), so the
    probability check happens on the second turn.

    Validates: Requirements 3.2
    """

    # Create service with deterministic random generator
    def deterministic_random() -> float:
        return random_value

    service = create_test_service(
        probability=probability,
        turn_count=turn_count,
        random_generator=deterministic_random,
    )
    context = create_test_context()

    session_id = "test-session"

    # First turn is skipped (guaranteed original model)
    first_turn = service.should_replace(session_id, context)
    assert not first_turn, "First turn should not trigger replacement"

    # Second turn checks probability
    should_replace = service.should_replace(session_id, context)

    # Verify threshold logic
    expected_trigger = random_value < probability
    assert should_replace == expected_trigger, (
        f"Replacement trigger mismatch: random={random_value:.4f}, "
        f"probability={probability:.4f}, expected={expected_trigger}, "
        f"actual={should_replace}"
    )


@given(
    probability=st.floats(min_value=0.0, max_value=1.0),
    turn_count=st.integers(min_value=1, max_value=100),
)
@property_test_settings(suppress_health_check=[HealthCheck.filter_too_much])
def test_disabled_feature_never_triggers(probability: float, turn_count: int) -> None:
    """
    Test that disabled feature never triggers replacement.

    When enabled=False, replacement should never activate regardless of
    probability.
    """
    registry = BackendRegistry()

    def mock_factory() -> None:
        pass

    registry.register_backend("test-backend", mock_factory)

    # Create disabled configuration
    config = ReplacementConfig(
        enabled=False,
        probability=probability,
        backend_model="test-backend:test-model",
        turn_count=turn_count,
    )

    service = ModelReplacementService(config, registry)
    context = create_test_context()

    # Should never trigger when disabled
    session_id = "test-session"
    should_replace = service.should_replace(session_id, context)
    assert not should_replace, "Replacement triggered when feature is disabled"
