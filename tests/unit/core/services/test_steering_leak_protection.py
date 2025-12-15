"""
Tests for steering leak protection service.

These tests verify that internal steering messages are properly detected
and sanitized before reaching clients.
"""

import pytest
from src.core.services.steering_leak_protection import (
    SteeringLeakError,
    SteeringLeakProtector,
    check_and_sanitize_response,
    get_steering_leak_protector,
    set_steering_leak_protector,
)


class TestSteeringLeakProtector:
    """Tests for the SteeringLeakProtector class."""

    def test_init_defaults(self) -> None:
        """Test default initialization values."""
        protector = SteeringLeakProtector()
        assert protector.enabled is True
        assert protector.leak_count == 0

    def test_init_disabled(self) -> None:
        """Test initialization with protection disabled."""
        protector = SteeringLeakProtector(enabled=False)
        assert protector.enabled is False

    def test_set_enabled(self) -> None:
        """Test enabling/disabling protection."""
        protector = SteeringLeakProtector()
        protector.set_enabled(False)
        assert protector.enabled is False
        protector.set_enabled(True)
        assert protector.enabled is True

    def test_has_leak_chatcmpl_steering_id(self) -> None:
        """Test detection of chatcmpl-steering-* ID pattern."""
        protector = SteeringLeakProtector()
        content = '{"id": "chatcmpl-steering-1234567890", "object": "chat.completion"}'
        assert protector.has_leak(content) is True

    def test_has_leak_steering_message(self) -> None:
        """Test detection of steering_message key."""
        protector = SteeringLeakProtector()
        content = '{"steering_message": "Do not execute this command"}'
        assert protector.has_leak(content) is True

    def test_has_leak_tool_call_swallowed(self) -> None:
        """Test detection of tool_call_swallowed flag."""
        protector = SteeringLeakProtector()
        content = '{"tool_call_swallowed": true, "message": "blocked"}'
        assert protector.has_leak(content) is True

    def test_has_leak_swallowed_tool_calls(self) -> None:
        """Test detection of swallowed_tool_calls array."""
        protector = SteeringLeakProtector()
        content = '{"swallowed_tool_calls": [{"id": "call_1"}]}'
        assert protector.has_leak(content) is True

    def test_has_leak_replacement_provided(self) -> None:
        """Test detection of replacement_provided flag."""
        protector = SteeringLeakProtector()
        content = '{"replacement_provided": true}'
        assert protector.has_leak(content) is True

    def test_has_leak_steering_replacement_internal(self) -> None:
        """Test detection of _steering_replacement internal flag."""
        protector = SteeringLeakProtector()
        content = '{"_steering_replacement": true}'
        assert protector.has_leak(content) is True

    def test_has_leak_original_tool_call(self) -> None:
        """Test detection of original_tool_call object."""
        protector = SteeringLeakProtector()
        content = '{"original_tool_call": {"id": "call_1", "function": {}}}'
        assert protector.has_leak(content) is True

    def test_has_no_leak_normal_content(self) -> None:
        """Test that normal content is not flagged as leak."""
        protector = SteeringLeakProtector()
        content = (
            '{"id": "chatcmpl-abc123", "choices": [{"message": {"content": "Hello"}}]}'
        )
        assert protector.has_leak(content) is False

    def test_has_no_leak_empty_content(self) -> None:
        """Test that empty content is not flagged as leak."""
        protector = SteeringLeakProtector()
        assert protector.has_leak("") is False
        assert protector.has_leak(None) is False  # type: ignore[arg-type]

    def test_has_leak_bytes(self) -> None:
        """Test leak detection in byte data."""
        protector = SteeringLeakProtector()
        data = b'{"id": "chatcmpl-steering-1234567890"}'
        assert protector.has_leak_bytes(data) is True

    def test_has_no_leak_bytes_normal(self) -> None:
        """Test that normal byte content is not flagged."""
        protector = SteeringLeakProtector()
        data = b'{"id": "chatcmpl-abc123", "content": "Hello"}'
        assert protector.has_leak_bytes(data) is False

    def test_sanitize_content_removes_leak(self) -> None:
        """Test that leaked steering content is sanitized."""
        protector = SteeringLeakProtector(log_leaks=False)
        content = 'Normal text {"id": "chatcmpl-steering-123", "object": "chat.completion"} more text'
        sanitized, had_leak = protector.sanitize_content(content)
        assert had_leak is True
        assert "chatcmpl-steering" not in sanitized
        assert protector.leak_count == 1

    def test_sanitize_content_no_leak_unchanged(self) -> None:
        """Test that content without leaks is unchanged."""
        protector = SteeringLeakProtector()
        content = "This is normal content without any steering data"
        sanitized, had_leak = protector.sanitize_content(content)
        assert had_leak is False
        assert sanitized == content
        assert protector.leak_count == 0

    def test_sanitize_content_disabled(self) -> None:
        """Test that disabled protection does not sanitize."""
        protector = SteeringLeakProtector(enabled=False)
        content = '{"id": "chatcmpl-steering-123"}'
        sanitized, had_leak = protector.sanitize_content(content)
        assert had_leak is False
        assert sanitized == content

    def test_sanitize_bytes(self) -> None:
        """Test byte data sanitization."""
        protector = SteeringLeakProtector(log_leaks=False)
        data = (
            b'data: {"id": "chatcmpl-steering-123", "steering_message": "blocked"}\n\n'
        )
        sanitized, had_leak = protector.sanitize_bytes(data)
        assert had_leak is True
        assert b"chatcmpl-steering" not in sanitized
        assert b"steering_message" not in sanitized

    def test_sanitize_dict_removes_internal_keys(self) -> None:
        """Test that internal steering keys are removed from dicts."""
        protector = SteeringLeakProtector(log_leaks=False)
        data = {
            "content": "Hello",
            "steering_message": "blocked",
            "tool_call_swallowed": True,
            "_steering_replacement": True,
        }
        sanitized, had_leak = protector.sanitize_dict(data)
        assert had_leak is True
        assert "content" in sanitized
        assert "steering_message" not in sanitized
        assert "tool_call_swallowed" not in sanitized
        assert "_steering_replacement" not in sanitized

    def test_sanitize_dict_preserves_normal_keys(self) -> None:
        """Test that normal keys are preserved."""
        protector = SteeringLeakProtector()
        data = {"content": "Hello", "model": "gpt-4", "usage": {"tokens": 10}}
        sanitized, had_leak = protector.sanitize_dict(data)
        assert had_leak is False
        assert sanitized == data

    def test_sanitize_dict_nested_metadata(self) -> None:
        """Test sanitization of nested metadata."""
        protector = SteeringLeakProtector(log_leaks=False)
        data = {
            "content": "Hello",
            "metadata": {"steering_message": "blocked", "session_id": "123"},
        }
        sanitized, had_leak = protector.sanitize_dict(data)
        assert had_leak is True
        assert "steering_message" not in sanitized.get("metadata", {})
        assert sanitized["metadata"]["session_id"] == "123"

    def test_strict_mode_raises_error(self) -> None:
        """Test that strict mode raises error on leak detection."""
        protector = SteeringLeakProtector(strict_mode=True, log_leaks=False)
        content = '{"id": "chatcmpl-steering-123"}'
        with pytest.raises(SteeringLeakError):
            protector.sanitize_content(content)

    def test_leak_count_increments(self) -> None:
        """Test that leak count increments correctly."""
        protector = SteeringLeakProtector(log_leaks=False)
        assert protector.leak_count == 0

        protector.sanitize_content('{"id": "chatcmpl-steering-1"}')
        assert protector.leak_count == 1

        protector.sanitize_content('{"id": "chatcmpl-steering-2"}')
        assert protector.leak_count == 2

        # No leak should not increment
        protector.sanitize_content("normal content")
        assert protector.leak_count == 2


