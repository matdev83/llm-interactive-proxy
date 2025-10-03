"""Unit tests for the tool call loop detection tracker."""

import datetime
import json

import pytest
from src.tool_call_loop.config import ToolCallLoopConfig, ToolLoopMode
from src.tool_call_loop.tracker import ToolCallSignature, ToolCallTracker


class TestToolCallSignature:
    """Tests for the ToolCallSignature class."""

    def test_from_tool_call_valid_json(self):
        """Test creating a signature from a tool call with valid JSON arguments."""
        tool_name = "test_tool"
        arguments = '{"arg1": "value1", "arg2": 42}'

        signature = ToolCallSignature.from_tool_call(tool_name, arguments)

        assert signature.tool_name == tool_name
        assert signature.raw_arguments == arguments
        # Check that the arguments are canonicalized (sorted keys)
        expected_canonical = json.dumps(json.loads(arguments), sort_keys=True)
        assert signature.arguments_signature == expected_canonical

    def test_from_tool_call_invalid_json(self):
        """Test creating a signature from a tool call with invalid JSON arguments."""
        tool_name = "test_tool"
        arguments = "invalid json"

        signature = ToolCallSignature.from_tool_call(tool_name, arguments)

        assert signature.tool_name == tool_name
        assert signature.raw_arguments == arguments
        # Invalid JSON should be used as-is
        assert signature.arguments_signature == arguments

    def test_get_full_signature(self):
        """Test getting the full signature string."""
        tool_name = "test_tool"
        arguments = '{"arg": "value"}'

        signature = ToolCallSignature.from_tool_call(tool_name, arguments)

        # Full signature should be tool_name:arguments_signature
        expected_full_sig = (
            f"{tool_name}:{json.dumps(json.loads(arguments), sort_keys=True)}"
        )
        assert signature.get_full_signature() == expected_full_sig

    def test_is_expired(self):
        """Test checking if a signature has expired."""
        # Create a signature with a timestamp in the past
        signature = ToolCallSignature(
            timestamp=datetime.datetime.now() - datetime.timedelta(seconds=10),
            tool_name="test_tool",
            arguments_signature='{"arg": "value"}',
            raw_arguments='{"arg": "value"}',
        )

        # Should be expired with TTL of 5 seconds
        assert signature.is_expired(5) is True
        # Should not be expired with TTL of 15 seconds
        assert signature.is_expired(15) is False


class TestToolCallTracker:
    """Tests for the ToolCallTracker class."""

    @pytest.fixture
    def config(self) -> ToolCallLoopConfig:
        """Create a default configuration for testing."""
        return ToolCallLoopConfig(
            enabled=True, max_repeats=3, ttl_seconds=60, mode=ToolLoopMode.BREAK
        )

    def test_init(self, config) -> None:
        """Test initializing the tracker."""
        tracker = ToolCallTracker(config)

        assert tracker.config == config
        assert tracker.signatures == []
        assert tracker.consecutive_repeats == {}
        assert tracker.chance_given == {}

    def test_prune_expired_no_signatures(self, config) -> None:
        """Test pruning when there are no signatures."""
        tracker = ToolCallTracker(config)

        pruned = tracker.prune_expired()

        assert pruned == 0
        assert tracker.signatures == []

    def test_prune_expired_with_expired(self, config) -> None:
        """Test pruning with expired signatures."""
        tracker = ToolCallTracker(config)

        # Add an expired signature
        expired_sig = ToolCallSignature(
            timestamp=datetime.datetime.now()
            - datetime.timedelta(seconds=config.ttl_seconds + 10),
            tool_name="test_tool",
            arguments_signature='{"arg": "value"}',
            raw_arguments='{"arg": "value"}',
        )
        tracker.signatures.append(expired_sig)
        tracker.consecutive_repeats[expired_sig.get_full_signature()] = 2

        # Add a non-expired signature
        valid_sig = ToolCallSignature(
            timestamp=datetime.datetime.now(),
            tool_name="test_tool2",
            arguments_signature='{"arg": "value2"}',
            raw_arguments='{"arg": "value2"}',
        )
        tracker.signatures.append(valid_sig)
        tracker.consecutive_repeats[valid_sig.get_full_signature()] = 1

        pruned = tracker.prune_expired()

        assert pruned == 1
        assert len(tracker.signatures) == 1
        assert tracker.signatures[0] == valid_sig
        # Check that the consecutive count for the expired signature is removed
        assert expired_sig.get_full_signature() not in tracker.consecutive_repeats
        assert valid_sig.get_full_signature() in tracker.consecutive_repeats

    def test_track_tool_call_disabled(self, config) -> None:
        """Test tracking when disabled."""
        config.enabled = False
        tracker = ToolCallTracker(config)

        should_block, _reason, _count = tracker.track_tool_call(
            "test_tool", '{"arg": "value"}'
        )

        assert should_block is False
        assert _reason is None
        assert _count is None
        # No signature should be added when disabled
        assert len(tracker.signatures) == 0

    def test_track_tool_call_first_call(self, config) -> None:
        """Test tracking the first call."""
        tracker = ToolCallTracker(config)

        should_block, _reason, _count = tracker.track_tool_call(
            "test_tool", '{"arg": "value"}'
        )

        assert should_block is False
        assert _reason is None
        assert _count is None
        # Signature should be added
        assert len(tracker.signatures) == 1
        assert tracker.signatures[0].tool_name == "test_tool"
        # Consecutive count should be initialized
        full_sig = tracker.signatures[0].get_full_signature()
        assert tracker.consecutive_repeats[full_sig] == 1


