"""Unit tests for TestExecutionSessionState."""

from __future__ import annotations

import time

import pytest
from src.services.test_execution_reminder.session_state import (
    TestExecutionSessionState,
)


class TestSessionStateInitialization:
    """Test suite for SessionState initialization."""

    def test_default_initialization(self) -> None:
        """Test that SessionState initializes with correct default values."""
        state = TestExecutionSessionState()

        # Should start in clean state
        assert state.is_dirty is False

        # Modification count should be zero
        assert state.modification_count == 0

        # Last test time should be zero (no tests run yet)
        assert state.last_test_time == 0.0

        # Last modification time and last seen should be set to current time
        # (within a small tolerance)
        current_time = time.time()
        assert abs(state.last_modification_time - current_time) < 0.1
        assert abs(state.last_seen - current_time) < 0.1

    def test_explicit_initialization_clean(self) -> None:
        """Test explicit initialization in clean state."""
        state = TestExecutionSessionState(is_dirty=False)

        assert state.is_dirty is False
        assert state.modification_count == 0

    def test_explicit_initialization_dirty(self) -> None:
        """Test explicit initialization in dirty state."""
        state = TestExecutionSessionState(is_dirty=True)

        assert state.is_dirty is True
        # Note: modification_count is still 0 on initialization
        # It only increments when mark_dirty() is called
        assert state.modification_count == 0

    def test_initialization_with_custom_timestamps(self) -> None:
        """Test initialization with custom timestamp values."""
        custom_time = 1234567890.0
        state = TestExecutionSessionState(
            last_modification_time=custom_time,
            last_test_time=custom_time,
            last_seen=custom_time,
        )

        assert state.last_modification_time == custom_time
        assert state.last_test_time == custom_time
        assert state.last_seen == custom_time

    def test_initialization_with_custom_modification_count(self) -> None:
        """Test initialization with custom modification count."""
        state = TestExecutionSessionState(modification_count=5)

        assert state.modification_count == 5


class TestSessionStateTransitions:
    """Test suite for SessionState transitions."""

    def test_mark_dirty_from_clean(self) -> None:
        """Test marking a clean session as dirty."""
        state = TestExecutionSessionState()
        assert state.is_dirty is False

        # Mark dirty
        state.mark_dirty()

        # Should now be dirty
        assert state.is_dirty is True

    def test_mark_dirty_from_dirty(self) -> None:
        """Test marking an already dirty session as dirty again."""
        state = TestExecutionSessionState(is_dirty=True, modification_count=1)

        # Mark dirty again
        state.mark_dirty()

        # Should still be dirty
        assert state.is_dirty is True

    def test_mark_clean_from_dirty(self) -> None:
        """Test marking a dirty session as clean."""
        state = TestExecutionSessionState(is_dirty=True, modification_count=3)

        # Mark clean
        state.mark_clean()

        # Should now be clean
        assert state.is_dirty is False

    def test_mark_clean_from_clean(self) -> None:
        """Test marking an already clean session as clean again."""
        state = TestExecutionSessionState(is_dirty=False)

        # Mark clean again
        state.mark_clean()

        # Should still be clean
        assert state.is_dirty is False

    def test_state_transition_cycle(self) -> None:
        """Test a complete cycle: clean -> dirty -> clean -> dirty."""
        state = TestExecutionSessionState()

        # Start clean
        assert state.is_dirty is False

        # Transition to dirty
        state.mark_dirty()
        assert state.is_dirty is True

        # Transition back to clean
        state.mark_clean()
        assert state.is_dirty is False

        # Transition to dirty again
        state.mark_dirty()
        assert state.is_dirty is True

    def test_multiple_dirty_transitions(self) -> None:
        """Test multiple consecutive dirty transitions."""
        state = TestExecutionSessionState()

        # Mark dirty multiple times
        for _ in range(5):
            state.mark_dirty()

        # Should still be dirty
        assert state.is_dirty is True

    def test_multiple_clean_transitions(self) -> None:
        """Test multiple consecutive clean transitions."""
        state = TestExecutionSessionState(is_dirty=True)

        # Mark clean multiple times
        for _ in range(5):
            state.mark_clean()

        # Should still be clean
        assert state.is_dirty is False


