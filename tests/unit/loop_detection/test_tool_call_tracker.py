"""Tests for the ToolCallTracker class."""

import datetime
import json
from typing import Any, Dict

import pytest
from src.loop_detection.tool_call_tracker import ToolCallSignature, ToolCallTracker
from src.loop_detection.config import LoopDetectionConfig


@pytest.fixture
def config() -> LoopDetectionConfig:
    """Create a test configuration."""
    return LoopDetectionConfig(
        enabled=True,
        max_repeats=3,
        ttl_seconds=60,
        mode="consecutive"
    )


class TestToolCallSignature:
    """Test the ToolCallSignature class."""

    def test_signature_creation(self) -> None:
        """Test creating ToolCallSignature instances."""
        sig = ToolCallSignature("test_tool", '{"arg": "value"}')
        
        assert sig.tool_name == "test_tool"
        assert sig.arguments_json == '{"arg": "value"}'
        assert sig.timestamp is not None

    def test_signature_equality(self) -> None:
        """Test ToolCallSignature equality comparison."""
        sig1 = ToolCallSignature("test_tool", '{"arg": "value"}')
        sig2 = ToolCallSignature("test_tool", '{"arg": "value"}')
        sig3 = ToolCallSignature("other_tool", '{"arg": "value"}')
        sig4 = ToolCallSignature("test_tool", '{"other": "value"}')
        
        assert sig1 == sig2
        assert sig1 != sig3
        assert sig1 != sig4

    def test_get_full_signature(self) -> None:
        """Test getting the full signature string."""
        sig = ToolCallSignature("test_tool", '{"arg": "value"}')
        expected = "test_tool:{\"arg\": \"value\"}"
        assert sig.get_full_signature() == expected

    def test_is_expired(self) -> None:
        """Test checking if a signature is expired."""
        sig = ToolCallSignature("test_tool", '{"arg": "value"}')
        
        # Should not be expired immediately
        assert not sig.is_expired(60)
        
        # Manually set timestamp to past
        sig.timestamp = datetime.datetime.now() - datetime.timedelta(seconds=70)
        assert sig.is_expired(60)


class TestToolCallTracker:
    """Test the ToolCallTracker class."""

    def test_tracker_initialization(self, config: LoopDetectionConfig) -> None:
        """Test that tracker initializes correctly."""
        tracker = ToolCallTracker(config)
        
        assert tracker.config == config
        assert len(tracker.signatures) == 0
        assert len(tracker.consecutive_repeats) == 0

    def test_track_first_tool_call(self, config: LoopDetectionConfig) -> None:
        """Test tracking the first call to a tool."""
        tracker = ToolCallTracker(config)
        
        should_block, reason, count = tracker.track_tool_call(
            "test_tool", '{"arg": "value"}'
        )
        
        assert should_block is False
        assert reason is None
        assert count is None
        assert len(tracker.signatures) == 1
        assert len(tracker.consecutive_repeats) == 1
        
        full_sig = "test_tool:{\"arg\": \"value\"}"
        assert tracker.consecutive_repeats[full_sig] == 1

    def test_track_repeated_tool_call_below_threshold(self, config: LoopDetectionConfig) -> None:
        """Test tracking repeated calls below the blocking threshold."""
        tracker = ToolCallTracker(config)
        
        # Make repeated calls up to threshold - 1
        for i in range(config.max_repeats - 1):
            should_block, reason, count = tracker.track_tool_call(
                "test_tool", '{"arg": "value"}'
            )
            assert should_block is False
            assert reason is None
            assert count is None
        
        assert len(tracker.signatures) == 1
        full_sig = "test_tool:{\"arg\": \"value\"}"
        assert tracker.consecutive_repeats[full_sig] == config.max_repeats - 1

    def test_track_repeated_tool_call_at_threshold(self, config: LoopDetectionConfig) -> None:
        """Test tracking repeated calls at the blocking threshold."""
        tracker = ToolCallTracker(config)
        
        # Make repeated calls up to threshold
        for i in range(config.max_repeats - 1):
            tracker.track_tool_call("test_tool", '{"arg": "value"}')
        
        # The threshold call should block
        should_block, reason, count = tracker.track_tool_call(
            "test_tool", '{"arg": "value"}'
        )
        
        assert should_block is True
        assert reason == "consecutive_repeats"
        assert count == config.max_repeats
        assert len(tracker.signatures) == 1
        full_sig = "test_tool:{\"arg\": \"value\"}"
        assert tracker.consecutive_repeats[full_sig] == config.max_repeats

    def test_track_different_tool_calls(self, config: LoopDetectionConfig) -> None:
        """Test tracking calls to different tools."""
        tracker = ToolCallTracker(config)
        
        # Call different tools
        tracker.track_tool_call("tool1", '{"arg": "value1"}')
        tracker.track_tool_call("tool2", '{"arg": "value2"}')
        tracker.track_tool_call("tool1", '{"arg": "value1"}')
        
        assert len(tracker.signatures) == 2
        assert len(tracker.consecutive_repeats) == 2
        
        sig1 = "tool1:{\"arg\": \"value1\"}"
        sig2 = "tool2:{\"arg\": \"value2\"}"
        assert tracker.consecutive_repeats[sig1] == 2
        assert tracker.consecutive_repeats[sig2] == 1

    def test_track_tool_call_with_different_args(self, config: LoopDetectionConfig) -> None:
        """Test that calls with different arguments are treated separately."""
        tracker = ToolCallTracker(config)
        
        # Call same tool with different arguments
        tracker.track_tool_call("test_tool", '{"arg": "value1"}')
        tracker.track_tool_call("test_tool", '{"arg": "value2"}')
        tracker.track_tool_call("test_tool", '{"arg": "value1"}')
        
        assert len(tracker.signatures) == 2
        assert len(tracker.consecutive_repeats) == 2
        
        sig1 = "test_tool:{\"arg\": \"value1\"}"
        sig2 = "test_tool:{\"arg\": \"value2\"}"
        assert tracker.consecutive_repeats[sig1] == 2
        assert tracker.consecutive_repeats[sig2] == 1

    def test_track_tool_call_with_ttl_expiry(self, config: LoopDetectionConfig) -> None:
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
        should_block, reason, count = tracker.track_tool_call(
            "test_tool", '{"arg": "value"}'
        )
        
        assert should_block is False
        assert reason is None
        assert count is None
        
        # Check that old signatures were pruned
        assert len(tracker.signatures) == 1
        # Check that the consecutive count was reset
        full_sig = tracker.signatures[0].get_full_signature()
        assert tracker.consecutive_repeats[full_sig] == 1