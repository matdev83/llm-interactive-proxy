"""Tests for SessionState class."""

from typing import cast

from src.core.domain.session import SessionState


class TestSessionStateWeightedFirstRequest:
    """Tests for weighted_first_request_consumed field in SessionState."""

    def test_weighted_first_request_consumed_defaults_to_false(self) -> None:
        """Test that weighted_first_request_consumed defaults to False for new sessions."""
        state = SessionState()

        assert state.weighted_first_request_consumed is False

    def test_with_weighted_first_request_consumed_returns_new_state(self) -> None:
        """Test that with_weighted_first_request_consumed creates a new state with updated value."""
        state = SessionState()

        new_state = state.with_weighted_first_request_consumed(True)

        assert new_state.weighted_first_request_consumed is True
        assert state.weighted_first_request_consumed is False  # Original unchanged

    def test_with_weighted_first_request_consumed_copy_on_write_behavior(self) -> None:
        """Test copy-on-write behavior for weighted_first_request_consumed."""
        state = SessionState()

        new_state = state.with_weighted_first_request_consumed(True)

        # Verify copy-on-write: original should be unchanged
        assert state is not new_state
        assert state.weighted_first_request_consumed is False
        assert new_state.weighted_first_request_consumed is True

    def test_with_weighted_first_request_consumed_can_set_to_false(self) -> None:
        """Test that with_weighted_first_request_consumed can explicitly set to False."""
        state = SessionState(weighted_first_request_consumed=True)

        new_state = state.with_weighted_first_request_consumed(False)

        assert new_state.weighted_first_request_consumed is False

    def test_weighted_first_request_consumed_persists_via_to_dict(self) -> None:
        """Test that weighted_first_request_consumed is preserved in dict serialization."""
        state = SessionState(weighted_first_request_consumed=True)

        state_dict = state.to_dict()

        assert state_dict["weighted_first_request_consumed"] is True

    def test_weighted_first_request_consumed_restored_via_from_dict(self) -> None:
        """Test that weighted_first_request_consumed is restored from dict serialization."""
        state = SessionState(weighted_first_request_consumed=True)
        state_dict = state.to_dict()

        restored_state = cast(SessionState, SessionState.from_dict(state_dict))

        assert restored_state.weighted_first_request_consumed is True

    def test_with_interleaved_thinking_weighted_cycle_state_returns_new_state(
        self,
    ) -> None:
        state = SessionState()
        cycle_state = {
            "selector": "[weight=1]anthropic:claude^[weight=1][thinker]openai:gpt-4",
            "sequence": ["anthropic:claude", "openai:gpt-4"],
            "next_index": 1,
        }

        new_state = state.with_interleaved_thinking_weighted_cycle_state(cycle_state)

        assert state.interleaved_thinking_weighted_cycle_state is None
        assert new_state.interleaved_thinking_weighted_cycle_state == cycle_state

    def test_interleaved_thinking_weighted_cycle_state_persists_via_dict(
        self,
    ) -> None:
        cycle_state = {
            "selector": "[weight=1]anthropic:claude^[weight=1][thinker]openai:gpt-4",
            "sequence": ["anthropic:claude", "openai:gpt-4"],
            "next_index": 1,
        }
        state = SessionState(
            interleaved_thinking_weighted_cycle_state=cycle_state,
        )

        restored_state = cast(SessionState, SessionState.from_dict(state.to_dict()))

        assert restored_state.interleaved_thinking_weighted_cycle_state == cycle_state