class TestGlobalProtector:
    """Tests for global protector instance management."""

    def test_get_global_protector(self) -> None:
        """Test getting the global protector instance."""
        protector = get_steering_leak_protector()
        assert protector is not None
        assert isinstance(protector, SteeringLeakProtector)

    def test_set_global_protector(self) -> None:
        """Test setting a custom global protector."""
        original = get_steering_leak_protector()
        custom = SteeringLeakProtector(enabled=False)

        try:
            set_steering_leak_protector(custom)
            current = get_steering_leak_protector()
            assert current is custom
            assert current.enabled is False
        finally:
            # Restore original
            set_steering_leak_protector(original)


class TestCheckAndSanitizeResponse:
    """Tests for the convenience function."""

    def test_sanitize_string(self) -> None:
        """Test sanitizing string content."""
        content = 'text {"id": "chatcmpl-steering-123"} more'
        sanitized, had_leak = check_and_sanitize_response(content)
        assert had_leak is True
        assert isinstance(sanitized, str)

    def test_sanitize_bytes(self) -> None:
        """Test sanitizing bytes content."""
        content = b'{"steering_message": "blocked"}'
        sanitized, had_leak = check_and_sanitize_response(content)
        assert had_leak is True
        assert isinstance(sanitized, bytes)

    def test_sanitize_dict(self) -> None:
        """Test sanitizing dict content."""
        content = {"tool_call_swallowed": True, "content": "Hello"}
        sanitized, had_leak = check_and_sanitize_response(content)
        assert had_leak is True
        assert isinstance(sanitized, dict)
        assert "tool_call_swallowed" not in sanitized

    def test_no_leak_passthrough(self) -> None:
        """Test that content without leaks passes through unchanged."""
        content = {"content": "Hello", "model": "gpt-4"}
        sanitized, had_leak = check_and_sanitize_response(content)
        assert had_leak is False
        assert sanitized == content


