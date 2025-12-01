"""Unit tests for SessionState replacement state integration."""

from src.core.domain.replacement_state import ReplacementState
from src.core.domain.session import SessionState


def test_session_state_has_replacement_fields():
    """Test that SessionState has replacement_state and replacement_disabled fields."""
    state = SessionState()

    assert hasattr(
        state, "replacement_state"
    ), "SessionState should have replacement_state field"
    assert hasattr(
        state, "replacement_disabled"
    ), "SessionState should have replacement_disabled field"

    # Verify default values
    assert state.replacement_state is None, "Default replacement_state should be None"
    assert (
        state.replacement_disabled is False
    ), "Default replacement_disabled should be False"


def test_get_replacement_state_returns_default():
    """Test that get_replacement_state returns a default ReplacementState when none is set."""
    session_state = SessionState()

    replacement_state = session_state.get_replacement_state()

    assert isinstance(
        replacement_state, ReplacementState
    ), "Should return ReplacementState instance"
    assert replacement_state.active is False, "Default state should be inactive"
    assert (
        replacement_state.turns_remaining == 0
    ), "Default state should have 0 turns remaining"


def test_set_and_get_replacement_state():
    """Test that set_replacement_state and get_replacement_state work correctly."""
    session_state = SessionState()

    # Create a replacement state
    replacement_state = ReplacementState()
    replacement_state.activate(
        turn_count=3,
        original_backend="anthropic",
        original_model="claude-3-5-sonnet",
        replacement_backend="openai",
        replacement_model="gpt-4",
    )

    # Set it on the session state
    new_session_state = session_state.set_replacement_state(replacement_state)

    # Verify the original session state is unchanged (immutable)
    assert (
        session_state.replacement_state is None
    ), "Original session state should be unchanged"

    # Verify the new session state has the replacement state
    assert (
        new_session_state.replacement_state is not None
    ), "New session state should have replacement_state"

    # Get the replacement state back
    retrieved_state = new_session_state.get_replacement_state()

    # Verify all fields match
    assert retrieved_state.active is True, "Retrieved state should be active"
    assert (
        retrieved_state.turns_remaining == 3
    ), "Retrieved state should have 3 turns remaining"
    assert (
        retrieved_state.original_backend == "anthropic"
    ), "Original backend should match"
    assert (
        retrieved_state.original_model == "claude-3-5-sonnet"
    ), "Original model should match"
    assert (
        retrieved_state.replacement_backend == "openai"
    ), "Replacement backend should match"
    assert (
        retrieved_state.replacement_model == "gpt-4"
    ), "Replacement model should match"


def test_replacement_state_round_trip():
    """Test that replacement state can be stored and retrieved multiple times."""
    session_state = SessionState()

    # Create and set initial state
    state1 = ReplacementState()
    state1.activate(
        turn_count=5,
        original_backend="test1",
        original_model="model1",
        replacement_backend="test2",
        replacement_model="model2",
    )

    session_state = session_state.set_replacement_state(state1)

    # Retrieve and modify
    retrieved_state = session_state.get_replacement_state()
    retrieved_state.decrement_turn()

    # Store modified state
    session_state = session_state.set_replacement_state(retrieved_state)

    # Retrieve again and verify
    final_state = session_state.get_replacement_state()
    assert final_state.active is True, "State should still be active"
    assert final_state.turns_remaining == 4, "Turns should be decremented to 4"


def test_replacement_disabled_field():
    """Test that replacement_disabled field works correctly."""
    session_state = SessionState()

    # Verify default
    assert session_state.replacement_disabled is False, "Default should be False"

    # Create new state with replacement_disabled=True
    new_state = session_state.model_copy(update={"replacement_disabled": True})

    # Verify original is unchanged
    assert session_state.replacement_disabled is False, "Original should be unchanged"

    # Verify new state has the flag set
    assert new_state.replacement_disabled is True, "New state should have flag set"
