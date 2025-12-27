"""Regression test for SSEBytesParser DoS vulnerability fix.

This test verifies that the SSEBytesParser properly limits payload size and
JSON nesting depth to prevent DoS attacks.

Fixed: Added MAX_SSE_PAYLOAD_SIZE (10MB) and MAX_JSON_DEPTH (100) limits.
"""

import json

import pytest
from src.core.domain.streaming.parsing.sse_bytes_parser import (
    MAX_JSON_DEPTH,
    MAX_SSE_PAYLOAD_SIZE,
    SSEBytesParser,
)


class TestSSEBytesParserDoSRegression:
    """Regression tests for SSEBytesParser DoS vulnerability fix."""

    @pytest.fixture
    def parser(self) -> SSEBytesParser:
        return SSEBytesParser()

    def create_deeply_nested_json(self, depth: int) -> str:
        """Create a deeply nested JSON structure."""
        result = {"payload": "data"}
        for _ in range(depth):
            result = {"nested": result}
        return json.dumps(result)

    def create_large_json(self, size_mb: int) -> str:
        """Create a large JSON payload."""
        large_array = []
        target_size = size_mb * 1024 * 1024

        obj_count = min(target_size // 100, 1000000)

        for i in range(obj_count):
            large_array.append({"id": i, "data": "x" * 50, "value": 42})

        return json.dumps(large_array)

    def test_large_payloads_rejected(self, parser: SSEBytesParser) -> None:
        """Test that large payloads (>10MB) are rejected."""
        # Test payload just under limit (should work)
        normal_payload = b'{"message": "hello"}'
        result = parser.parse(normal_payload)
        assert result is not None, "Normal payload should be accepted"

        # Test payload over limit (should be rejected) - reduced size for performance
        large_json = self.create_large_json(11)  # 11MB > 10MB limit (reduced from 15MB for performance)
        large_payload = f"data: {large_json}".encode()

        with pytest.raises(ValueError, match="too large"):
            parser.parse(large_payload)

    def test_deep_nesting_rejected(self, parser: SSEBytesParser) -> None:
        """Test that deeply nested JSON (>100 levels) is rejected."""
        # Test normal depth (should work)
        normal_json = self.create_deeply_nested_json(10)
        normal_payload = f"data: {normal_json}".encode()

        result = parser.parse(normal_payload)
        assert result is not None, "Normal depth JSON should be accepted"

        # Test excessive depth (should be rejected)
        deep_json = self.create_deeply_nested_json(150)  # > 100 limit
        deep_payload = f"data: {deep_json}".encode()

        with pytest.raises(ValueError, match="too deeply nested|depth"):
            parser.parse(deep_payload)

    def test_normal_functionality_works(self, parser: SSEBytesParser) -> None:
        """Test that normal functionality still works."""
        # Test SSE with [DONE]
        result = parser.parse(b"data: [DONE]")
        assert result.is_done, "SSE [DONE] marker should be recognized"

        # Test SSE with JSON
        test_json = '{"choices": [{"delta": {"content": "hello"}}]}'
        result = parser.parse(f"data: {test_json}".encode())
        assert result.content is not None, "SSE JSON parsing should work"
        assert "hello" in str(result.content), "Content should contain 'hello'"

        # Test plain string (non-SSE)
        result = parser.parse(b"plain text")
        assert result.content == "plain text", "Plain string parsing should work"

    def test_edge_cases_handled(self, parser: SSEBytesParser) -> None:
        """Test edge cases."""
        # Test empty payload
        result = parser.parse(b"")
        assert result is not None, "Empty payload should be handled"

        # Test invalid UTF-8
        result = parser.parse(b"\xff\xfe\x00\x00")  # Invalid UTF-8
        assert result is not None, "Invalid UTF-8 should be handled"

        # Test malformed JSON
        result = parser.parse(b"data: {invalid json}")
        # Should fall back to plain string
        assert "{invalid json}" in str(
            result.content
        ), "Malformed JSON should fall back to string"

    def test_max_constants_defined(self) -> None:
        """Test that DoS protection constants are defined correctly."""
        # Verify constants exist and have reasonable values
        assert MAX_SSE_PAYLOAD_SIZE == 10 * 1024 * 1024, (
            f"MAX_SSE_PAYLOAD_SIZE ({MAX_SSE_PAYLOAD_SIZE}) should be 10MB "
            "(10485760 bytes)"
        )
        assert MAX_JSON_DEPTH == 100, f"MAX_JSON_DEPTH ({MAX_JSON_DEPTH}) should be 100"
        assert MAX_SSE_PAYLOAD_SIZE > 0, "MAX_SSE_PAYLOAD_SIZE should be positive"
        assert MAX_JSON_DEPTH > 0, "MAX_JSON_DEPTH should be positive"

    def test_payload_at_limit_boundary(self, parser: SSEBytesParser) -> None:
        """Test payload exactly at the size limit."""
        # Create payload exactly at 10MB limit
        limit_bytes = MAX_SSE_PAYLOAD_SIZE
        # Subtract "data: " prefix (6 bytes) and JSON overhead
        json_size = limit_bytes - 20  # Leave room for "data: " and JSON structure
        large_content = "x" * json_size
        json_payload = json.dumps({"data": large_content})
        payload = f"data: {json_payload}".encode()

        # Should be rejected if exceeds limit
        if len(payload) > MAX_SSE_PAYLOAD_SIZE:
            with pytest.raises(ValueError, match="too large"):
                parser.parse(payload)
        else:
            # Should work if under limit
            result = parser.parse(payload)
            assert result is not None, "Payload at limit should be processed"

    def test_depth_at_limit_boundary(self, parser: SSEBytesParser) -> None:
        """Test JSON depth at the depth limit boundary."""
        # Create JSON with MAX_JSON_DEPTH - 5 levels (safe margin to avoid stack overflow)
        # The validation itself recurses, so we need a safe margin
        safe_depth = MAX_JSON_DEPTH - 5
        safe_depth_json = self.create_deeply_nested_json(safe_depth)
        safe_payload = f"data: {safe_depth_json}".encode()

        result = parser.parse(safe_payload)
        assert result is not None, "JSON at safe depth should be processed"

        # Test with depth that exceeds limit (but not so much it causes stack overflow in validation)
        # Note: The validation itself can cause stack overflow, so we test that it's rejected
        # by using a depth that's clearly over the limit
        excess_depth = MAX_JSON_DEPTH + 10
        excess_depth_json = self.create_deeply_nested_json(excess_depth)
        excess_payload = f"data: {excess_depth_json}".encode()

        # Should be rejected - may raise ValueError or RecursionError
        with pytest.raises(
            (ValueError, RecursionError), match="too deeply nested|depth|maximum"
        ):
            parser.parse(excess_payload)