class TestToolCallLoopConfig:
    """Tests for ToolCallLoopConfig helper methods."""

    def test_merge_with_none_returns_copy(self) -> None:
        """Ensure merge_with(None) returns a new instance."""
        original = ToolCallLoopConfig(
            enabled=False,
            max_repeats=5,
            ttl_seconds=45,
            mode=ToolLoopMode.BREAK,
        )

        merged = original.merge_with(None)

        assert merged is not original
        assert merged == original

        merged.enabled = True
        assert original.enabled is False

    def test_merge_with_override_does_not_mutate_inputs(self) -> None:
        """Ensure overrides produce independent merged config."""
        base = ToolCallLoopConfig(
            enabled=False,
            max_repeats=2,
            ttl_seconds=30,
            mode=ToolLoopMode.BREAK,
        )
        override = ToolCallLoopConfig(
            enabled=True,
            max_repeats=4,
            ttl_seconds=60,
            mode=ToolLoopMode.CHANCE_THEN_BREAK,
        )

        merged = base.merge_with(override)

        assert merged is not base
        assert merged is not override
        assert merged.enabled is True
        assert merged.max_repeats == 4
        assert merged.ttl_seconds == 60
        assert merged.mode is ToolLoopMode.CHANCE_THEN_BREAK

        # Mutating the merged instance should not leak back to inputs
        merged.max_repeats = 10
        assert base.max_repeats == 2
        assert override.max_repeats == 4


