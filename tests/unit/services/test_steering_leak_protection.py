"""
Tests for Steering Leak Protection Service.

This module tests the systemic protection against internal steering message leaks
in client-facing responses.
"""

from __future__ import annotations

import json

import pytest
from src.core.services.steering_leak_protection import (
    SteeringLeakError,
    SteeringLeakProtector,
    check_and_sanitize_response,
    get_steering_leak_protector,
)


class TestSteeringLeakProtector:
    """Tests for the SteeringLeakProtector class."""

    def test_detects_chatcmpl_steering_id_pattern(self) -> None:
        """Ensure the protector detects chatcmpl-steering-* ID patterns."""
        protector = SteeringLeakProtector()
        content = '{"id": "chatcmpl-steering-1765461372", "object": "chat.completion"}'
        assert protector.has_leak(content) is True

    def test_detects_steering_message_key(self) -> None:
        """Ensure the protector detects steering_message metadata key."""
        protector = SteeringLeakProtector()
        content = '{"steering_message": "Some internal message"}'
        assert protector.has_leak(content) is True

    def test_detects_tool_call_swallowed_key(self) -> None:
        """Ensure the protector detects tool_call_swallowed marker."""
        protector = SteeringLeakProtector()
        content = '{"tool_call_swallowed": true}'
        assert protector.has_leak(content) is True

    def test_detects_steering_replacement_flag(self) -> None:
        """Ensure the protector detects _steering_replacement flag."""
        protector = SteeringLeakProtector()
        content = '{"_steering_replacement": true}'
        assert protector.has_leak(content) is True

    def test_detects_swallowed_tool_calls_array(self) -> None:
        """Ensure the protector detects swallowed_tool_calls array."""
        protector = SteeringLeakProtector()
        content = '{"swallowed_tool_calls": [{"id": "call_123"}]}'
        assert protector.has_leak(content) is True

    def test_detects_original_tool_call_embedding(self) -> None:
        """Ensure the protector detects original_tool_call embedded in response."""
        protector = SteeringLeakProtector()
        content = '{"original_tool_call": {"id": "call_123"}}'
        assert protector.has_leak(content) is True

    def test_no_false_positive_on_normal_content(self) -> None:
        """Ensure normal response content doesn't trigger false positives."""
        protector = SteeringLeakProtector()

        # Normal OpenAI-style response
        normal_response = json.dumps(
            {
                "id": "chatcmpl-abc123",
                "object": "chat.completion",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "Hello, how can I help you?",
                        },
                        "finish_reason": "stop",
                    }
                ],
            }
        )
        assert protector.has_leak(normal_response) is False

    def test_no_false_positive_on_tool_calls_content(self) -> None:
        """Ensure legitimate tool_calls in response don't trigger false positives."""
        protector = SteeringLeakProtector()

        # Response with tool calls (legitimate, not swallowed)
        response = json.dumps(
            {
                "id": "chatcmpl-xyz789",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "tool_calls": [
                                {"id": "call_1", "function": {"name": "search"}}
                            ],
                        }
                    }
                ],
            }
        )
        assert protector.has_leak(response) is False

    def test_sanitize_content_removes_steering_struct(self) -> None:
        """Ensure sanitize_content removes leaked steering JSON structures."""
        protector = SteeringLeakProtector()

        # Simulated leak: steering struct appended to legitimate content
        leaked_content = (
            "Here is my response about the issue."
            '{"id": "chatcmpl-steering-1765461372", "object": "chat.completion", '
            '"created": 1765461372, "model": "claude-opus-4-5-thinking", '
            '"choices": [{"index": 0, "message": {"role": "assistant", '
            '"content": "File operation blocked"}, "finish_reason": "stop"}], '
            '"usage": null}'
        )

        sanitized, had_leak = protector.sanitize_content(leaked_content)
        assert had_leak is True
        assert "chatcmpl-steering" not in sanitized
        # The legitimate content should be preserved
        assert "Here is my response" in sanitized

    def test_sanitize_bytes_works_with_utf8(self) -> None:
        """Ensure sanitize_bytes correctly handles UTF-8 encoded content."""
        protector = SteeringLeakProtector()

        content = '{"id": "chatcmpl-steering-123456", "object": "chat.completion"}'
        data = content.encode("utf-8")

        sanitized, had_leak = protector.sanitize_bytes(data)
        assert had_leak is True
        assert b"chatcmpl-steering" not in sanitized

    def test_sanitize_dict_removes_internal_keys(self) -> None:
        """Ensure sanitize_dict removes internal steering keys."""
        protector = SteeringLeakProtector()

        leaked_dict = {
            "id": "chatcmpl-abc123",
            "choices": [{"message": {"content": "Hello"}}],
            "steering_message": "Internal guidance",
            "tool_call_swallowed": True,
            "_steering_replacement": True,
            "original_tool_call": {"id": "call_123"},
        }

        sanitized, had_leak = protector.sanitize_dict(leaked_dict)
        assert had_leak is True
        assert "steering_message" not in sanitized
        assert "tool_call_swallowed" not in sanitized
        assert "_steering_replacement" not in sanitized
        assert "original_tool_call" not in sanitized
        # Legitimate keys preserved
        assert "id" in sanitized
        assert "choices" in sanitized

    def test_sanitize_dict_handles_nested_metadata(self) -> None:
        """Ensure sanitize_dict also cleans nested metadata."""
        protector = SteeringLeakProtector()

        leaked_dict = {
            "id": "chatcmpl-abc123",
            "metadata": {
                "steering_message": "Should be removed",
                "_steering_replacement": True,
                "legitimate_key": "Keep this",
            },
        }

        sanitized, had_leak = protector.sanitize_dict(leaked_dict)
        assert had_leak is True
        assert "steering_message" not in sanitized.get("metadata", {})
        assert sanitized["metadata"].get("legitimate_key") == "Keep this"

    def test_strict_mode_raises_on_leak(self) -> None:
        """Ensure strict mode raises SteeringLeakError on detection."""
        protector = SteeringLeakProtector(strict_mode=True)

        content = '{"id": "chatcmpl-steering-123", "object": "chat.completion"}'

        with pytest.raises(SteeringLeakError):
            protector.sanitize_content(content)

    def test_disabled_protector_passes_through(self) -> None:
        """Ensure disabled protector doesn't modify content."""
        protector = SteeringLeakProtector(enabled=False)

        leaked_content = '{"id": "chatcmpl-steering-123"}'
        sanitized, had_leak = protector.sanitize_content(leaked_content)

        assert had_leak is False
        assert sanitized == leaked_content

    def test_leak_count_increments(self) -> None:
        """Ensure leak_count tracks detected leaks."""
        protector = SteeringLeakProtector()
        assert protector.leak_count == 0

        protector.sanitize_content('{"id": "chatcmpl-steering-1"}')
        assert protector.leak_count == 1

        protector.sanitize_content('{"id": "chatcmpl-steering-2"}')
        assert protector.leak_count == 2

    def test_empty_content_returns_unchanged(self) -> None:
        """Ensure empty content is handled gracefully."""
        protector = SteeringLeakProtector()

        sanitized, had_leak = protector.sanitize_content("")
        assert had_leak is False
        assert sanitized == ""

        sanitized_bytes, had_leak = protector.sanitize_bytes(b"")
        assert had_leak is False
        assert sanitized_bytes == b""


