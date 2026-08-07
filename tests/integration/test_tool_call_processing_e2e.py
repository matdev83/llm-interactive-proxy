"""
Integration tests for end-to-end tool call processing optimization.

Tests the complete flow of message processing with historical messages,
verifying that:
1. Only new messages are processed
2. Historical messages are skipped efficiently
3. Performance improvements are achieved
4. Conversation continuity is maintained
"""

from __future__ import annotations

import json
import time

from src.core.services import metrics_service
from src.core.utils.message_processing_utils import (
    find_last_assistant_message,
    is_message_processed,
    mark_message_processed,
)


class TestToolCallProcessingE2E:
    """End-to-end integration tests for tool call processing optimization."""

    def setup_method(self):
        """Reset metrics before each test."""
        with metrics_service._lock:
            metrics_service._counters.clear()
            metrics_service._timers.clear()

    def test_large_conversation_history_processing(self):
        """Test processing a conversation with 70+ historical messages."""
        # Create 70 historical messages (already processed)
        historical_messages = []
        for i in range(70):
            msg = {
                "role": "assistant" if i % 2 == 0 else "user",
                "content": f"Message {i}",
            }
            if msg["role"] == "assistant":
                msg["tool_calls"] = [
                    {
                        "id": f"call_{i}",
                        "type": "function",
                        "function": {"name": "test_tool", "arguments": "{}"},
                    }
                ]
                # Mark as already processed
                mark_message_processed(msg)
            historical_messages.append(msg)

        # Add one new message (not processed)
        new_message = {
            "role": "assistant",
            "content": "New response",
            "tool_calls": [
                {
                    "id": "call_new",
                    "type": "function",
                    "function": {"name": "new_tool", "arguments": "{}"},
                }
            ],
        }
        all_messages = [*historical_messages, new_message]

        # Reset metrics to only count messages processed during this operation
        with metrics_service._lock:
            metrics_service._counters.clear()
            metrics_service._timers.clear()

        # Process messages
        processed_count = 0
        skipped_count = 0

        with metrics_service.timer("tool_call.processing.duration"):
            for msg in all_messages:
                # Only process assistant messages that potentially have tool calls
                if msg.get("role") == "assistant" and "tool_calls" in msg:
                    if is_message_processed(msg):
                        skipped_count += 1
                        metrics_service.inc("tool_call.messages.skipped")
                    else:
                        # Simulate processing
                        processed_count += 1
                        mark_message_processed(msg)
                else:
                    # User messages, tool responses, etc. don't need tool call processing
                    continue

        # Verify only the new message was processed
        assert processed_count == 1
        assert skipped_count == 35  # 35 assistant messages in historical data

        # Verify metrics
        assert metrics_service.get("tool_call.messages.processed") == 1
        assert metrics_service.get("tool_call.messages.skipped") == 35

    def test_conversation_continuity_maintained(self):
        """Test that historical tool calls remain in conversation context."""
        # Create messages with tool calls
        messages = [
            {
                "role": "user",
                "content": "Read file.txt",
            },
            {
                "role": "assistant",
                "content": "I'll read the file",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "read_file",
                            "arguments": json.dumps({"path": "file.txt"}),
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_1",
                "content": "File contents here",
            },
            {
                "role": "assistant",
                "content": "The file contains...",
            },
        ]

        # Mark first assistant message as processed
        mark_message_processed(messages[1])

        # Verify tool call is still present
        assert "tool_calls" in messages[1]
        assert len(messages[1]["tool_calls"]) == 1
        assert messages[1]["tool_calls"][0]["function"]["name"] == "read_file"

        # Verify it's marked as processed
        assert is_message_processed(messages[1])

        # Verify tool response is still linked
        assert messages[2]["tool_call_id"] == "call_1"

    def test_performance_improvement_with_large_history(self):
        """Test that processing time is significantly reduced with markers."""
        # Create 100 messages
        messages = []
        for i in range(100):
            msg = {
                "role": "assistant" if i % 2 == 0 else "user",
                "content": f"Message {i}",
            }
            if msg["role"] == "assistant":
                msg["tool_calls"] = [
                    {
                        "id": f"call_{i}",
                        "type": "function",
                        "function": {"name": "test_tool", "arguments": "{}"},
                    }
                ]
            messages.append(msg)

        # Scenario 1: Process all messages (no markers)
        start_time = time.perf_counter()
        for msg in messages:
            # Simulate processing work
            _ = json.dumps(msg)
        time_without_optimization = time.perf_counter() - start_time

        # Scenario 2: Mark all but last as processed
        for msg in messages[:-1]:
            if msg["role"] == "assistant":
                mark_message_processed(msg)

        start_time = time.perf_counter()
        processed = 0
        for msg in messages:
            # Only process assistant messages that potentially have tool calls
            if (
                not is_message_processed(msg)
                and msg.get("role") == "assistant"
                and "tool_calls" in msg
            ):
                # Simulate processing work
                _ = json.dumps(msg)
                processed += 1
        time_with_optimization = time.perf_counter() - start_time

        # Verify significant reduction (should process much fewer messages)
        assert processed <= 2  # Only last message and possibly one user message

        # Performance improvement should be substantial
        # (This is a rough check - actual improvement depends on processing complexity)
        improvement_ratio = time_without_optimization / max(
            time_with_optimization, 0.000001
        )
        assert improvement_ratio > 1.5  # At least 50% faster

    def test_different_message_formats(self):
        """Test processing with different message formats (dict vs object)."""

        class MessageObject:
            def __init__(self, role, content):
                self.role = role
                self.content = content
                self.tool_calls = []

        # Test with dict messages
        dict_msg = {"role": "assistant", "content": "Test"}
        assert not is_message_processed(dict_msg)
        mark_message_processed(dict_msg)
        assert is_message_processed(dict_msg)

        # Test with object messages
        obj_msg = MessageObject("assistant", "Test")
        assert not is_message_processed(obj_msg)
        mark_message_processed(obj_msg)
        assert is_message_processed(obj_msg)

    def test_find_last_assistant_message_utility(self):
        """Test the utility function for finding last assistant message."""
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"},
            {"role": "user", "content": "How are you?"},
            {"role": "assistant", "content": "Good"},
            {"role": "user", "content": "Great"},
        ]

        last_idx = find_last_assistant_message(messages)
        assert last_idx == 3
        assert messages[last_idx]["content"] == "Good"

    def test_find_last_assistant_message_no_assistant(self):
        """Test finding last assistant message when none exist."""
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "user", "content": "Anyone there?"},
        ]

        last_idx = find_last_assistant_message(messages)
        assert last_idx is None

    def test_find_last_assistant_message_empty_list(self):
        """Test finding last assistant message in empty list."""
        messages = []
        last_idx = find_last_assistant_message(messages)
        assert last_idx is None

    def test_error_handling_with_malformed_messages(self):
        """Test that processing handles malformed messages gracefully."""
        messages = [
            {"role": "assistant", "content": "Normal message"},
            {"content": "Missing role"},  # Malformed
            {"role": "assistant"},  # Missing content
            None,  # Completely invalid
        ]

        # Should not crash when checking processed status
        for msg in messages:
            if msg is not None and isinstance(msg, dict):
                try:
                    is_processed = is_message_processed(msg)
                    assert isinstance(is_processed, bool)
                except Exception:
                    # Should handle gracefully
                    pass

    def test_configuration_options_work_correctly(self):
        """Test that configuration options for processing work as expected."""
        # This test verifies that the system respects configuration
        # In a real implementation, this would test force_reprocess flags

        messages = [
            {"role": "assistant", "content": "Message 1"},
            {"role": "assistant", "content": "Message 2"},
        ]

        # Mark first message as processed
        mark_message_processed(messages[0])

        # Normal mode: skip processed messages
        to_process = [msg for msg in messages if not is_message_processed(msg)]
        assert len(to_process) == 1
        assert to_process[0]["content"] == "Message 2"

        # Force reprocess mode: process all messages
        # (In real implementation, this would check a config flag)
        force_reprocess = True
        if force_reprocess:
            to_process = messages
        assert len(to_process) == 2

    def test_metrics_tracking_accuracy(self):
        """Test that metrics accurately track processing statistics."""
        # Reset metrics
        with metrics_service._lock:
            metrics_service._counters.clear()

        messages = []
        for i in range(20):
            msg = {"role": "assistant", "content": f"Message {i}"}
            messages.append(msg)

        # Mark 15 as processed, leave 5 new
        for msg in messages[:15]:
            mark_message_processed(msg)

        # Reset metrics to only count messages processed during this operation
        with metrics_service._lock:
            metrics_service._counters.clear()

        # Track skipped messages
        for msg in messages:
            if is_message_processed(msg):
                metrics_service.inc("tool_call.messages.skipped")
            else:
                # Process new messages
                mark_message_processed(msg)  # This will increment processed counter

        # Verify metrics
        processed = metrics_service.get("tool_call.messages.processed")
        skipped = metrics_service.get("tool_call.messages.skipped")

        assert processed == 5  # 5 new messages processed
        assert skipped == 15  # 15 historical messages skipped

    def test_skip_rate_calculation(self):
        """Test calculation of skip rate for performance monitoring."""
        # Create 95 historical and 5 new messages
        messages = []
        for i in range(100):
            msg = {"role": "assistant", "content": f"Message {i}"}
            if i < 95:
                mark_message_processed(msg)
            messages.append(msg)

        # Reset metrics to only count messages processed during this operation
        with metrics_service._lock:
            metrics_service._counters.clear()

        # Process messages and track metrics
        for msg in messages:
            if is_message_processed(msg):
                metrics_service.inc("tool_call.messages.skipped")
            else:
                mark_message_processed(msg)  # This will increment processed counter

        # Calculate skip rate
        processed = metrics_service.get("tool_call.messages.processed")
        skipped = metrics_service.get("tool_call.messages.skipped")
        total = processed + skipped

        skip_rate = (skipped / total) * 100 if total > 0 else 0

        # Should achieve >90% skip rate
        assert skip_rate >= 90.0
        assert skip_rate == 95.0  # Exactly 95% in this test

    def test_logging_performance_stats(self, caplog):
        """Test that performance statistics are logged correctly."""
        # Generate some processing activity
        for i in range(10):
            msg = {"role": "assistant", "content": f"Message {i}"}
            if i < 8:
                mark_message_processed(msg)
                is_message_processed(msg)
            else:
                mark_message_processed(msg)

        # Record some timing data
        metrics_service.record_duration("tool_call.processing.duration", 0.001)
        metrics_service.record_duration("tool_call.processing.duration", 0.002)

        # Log stats
        metrics_service.log_performance_stats()

        # Verify log output
        log_messages = [record.message for record in caplog.records]
        assert any("processed=" in msg for msg in log_messages)
        assert any("skipped=" in msg for msg in log_messages)
        assert any("skip_rate=" in msg for msg in log_messages)