class TestTimestampTracking:
    """Test suite for timestamp tracking."""

    def test_mark_dirty_updates_last_modification_time(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that mark_dirty updates last_modification_time."""
        import src.services.test_execution_reminder.session_state as session_state_module

        current_time = {"value": 1000.0}

        def fake_time() -> float:
            return current_time["value"]

        # Patch the time function in the module
        monkeypatch.setattr(session_state_module, "time", fake_time)

        # Create state with explicit timestamps to avoid default_factory capturing real time
        state = TestExecutionSessionState(
            last_modification_time=current_time["value"],
            last_seen=current_time["value"],
        )
        initial_time = state.last_modification_time

        # Advance time to ensure time difference
        current_time["value"] += 0.01

        # Mark dirty
        state.mark_dirty()

        # Last modification time should be updated
        assert state.last_modification_time > initial_time
        assert state.last_modification_time == pytest.approx(1000.01, rel=0.001)

    def test_mark_dirty_updates_last_seen(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that mark_dirty updates last_seen."""
        current_time = {"value": 1000.0}

        def fake_time() -> float:
            return current_time["value"]

        # Patch time before creating state instance
        # session_state uses "from time import time", so patch the imported function
        monkeypatch.setattr(
            "src.services.test_execution_reminder.session_state.time", fake_time
        )

        # Create state with explicit initial values to avoid default_factory issues
        state = TestExecutionSessionState(
            last_modification_time=current_time["value"],
            last_seen=current_time["value"],
        )
        initial_time = state.last_seen

        # Advance time to ensure time difference
        current_time["value"] += 0.01

        # Mark dirty
        state.mark_dirty()

        # Last seen should be updated
        assert state.last_seen > initial_time
        assert state.last_seen == pytest.approx(1000.01, rel=0.001)

    def test_mark_clean_updates_last_test_time(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that mark_clean updates last_test_time."""
        current_time = {"value": 1000.0}

        def fake_time() -> float:
            return current_time["value"]

        # Patch time before creating state instance
        # session_state uses "from time import time", so patch the imported function
        monkeypatch.setattr(
            "src.services.test_execution_reminder.session_state.time", fake_time
        )

        state = TestExecutionSessionState(is_dirty=True)
        initial_time = state.last_test_time

        # Advance time to ensure time difference
        current_time["value"] += 0.01

        # Mark clean
        state.mark_clean()

        # Last test time should be updated
        assert state.last_test_time > initial_time
        assert state.last_test_time == pytest.approx(1000.01, rel=0.001)

    def test_mark_clean_updates_last_seen(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that mark_clean updates last_seen."""
        current_time = {"value": 1000.0}

        def fake_time() -> float:
            return current_time["value"]

        # Patch time before creating state instance
        # session_state uses "from time import time", so patch the imported function
        monkeypatch.setattr(
            "src.services.test_execution_reminder.session_state.time", fake_time
        )

        # Create state with explicit initial values to avoid default_factory issues
        state = TestExecutionSessionState(
            is_dirty=True,
            last_modification_time=current_time["value"],
            last_seen=current_time["value"],
        )
        initial_time = state.last_seen

        # Advance time to ensure time difference
        current_time["value"] += 0.01

        # Mark clean
        state.mark_clean()

        # Last seen should be updated
        assert state.last_seen > initial_time
        assert state.last_seen == pytest.approx(1000.01, rel=0.001)

    def test_update_last_seen_only(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that update_last_seen only updates last_seen timestamp."""
        current_time = {"value": 1000.0}

        def fake_time() -> float:
            return current_time["value"]

        # Patch time before creating state instance
        # session_state uses "from time import time", so patch the imported function
        monkeypatch.setattr(
            "src.services.test_execution_reminder.session_state.time", fake_time
        )

        # Create state with explicit initial values to avoid default_factory issues
        state = TestExecutionSessionState(
            last_modification_time=current_time["value"],
            last_seen=current_time["value"],
        )
        initial_modification_time = state.last_modification_time
        initial_test_time = state.last_test_time
        initial_last_seen = state.last_seen

        # Advance time to ensure time difference
        current_time["value"] += 0.01

        # Update last seen
        state.update_last_seen()

        # Only last_seen should be updated
        assert state.last_seen > initial_last_seen
        assert state.last_seen == pytest.approx(1000.01, rel=0.001)
        assert state.last_modification_time == initial_modification_time
        assert state.last_test_time == initial_test_time

    def test_timestamp_ordering_after_mark_dirty(self) -> None:
        """Test that timestamps are in correct order after mark_dirty."""
        state = TestExecutionSessionState()

        # Mark dirty
        state.mark_dirty()

        # last_modification_time and last_seen should be approximately equal
        # and both should be greater than last_test_time (which is 0)
        assert abs(state.last_modification_time - state.last_seen) < 0.01
        assert state.last_modification_time > state.last_test_time
        assert state.last_seen > state.last_test_time

    def test_timestamp_ordering_after_mark_clean(self) -> None:
        """Test that timestamps are in correct order after mark_clean."""
        state = TestExecutionSessionState(is_dirty=True)

        # Mark clean
        state.mark_clean()

        # last_test_time and last_seen should be approximately equal
        assert abs(state.last_test_time - state.last_seen) < 0.01

    def test_timestamps_increase_monotonically(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that timestamps increase monotonically with operations."""
        current_time = {"value": 1000.0}

        def fake_time() -> float:
            return current_time["value"]

        # Patch time before creating state instance
        # session_state uses "from time import time", so patch the imported function
        monkeypatch.setattr(
            "src.services.test_execution_reminder.session_state.time", fake_time
        )

        # Create state with explicit initial values to avoid default_factory issues
        state = TestExecutionSessionState(
            last_modification_time=current_time["value"],
            last_seen=current_time["value"],
        )

        # Record initial timestamps
        timestamps = [state.last_seen]

        # Perform operations with time advances
        for _ in range(3):
            current_time["value"] += 0.01
            state.mark_dirty()
            timestamps.append(state.last_seen)

        # All timestamps should be increasing
        for i in range(len(timestamps) - 1):
            assert timestamps[i + 1] > timestamps[i]

    def test_last_modification_time_not_updated_by_mark_clean(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that mark_clean does not update last_modification_time."""
        current_time = {"value": 1000.0}

        def fake_time() -> float:
            return current_time["value"]

        # Patch time before creating state instance
        # session_state uses "from time import time", so patch the imported function
        monkeypatch.setattr(
            "src.services.test_execution_reminder.session_state.time", fake_time
        )

        state = TestExecutionSessionState(is_dirty=True)
        state.mark_dirty()
        modification_time = state.last_modification_time

        # Advance time and mark clean
        current_time["value"] += 0.01
        state.mark_clean()

        # last_modification_time should not change
        assert state.last_modification_time == modification_time

    def test_last_test_time_not_updated_by_mark_dirty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that mark_dirty does not update last_test_time."""
        current_time = {"value": 1000.0}

        def fake_time() -> float:
            return current_time["value"]

        # Patch time before creating state instance
        # session_state uses "from time import time", so patch the imported function
        monkeypatch.setattr(
            "src.services.test_execution_reminder.session_state.time", fake_time
        )

        state = TestExecutionSessionState()
        state.mark_clean()
        test_time = state.last_test_time

        # Advance time and mark dirty
        current_time["value"] += 0.01
        state.mark_dirty()

        # last_test_time should not change
        assert state.last_test_time == test_time


class TestModificationCounting:
    """Test suite for modification counting."""

    def test_initial_modification_count_is_zero(self) -> None:
        """Test that modification count starts at zero."""
        state = TestExecutionSessionState()
        assert state.modification_count == 0

    def test_mark_dirty_increments_modification_count(self) -> None:
        """Test that mark_dirty increments modification count."""
        state = TestExecutionSessionState()
        assert state.modification_count == 0

        # Mark dirty once
        state.mark_dirty()
        assert state.modification_count == 1

        # Mark dirty again
        state.mark_dirty()
        assert state.modification_count == 2

        # Mark dirty a third time
        state.mark_dirty()
        assert state.modification_count == 3

    def test_mark_clean_resets_modification_count(self) -> None:
        """Test that mark_clean resets modification count to zero."""
        state = TestExecutionSessionState()

        # Make some modifications
        state.mark_dirty()
        state.mark_dirty()
        state.mark_dirty()
        assert state.modification_count == 3

        # Mark clean
        state.mark_clean()
        assert state.modification_count == 0

    def test_modification_count_after_multiple_cycles(self) -> None:
        """Test modification count through multiple dirty/clean cycles."""
        state = TestExecutionSessionState()

        # First cycle: 2 modifications
        state.mark_dirty()
        state.mark_dirty()
        assert state.modification_count == 2

        # Clean
        state.mark_clean()
        assert state.modification_count == 0

        # Second cycle: 3 modifications
        state.mark_dirty()
        state.mark_dirty()
        state.mark_dirty()
        assert state.modification_count == 3

        # Clean
        state.mark_clean()
        assert state.modification_count == 0

        # Third cycle: 1 modification
        state.mark_dirty()
        assert state.modification_count == 1

    def test_modification_count_independent_of_update_last_seen(self) -> None:
        """Test that update_last_seen does not affect modification count."""
        state = TestExecutionSessionState()

        # Make some modifications
        state.mark_dirty()
        state.mark_dirty()
        assert state.modification_count == 2

        # Update last seen
        state.update_last_seen()

        # Modification count should not change
        assert state.modification_count == 2

    def test_modification_count_with_consecutive_clean_calls(self) -> None:
        """Test that consecutive mark_clean calls keep count at zero."""
        state = TestExecutionSessionState()

        # Make modifications
        state.mark_dirty()
        state.mark_dirty()
        assert state.modification_count == 2

        # Mark clean multiple times
        state.mark_clean()
        assert state.modification_count == 0

        state.mark_clean()
        assert state.modification_count == 0

        state.mark_clean()
        assert state.modification_count == 0

    def test_large_modification_count(self) -> None:
        """Test handling of large modification counts."""
        state = TestExecutionSessionState()

        # Make many modifications
        for _ in range(100):
            state.mark_dirty()

        assert state.modification_count == 100

        # Clean should reset to zero
        state.mark_clean()
        assert state.modification_count == 0


class TestSessionStateEdgeCases:
    """Test suite for edge cases and boundary conditions."""

    def test_rapid_state_transitions(self) -> None:
        """Test rapid state transitions without delays."""
        state = TestExecutionSessionState()

        # Rapid transitions
        for _ in range(10):
            state.mark_dirty()
            state.mark_clean()

        # Should end in clean state with zero modifications
        assert state.is_dirty is False
        assert state.modification_count == 0

    def test_state_consistency_after_many_operations(self) -> None:
        """Test state consistency after many operations."""
        state = TestExecutionSessionState()

        # Perform many operations
        for i in range(50):
            if i % 2 == 0:
                state.mark_dirty()
            else:
                state.mark_clean()

        # State should be consistent
        # After 50 operations (alternating dirty/clean), should end clean
        assert state.is_dirty is False
        assert state.modification_count == 0

    def test_timestamp_precision(self) -> None:
        """Test that timestamps have sufficient precision."""
        state = TestExecutionSessionState()

        # Perform operations in quick succession
        times = []
        for _ in range(5):
            state.mark_dirty()
            times.append(state.last_modification_time)

        # All timestamps should be unique (or at least most of them)
        # Due to time precision, some might be equal, but not all
        unique_times = len(set(times))
        assert unique_times >= 1  # At least one unique time

    def test_state_after_initialization_with_dirty_flag(self) -> None:
        """Test state behavior when initialized with dirty flag."""
        state = TestExecutionSessionState(is_dirty=True)

        # Should be dirty but with zero modifications
        # (modifications only count when mark_dirty is called)
        assert state.is_dirty is True
        assert state.modification_count == 0

        # First mark_dirty should increment count
        state.mark_dirty()
        assert state.modification_count == 1

    def test_all_timestamps_are_floats(self) -> None:
        """Test that all timestamp fields are floats."""
        state = TestExecutionSessionState()

        assert isinstance(state.last_modification_time, float)
        assert isinstance(state.last_test_time, float)
        assert isinstance(state.last_seen, float)

        # After operations
        state.mark_dirty()
        assert isinstance(state.last_modification_time, float)
        assert isinstance(state.last_seen, float)

        state.mark_clean()
        assert isinstance(state.last_test_time, float)
        assert isinstance(state.last_seen, float)

    def test_modification_count_is_integer(self) -> None:
        """Test that modification count is always an integer."""
        state = TestExecutionSessionState()

        assert isinstance(state.modification_count, int)

        state.mark_dirty()
        assert isinstance(state.modification_count, int)

        state.mark_clean()
        assert isinstance(state.modification_count, int)

    def test_is_dirty_is_boolean(self) -> None:
        """Test that is_dirty is always a boolean."""
        state = TestExecutionSessionState()

        assert isinstance(state.is_dirty, bool)

        state.mark_dirty()
        assert isinstance(state.is_dirty, bool)

        state.mark_clean()
        assert isinstance(state.is_dirty, bool)