class TestCheckAndSanitizeResponse:
    """Tests for the check_and_sanitize_response convenience function."""

    def test_handles_string_content(self) -> None:
        """Ensure string content is properly handled."""
        content = '{"id": "chatcmpl-steering-123"}'
        result, had_leak = check_and_sanitize_response(content)
        assert had_leak is True
        assert isinstance(result, str)

    def test_handles_bytes_content(self) -> None:
        """Ensure bytes content is properly handled."""
        content = b'{"id": "chatcmpl-steering-123"}'
        result, had_leak = check_and_sanitize_response(content)
        assert had_leak is True
        assert isinstance(result, bytes)

    def test_handles_dict_content(self) -> None:
        """Ensure dict content is properly handled."""
        content = {"steering_message": "internal", "id": "legitimate"}
        result, had_leak = check_and_sanitize_response(content)
        assert had_leak is True
        assert isinstance(result, dict)
        assert "steering_message" not in result


class TestGlobalProtector:
    """Tests for the global protector singleton."""

    def test_get_steering_leak_protector_returns_singleton(self) -> None:
        """Ensure get_steering_leak_protector returns a consistent instance."""
        protector1 = get_steering_leak_protector()
        protector2 = get_steering_leak_protector()
        # Should be the same instance (or at least same configuration)
        assert protector1.enabled == protector2.enabled


class TestRealWorldLeakScenarios:
    """Tests that simulate real-world leak scenarios from production issues."""

    def test_appended_steering_struct_to_legitimate_response(self) -> None:
        """
        Test the exact scenario reported in the bug:
        A legitimate response followed by leaked steering struct.
        """
        protector = SteeringLeakProtector()

        # This is the actual pattern that was reported
        leaked_content = (
            "The issue might be in how paths are validated after extraction. "
            "The path extracted is the project root itself, which should pass "
            "the is_within_boundary check. Let me look at how --stat might be "
            'included in the path{"id": "chatcmpl-steering-1765461372",'
            '"object": "chat.completion", "created": 1765461372, '
            '"model": "claude-opus-4-5-thinking", "choices": [{"index": 0, '
            '"message":{"role": "assistant", "content": "File operation blocked: '
            "Paths outside project root: /.venv/Scripts/python.exe, "
            "C:\\\\Users\\\\Mateusz\\\\source\\\\repos\\\\llm-interactive-proxy. "
            "Allowed: C:\\\\Users\\\\Mateusz\\\\AppData\\\\Local\\\\Microsoft\\\\"
            'WindowsApps"}, "finish_reason": "stop"}], "usage": null}'
        )

        assert protector.has_leak(leaked_content) is True

        sanitized, had_leak = protector.sanitize_content(leaked_content)
        assert had_leak is True
        # The leaked steering struct should be removed
        assert "chatcmpl-steering" not in sanitized
        # The legitimate content should be preserved
        assert "The issue might be in how paths are validated" in sanitized

    def test_full_steering_response_in_sse_chunk(self) -> None:
        """Test detection of full steering response in SSE chunk format."""
        protector = SteeringLeakProtector()

        # SSE-formatted chunk with steering response
        sse_chunk = (
            'data: {"id": "chatcmpl-steering-123456789", "object": "chat.completion", '
            '"created": 123456789, "model": "steering-agent", '
            '"choices": [{"index": 0, "message": {"role": "assistant", '
            '"content": "Blocked operation"}, "finish_reason": "stop"}], '
            '"usage": null}\n\n'
        )

        assert protector.has_leak(sse_chunk) is True

        # Should be detected in bytes form too
        assert protector.has_leak_bytes(sse_chunk.encode("utf-8")) is True
