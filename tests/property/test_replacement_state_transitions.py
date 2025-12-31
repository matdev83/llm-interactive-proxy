"""Property-based tests for replacement state transitions.

Feature: random-model-replacement
Property 13: Turn counter decrement
Property 14: Deactivation on counter expiry
Property 17: Initial session state
Validates: Requirements 4.1, 4.2, 4.5
"""

from __future__ import annotations

from hypothesis import example, given
from hypothesis import strategies as st
from src.core.domain.replacement_state import ReplacementState
from tests.utils.hypothesis_config import property_test_settings

# ============================================================================
# Strategies for generating test data
# ============================================================================


@st.composite
def backend_model_pair_strategy(draw: st.DrawFn) -> tuple[str, str]:
    """Generate a valid backend:model pair."""
    backends = ["anthropic", "openai", "gemini", "qwen-oauth", "test-backend"]
    models = [
        "claude-3-5-sonnet",
        "gpt-4",
        "gemini-2.0-flash",
        "qwen3-coder-plus",
        "test-model",
    ]

    backend = draw(st.sampled_from(backends))
    model = draw(st.sampled_from(models))

    return (backend, model)


# ============================================================================
# Property Tests for State Transitions
# ============================================================================


@given(
    turn_count=st.integers(min_value=1, max_value=10),
    original_pair=backend_model_pair_strategy(),
    replacement_pair=backend_model_pair_strategy(),
)
@property_test_settings()
def test_property_13_turn_counter_decrement(
    turn_count: int,
    original_pair: tuple[str, str],
    replacement_pair: tuple[str, str],
) -> None:
    """
    Feature: random-model-replacement, Property 13: Turn counter decrement

    For any completed turn where replacement is active and turns_remaining > 0,
    the turns_remaining counter must decrease by exactly 1.

    Validates: Requirements 4.1
    """
    # Create and activate replacement state
    state = ReplacementState()
    original_backend, original_model = original_pair
    replacement_backend, replacement_model = replacement_pair

    state.activate(
        turn_count=turn_count,
        original_backend=original_backend,
        original_model=original_model,
        replacement_backend=replacement_backend,
        replacement_model=replacement_model,
    )

    # Verify initial state
    assert state.active is True, "State should be active after activation"
    assert (
        state.turns_remaining == turn_count
    ), f"Initial turns_remaining should be {turn_count}, got {state.turns_remaining}"

    # Decrement turns one by one and verify
    for i in range(turn_count):
        expected_remaining = turn_count - i
        assert (
            state.turns_remaining == expected_remaining
        ), f"Before decrement {i+1}: expected {expected_remaining}, got {state.turns_remaining}"

        # Decrement
        state.decrement_turn()

        # Verify decrement (unless we've reached 0, in which case it deactivates)
        if expected_remaining > 1:
            assert (
                state.turns_remaining == expected_remaining - 1
            ), f"After decrement {i+1}: expected {expected_remaining - 1}, got {state.turns_remaining}"
            assert (
                state.active is True
            ), f"State should still be active after decrement {i+1}"


@given(
    turn_count=st.integers(min_value=1, max_value=10),
    original_pair=backend_model_pair_strategy(),
    replacement_pair=backend_model_pair_strategy(),
)
@property_test_settings()
def test_property_14_deactivation_on_counter_expiry(
    turn_count: int,
    original_pair: tuple[str, str],
    replacement_pair: tuple[str, str],
) -> None:
    """
    Feature: random-model-replacement, Property 14: Deactivation on counter expiry

    For any replacement state where turns_remaining reaches 0,
    replacement mode must deactivate.

    Validates: Requirements 4.2
    """
    # Create and activate replacement state
    state = ReplacementState()
    original_backend, original_model = original_pair
    replacement_backend, replacement_model = replacement_pair

    state.activate(
        turn_count=turn_count,
        original_backend=original_backend,
        original_model=original_model,
        replacement_backend=replacement_backend,
        replacement_model=replacement_model,
    )

    # Verify initial state
    assert state.active is True, "State should be active after activation"
    assert (
        state.turns_remaining == turn_count
    ), f"Initial turns_remaining should be {turn_count}"

    # Decrement until counter reaches 0
    for _ in range(turn_count):
        state.decrement_turn()

    # Verify deactivation
    assert (
        state.active is False
    ), "State should be deactivated when turns_remaining reaches 0"
    assert state.turns_remaining == 0, "turns_remaining should be 0 after deactivation"