class TestRealWorldScenarios:
    """Tests for real-world leak scenarios that triggered this protection."""

    def test_appended_steering_response_detected(self) -> None:
        """Test detection of steering response appended to content.

        This is the actual bug that was reported - steering JSON being
        appended to legitimate LLM response content.
        """
        protector = SteeringLeakProtector(log_leaks=False)

        # Simulates the actual bug: LLM content followed by leaked steering JSON
        content = (
            "The issue might be in how paths are validated after extraction. "
            "The path extracted is the project root itself, which should pass "
            'the is_within_boundary check. {"id": "chatcmpl-steering-1765461372", '
            '"object": "chat.completion", "created": 1765461372, '
            '"model": "claude-opus-4-5-thinking", "choices": [{"index": 0, '
            '"message": {"role": "assistant", "content": "File operation blocked: '
            'Paths outside project root: /.venv/Scripts/python.exe"}, '
            '"finish_reason": "stop"}], "usage": null}'
        )

        assert protector.has_leak(content) is True

        sanitized, had_leak = protector.sanitize_content(content)
        assert had_leak is True
        # The legitimate content should be preserved
        assert "paths are validated" in sanitized
        # The steering response should be removed
        assert "chatcmpl-steering" not in sanitized

    def test_full_steering_response_structure(self) -> None:
        """Test detection of complete steering response structure."""
        protector = SteeringLeakProtector(log_leaks=False)

        content = """{
            "id": "chatcmpl-steering-1234567890",
            "object": "chat.completion",
            "created": 1234567890,
            "model": "steering-agent",
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "File operation blocked"
                },
                "finish_reason": "stop"
            }],
            "usage": null
        }"""

        assert protector.has_leak(content) is True

        sanitized, had_leak = protector.sanitize_content(content)
        assert had_leak is True
        assert "chatcmpl-steering" not in sanitized

    def test_streaming_sse_with_steering_leak(self) -> None:
        """Test detection in SSE-formatted streaming content."""
        protector = SteeringLeakProtector(log_leaks=False)

        # SSE chunk with leaked steering data
        sse_chunk = (
            b'data: {"id": "chatcmpl-abc", "choices": [{"delta": {"content": '
            b'"Normal text"}}]}\n\n'
            b'data: {"id": "chatcmpl-steering-123", "steering_message": "blocked"}\n\n'
        )

        assert protector.has_leak_bytes(sse_chunk) is True

        sanitized, had_leak = protector.sanitize_bytes(sse_chunk)
        assert had_leak is True
        assert b"chatcmpl-steering" not in sanitized