class TestToolCallTracker:
    """Tests for ToolCallTracker functionality."""

    @pytest.fixture
    def config(self) -> ToolCallLoopConfig:
        """Create a default configuration for testing."""
        return ToolCallLoopConfig(
            enabled=True, max_repeats=3, ttl_seconds=60, mode=ToolLoopMode.BREAK
        )

    def test_track_tool_call_different_calls(self, config) -> None:
        """Test tracking different tool calls."""
        tracker = ToolCallTracker(config)

        # First call
        tracker.track_tool_call("test_tool", '{"arg": "value1"}')
        # Different tool
        tracker.track_tool_call("different_tool", '{"arg": "value1"}')
        # Same tool, different args
        tracker.track_tool_call("test_tool", '{"arg": "value2"}')

        # Should have 3 signatures
        assert len(tracker.signatures) == 3
        # Each should have a consecutive count of 1
        assert len(tracker.consecutive_repeats) == 3
        for sig in tracker.signatures:
            assert tracker.consecutive_repeats[sig.get_full_signature()] == 1

    def test_track_tool_call_repeated_below_threshold(self, config) -> None:
        """Test tracking repeated calls below the threshold."""
        tracker = ToolCallTracker(config)

        # Make repeated calls but not enough to trigger blocking
        for _ in range(config.max_repeats - 1):
            should_block, _reason, _count = tracker.track_tool_call(
                "test_tool", '{"arg": "value"}'
            )
            assert should_block is False

        # Check that the consecutive count is correct
        assert len(tracker.signatures) == config.max_repeats - 1
        full_sig = tracker.signatures[0].get_full_signature()
        assert tracker.consecutive_repeats[full_sig] == config.max_repeats - 1

    def test_track_tool_call_repeated_at_threshold_break_mode(self, config) -> None:
        """Test tracking repeated calls at the threshold with break mode."""
        config.mode = ToolLoopMode.BREAK
        tracker = ToolCallTracker(config)

        # Make repeated calls to trigger blocking
        for _ in range(config.max_repeats - 1):
            should_block, reason, count = tracker.track_tool_call(
                "test_tool", '{"arg": "value"}'
            )
            assert should_block is False

        # The last call should be blocked
        should_block, reason, count = tracker.track_tool_call(
            "test_tool", '{"arg": "value"}'
        )

        assert should_block is True
        assert reason is not None
        assert "Tool call loop detected" in reason
        assert count == config.max_repeats

    def test_track_tool_call_repeated_at_threshold_chance_mode(self, config) -> None:
        """Test tracking repeated calls at the threshold with chance_then_break mode."""
        config.mode = ToolLoopMode.CHANCE_THEN_BREAK
        tracker = ToolCallTracker(config)

        # Make repeated calls to trigger the chance
        for _ in range(config.max_repeats - 1):
            should_block, reason, count = tracker.track_tool_call(
                "test_tool", '{"arg": "value"}'
            )
            assert should_block is False

        # The call at the threshold should be blocked with a chance
        should_block, reason, count = tracker.track_tool_call(
            "test_tool", '{"arg": "value"}'
        )

        assert should_block is True
        assert reason is not None
        assert "Tool call loop warning" in reason
        assert count == config.max_repeats

        # Check that chance was given
        full_sig = tracker.signatures[0].get_full_signature()
        assert tracker.chance_given[full_sig] is True

    def test_track_tool_call_after_chance_different_call(self, config) -> None:
        """Test tracking a different call after a chance was given."""
        config.mode = ToolLoopMode.CHANCE_THEN_BREAK
        tracker = ToolCallTracker(config)

        # Make repeated calls to trigger the chance
        for _ in range(config.max_repeats):
            tracker.track_tool_call("test_tool", '{"arg": "value"}')

        # Now make a different call
        should_block, _reason, _count = tracker.track_tool_call(
            "test_tool", '{"arg": "different"}'
        )

        assert should_block is False
        assert _reason is None
        assert _count is None

        # Check that the chance is not applied to the new signature
        # Note: The chance for the old signature remains in the dict,
        # but it's not used for the new signature
        full_sig = f"test_tool:{json.dumps({'arg': 'different'}, sort_keys=True)}"
        assert full_sig not in tracker.chance_given

    def test_track_tool_call_after_chance_same_call(self, config) -> None:
        """Test tracking the same call after a chance was given."""
        config.mode = ToolLoopMode.CHANCE_THEN_BREAK
        tracker = ToolCallTracker(config)

        # Make repeated calls to trigger the chance
        for _ in range(config.max_repeats):
            tracker.track_tool_call("test_tool", '{"arg": "value"}')

        # Now make the same call again
        should_block, reason, count = tracker.track_tool_call(
            "test_tool", '{"arg": "value"}'
        )

        assert should_block is True
        assert reason is not None
        assert "After guidance" in reason
        assert count == config.max_repeats + 1

    def test_track_tool_call_reset_after_different(self, config) -> None:
        """Test that consecutive count resets after a different call."""
        tracker = ToolCallTracker(config)

        # Make some repeated calls
        for _ in range(config.max_repeats - 1):
            tracker.track_tool_call("test_tool", '{"arg": "value"}')

        # Make a different call
        tracker.track_tool_call("different_tool", '{"arg": "value"}')

        # Now make the original call again - should not block
        should_block, _reason, _count = tracker.track_tool_call(
            "test_tool", '{"arg": "value"}'
        )

        assert should_block is False
        assert _reason is None
        assert _count is None

        # Check that the consecutive count was reset
        full_sig = f"test_tool:{json.dumps({'arg': 'value'}, sort_keys=True)}"
        assert tracker.consecutive_repeats[full_sig] == 1

    def test_track_tool_call_with_ttl_expiry(self, config) -> None:
        """Test that TTL expiry resets consecutive counting."""
        tracker = ToolCallTracker(config)

        # Make some repeated calls
        for _ in range(config.max_repeats - 1):
            tracker.track_tool_call("test_tool", '{"arg": "value"}')

        # Manually set the timestamp of the signatures to be in the past
        for sig in tracker.signatures:
            sig.timestamp = datetime.datetime.now() - datetime.timedelta(
                seconds=config.ttl_seconds + 10
            )

        # Make the same call again - should not block due to TTL expiry
        should_block, _reason, _count = tracker.track_tool_call(
            "test_tool", '{"arg": "value"}'
        )

        assert should_block is False
        assert _reason is None
        assert _count is None

        # Check that old signatures were pruned
        assert len(tracker.signatures) == 1
        # Check that the consecutive count was reset
        full_sig = tracker.signatures[0].get_full_signature()
        assert tracker.consecutive_repeats[full_sig] == 1


class TestToolCallLoopConfig:
    """Tests for the ToolCallLoopConfig helper methods."""

    @pytest.mark.parametrize(
        "value, expected",
        [
            ("true", True),
            ("TrUe", True),
            ("1", True),
            ("yes", True),
            ("on", True),
            ("false", False),
            ("0", False),
            ("no", False),
            ("off", False),
            ("", False),
        ],
    )
    def test_from_dict_parses_string_booleans(self, value: str, expected: bool) -> None:
        """Ensure string boolean values are parsed correctly."""

        config = ToolCallLoopConfig.from_dict({"enabled": value})

        assert config.enabled is expected

    @pytest.mark.parametrize(
        "value, expected",
        [
            ("true", True),
            ("FALSE", False),
            ("On", True),
            ("off", False),
            ("  yes  ", True),
            (" 0 ", False),
            ("", False),
        ],
    )
    def test_from_env_vars_parses_string_booleans(
        self, value: str, expected: bool
    ) -> None:
        """Ensure environment variable boolean values are parsed correctly."""

        config = ToolCallLoopConfig.from_env_vars(
            {"TOOL_LOOP_DETECTION_ENABLED": value}
        )

        assert config.enabled is expected