@given(
    turn_count=st.integers(min_value=1, max_value=10),
    original_pair=backend_model_pair_strategy(),
    replacement_pair=backend_model_pair_strategy(),
)
@example(
    turn_count=1,
    original_pair=("anthropic", "claude-3-5-sonnet"),
    replacement_pair=("openai", "gpt-4"),
)
@example(
    turn_count=10,
    original_pair=("gemini", "gemini-2.0-flash"),
    replacement_pair=("qwen-oauth", "qwen3-coder-plus"),
)
@property_test_settings(max_examples=20)
def test_property_14_deactivation_stops_further_decrements(
    turn_count: int,
    original_pair: tuple[str, str],
    replacement_pair: tuple[str, str],
) -> None:
    """
    Feature: random-model-replacement, Property 14: Deactivation stops further decrements

    For any replacement state that has been deactivated,
    further calls to decrement_turn should not change the state.

    Validates: Requirements 4.2
    """
    # Create and activate replacement state
    state = ReplacementState()
    original_backend, original_model = original_pair
    replacement_backend, replacement_model = replacement_pair

    state.activate(
        turn_count=turn_count,
        original_backend=original_backend,
        original_model=original_model,
        replacement_backend=replacement_backend,
        replacement_model=replacement_model,
    )

    # Decrement until deactivated
    for _ in range(turn_count):
        state.decrement_turn()

    # Verify deactivation
    assert state.active is False, "State should be deactivated"
    assert state.turns_remaining == 0, "turns_remaining should be 0"

    # Try to decrement again (should have no effect)
    state.decrement_turn()

    # Verify state hasn't changed
    assert (
        state.active is False
    ), "State should remain deactivated after additional decrement"
    assert (
        state.turns_remaining == 0
    ), "turns_remaining should remain 0 after additional decrement"


def test_property_17_initial_session_state() -> None:
    """
    Feature: random-model-replacement, Property 17: Initial session state

    For any newly created session, replacement mode must be inactive
    (active=False, turns_remaining=0).

    Validates: Requirements 4.5
    """
    # Create a new replacement state (default initialization)
    state = ReplacementState()

    # Verify initial state
    assert state.active is False, "Newly created state should have active=False"
    assert (
        state.turns_remaining == 0
    ), "Newly created state should have turns_remaining=0"
    assert (
        state.original_backend == ""
    ), "Newly created state should have empty original_backend"
    assert (
        state.original_model == ""
    ), "Newly created state should have empty original_model"
    assert (
        state.replacement_backend == ""
    ), "Newly created state should have empty replacement_backend"
    assert (
        state.replacement_model == ""
    ), "Newly created state should have empty replacement_model"


@given(
    turn_count=st.integers(min_value=1, max_value=10),
    original_pair=backend_model_pair_strategy(),
    replacement_pair=backend_model_pair_strategy(),
)
@property_test_settings()
def test_property_17_deactivate_resets_to_initial_state(
    turn_count: int,
    original_pair: tuple[str, str],
    replacement_pair: tuple[str, str],
) -> None:
    """
    Feature: random-model-replacement, Property 17: Deactivate resets to initial state

    For any active replacement state, calling deactivate() should reset
    active and turns_remaining to their initial values.

    Validates: Requirements 4.5
    """
    # Create and activate replacement state
    state = ReplacementState()
    original_backend, original_model = original_pair
    replacement_backend, replacement_model = replacement_pair

    state.activate(
        turn_count=turn_count,
        original_backend=original_backend,
        original_model=original_model,
        replacement_backend=replacement_backend,
        replacement_model=replacement_model,
    )

    # Verify it's active
    assert state.active is True, "State should be active after activation"
    assert state.turns_remaining > 0, "turns_remaining should be > 0 after activation"

    # Deactivate
    state.deactivate()

    # Verify reset to initial state
    assert state.active is False, "State should have active=False after deactivation"
    assert (
        state.turns_remaining == 0
    ), "State should have turns_remaining=0 after deactivation"
    # Note: original/replacement backend/model are preserved for logging purposes


@given(
    turn_count=st.integers(min_value=2, max_value=10),
    decrement_count=st.integers(min_value=1, max_value=5),
    original_pair=backend_model_pair_strategy(),
    replacement_pair=backend_model_pair_strategy(),
)
@property_test_settings()
def test_property_13_partial_decrement_preserves_active_state(
    turn_count: int,
    decrement_count: int,
    original_pair: tuple[str, str],
    replacement_pair: tuple[str, str],
) -> None:
    """
    Feature: random-model-replacement, Property 13: Partial decrement preserves active state

    For any replacement state with turns_remaining > decrement_count,
    decrementing decrement_count times should keep the state active.

    Validates: Requirements 4.1
    """
    # Ensure we don't decrement to 0
    if decrement_count >= turn_count:
        return  # Skip this test case

    # Create and activate replacement state
    state = ReplacementState()
    original_backend, original_model = original_pair
    replacement_backend, replacement_model = replacement_pair

    state.activate(
        turn_count=turn_count,
        original_backend=original_backend,
        original_model=original_model,
        replacement_backend=replacement_backend,
        replacement_model=replacement_model,
    )

    # Decrement partially
    for _ in range(decrement_count):
        state.decrement_turn()

    # Verify state is still active
    assert (
        state.active is True
    ), f"State should still be active after {decrement_count} decrements (turn_count={turn_count})"
    assert (
        state.turns_remaining == turn_count - decrement_count
    ), f"turns_remaining should be {turn_count - decrement_count}, got {state.turns_remaining}"
