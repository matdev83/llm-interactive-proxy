"""Property-based tests for replacement state serialization.

Feature: random-model-replacement
Property 20: State persistence round-trip
Validates: Requirements 5.4, 5.5
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st
from src.core.domain.replacement_state import ReplacementState
from tests.utils.hypothesis_config import property_test_settings

# ============================================================================
# Strategies for generating test data
# ============================================================================


@st.composite
def replacement_state_strategy(draw: st.DrawFn) -> ReplacementState:
    """Generate a random ReplacementState for testing."""
    active = draw(st.booleans())

    # Generate turns_remaining based on active state
    if active:
        turns_remaining = draw(st.integers(min_value=0, max_value=10))
    else:
        # When inactive, turns_remaining should be 0
        turns_remaining = 0

    # Generate backend and model names
    backends = ["anthropic", "openai", "gemini", "qwen-oauth", "test-backend", ""]
    models = [
        "claude-3-5-sonnet",
        "gpt-4",
        "gemini-2.0-flash",
        "qwen3-coder-plus",
        "test-model",
        "",
    ]

    original_backend = draw(st.sampled_from(backends))
    original_model = draw(st.sampled_from(models))
    replacement_backend = draw(st.sampled_from(backends))
    replacement_model = draw(st.sampled_from(models))

    # Create state
    state = ReplacementState(
        active=active,
        turns_remaining=turns_remaining,
        original_backend=original_backend,
        original_model=original_model,
        replacement_backend=replacement_backend,
        replacement_model=replacement_model,
    )

    return state


# ============================================================================
# Property Tests for State Serialization
# ============================================================================


@given(state=replacement_state_strategy())
@property_test_settings()
def test_property_20_state_persistence_round_trip(state: ReplacementState) -> None:
    """
    Feature: random-model-replacement, Property 20: State persistence round-trip

    For any ReplacementState, serializing to dict and then deserializing
    must produce an equivalent ReplacementState.

    Validates: Requirements 5.4, 5.5
    """
    # Serialize to dict
    state_dict = state.to_dict()

    # Verify dict contains all required fields
    assert "active" in state_dict, "Serialized dict should contain 'active' field"
    assert (
        "turns_remaining" in state_dict
    ), "Serialized dict should contain 'turns_remaining' field"
    assert (
        "original_backend" in state_dict
    ), "Serialized dict should contain 'original_backend' field"
    assert (
        "original_model" in state_dict
    ), "Serialized dict should contain 'original_model' field"
    assert (
        "replacement_backend" in state_dict
    ), "Serialized dict should contain 'replacement_backend' field"
    assert (
        "replacement_model" in state_dict
    ), "Serialized dict should contain 'replacement_model' field"

    # Deserialize from dict
    restored_state = ReplacementState.from_dict(state_dict)

    # Verify all fields match
    assert (
        restored_state.active == state.active
    ), f"active field mismatch: expected {state.active}, got {restored_state.active}"
    assert (
        restored_state.turns_remaining == state.turns_remaining
    ), f"turns_remaining mismatch: expected {state.turns_remaining}, got {restored_state.turns_remaining}"
    assert (
        restored_state.original_backend == state.original_backend
    ), f"original_backend mismatch: expected {state.original_backend}, got {restored_state.original_backend}"
    assert (
        restored_state.original_model == state.original_model
    ), f"original_model mismatch: expected {state.original_model}, got {restored_state.original_model}"
    assert (
        restored_state.replacement_backend == state.replacement_backend
    ), f"replacement_backend mismatch: expected {state.replacement_backend}, got {restored_state.replacement_backend}"
    assert (
        restored_state.replacement_model == state.replacement_model
    ), f"replacement_model mismatch: expected {state.replacement_model}, got {restored_state.replacement_model}"


@given(state=replacement_state_strategy())
@property_test_settings()
def test_property_20_serialization_preserves_types(state: ReplacementState) -> None:
    """
    Feature: random-model-replacement, Property 20: Serialization preserves types

    For any ReplacementState, serializing to dict should preserve the correct
    types for all fields.

    Validates: Requirements 5.4, 5.5
    """
    # Serialize to dict
    state_dict = state.to_dict()

    # Verify types
    assert isinstance(
        state_dict["active"], bool
    ), f"active should be bool, got {type(state_dict['active'])}"
    assert isinstance(
        state_dict["turns_remaining"], int
    ), f"turns_remaining should be int, got {type(state_dict['turns_remaining'])}"
    assert isinstance(
        state_dict["original_backend"], str
    ), f"original_backend should be str, got {type(state_dict['original_backend'])}"
    assert isinstance(
        state_dict["original_model"], str
    ), f"original_model should be str, got {type(state_dict['original_model'])}"
    assert isinstance(
        state_dict["replacement_backend"], str
    ), f"replacement_backend should be str, got {type(state_dict['replacement_backend'])}"
    assert isinstance(
        state_dict["replacement_model"], str
    ), f"replacement_model should be str, got {type(state_dict['replacement_model'])}"


@given(state=replacement_state_strategy())
@property_test_settings()
def test_property_20_multiple_round_trips(state: ReplacementState) -> None:
    """
    Feature: random-model-replacement, Property 20: Multiple round-trips

    For any ReplacementState, performing multiple serialize/deserialize cycles
    should produce the same result.

    Validates: Requirements 5.4, 5.5
    """
    # Perform multiple round-trips
    current_state = state
    for i in range(3):
        # Serialize
        state_dict = current_state.to_dict()

        # Deserialize
        current_state = ReplacementState.from_dict(state_dict)

        # Verify all fields still match original
        assert (
            current_state.active == state.active
        ), f"active mismatch after round-trip {i+1}"
        assert (
            current_state.turns_remaining == state.turns_remaining
        ), f"turns_remaining mismatch after round-trip {i+1}"
        assert (
            current_state.original_backend == state.original_backend
        ), f"original_backend mismatch after round-trip {i+1}"
        assert (
            current_state.original_model == state.original_model
        ), f"original_model mismatch after round-trip {i+1}"
        assert (
            current_state.replacement_backend == state.replacement_backend
        ), f"replacement_backend mismatch after round-trip {i+1}"
        assert (
            current_state.replacement_model == state.replacement_model
        ), f"replacement_model mismatch after round-trip {i+1}"


def test_property_20_from_dict_handles_missing_fields() -> None:
    """
    Feature: random-model-replacement, Property 20: from_dict handles missing fields

    For any dict with missing fields, from_dict should use default values.

    Validates: Requirements 5.4, 5.5
    """
    # Test with empty dict
    state = ReplacementState.from_dict({})

    assert state.active is False, "Missing 'active' should default to False"
    assert state.turns_remaining == 0, "Missing 'turns_remaining' should default to 0"
    assert (
        state.original_backend == ""
    ), "Missing 'original_backend' should default to empty string"
    assert (
        state.original_model == ""
    ), "Missing 'original_model' should default to empty string"
    assert (
        state.replacement_backend == ""
    ), "Missing 'replacement_backend' should default to empty string"
    assert (
        state.replacement_model == ""
    ), "Missing 'replacement_model' should default to empty string"


def test_property_20_from_dict_handles_partial_data() -> None:
    """
    Feature: random-model-replacement, Property 20: from_dict handles partial data

    For any dict with some fields present, from_dict should use provided values
    and defaults for missing fields.

    Validates: Requirements 5.4, 5.5
    """
    # Test with partial data
    partial_dict = {
        "active": True,
        "turns_remaining": 5,
        "original_backend": "test-backend",
        # Missing: original_model, replacement_backend, replacement_model
    }

    state = ReplacementState.from_dict(partial_dict)

    # Verify provided values are used
    assert state.active is True, "Provided 'active' should be used"
    assert state.turns_remaining == 5, "Provided 'turns_remaining' should be used"
    assert (
        state.original_backend == "test-backend"
    ), "Provided 'original_backend' should be used"

    # Verify missing values use defaults
    assert (
        state.original_model == ""
    ), "Missing 'original_model' should default to empty string"
    assert (
        state.replacement_backend == ""
    ), "Missing 'replacement_backend' should default to empty string"
    assert (
        state.replacement_model == ""
    ), "Missing 'replacement_model' should default to empty string"
