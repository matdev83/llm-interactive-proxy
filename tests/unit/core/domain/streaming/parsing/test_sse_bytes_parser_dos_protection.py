"""
Tests for DoS protection in SSEBytesParser.

This test ensures that the parser properly defends against:
1. Large payloads that could cause memory exhaustion
2. Deep nesting that could cause stack overflow
3. While maintaining normal functionality
"""

import json

import pytest
from src.core.domain.streaming.parsing.sse_bytes_parser import SSEBytesParser


class TestSSEBytesParserDoSProtection:
    """Test DoS protection in SSEBytesParser."""

    def test_rejects_large_payloads(self):
        """Test that payloads exceeding size limit are rejected."""
        parser = SSEBytesParser()

        # Create a 15MB payload (exceeds 10MB limit)
        large_json = '{"data": "' + "x" * (15 * 1024 * 1024) + '"}'
        large_payload = f"data: {large_json}".encode()

        with pytest.raises(ValueError, match="too large"):
            parser.parse(large_payload)

    def test_accepts_payloads_under_size_limit(self):
        """Test that payloads under size limit are accepted."""
        parser = SSEBytesParser()

        # Create a 5MB payload (under 10MB limit)
        medium_json = '{"data": "' + "x" * (5 * 1024 * 1024) + '"}'
        medium_payload = f"data: {medium_json}".encode()

        # Should not raise an exception
        result = parser.parse(medium_payload)
        assert result.content == {"data": "x" * (5 * 1024 * 1024)}

    def test_rejects_deeply_nested_json(self):
        """Test that deeply nested JSON is rejected."""
        parser = SSEBytesParser()

        # Create JSON with 150 levels of nesting (exceeds 100 limit)
        nested_obj = {"payload": "data"}
        for _ in range(150):
            nested_obj = {"nested": nested_obj}

        deep_json = json.dumps(nested_obj)
        deep_payload = f"data: {deep_json}".encode()

        with pytest.raises(ValueError, match="too deeply nested"):
            parser.parse(deep_payload)

    def test_accepts_reasonably_nested_json(self):
        """Test that reasonably nested JSON is accepted."""
        parser = SSEBytesParser()

        # Create JSON with 50 levels of nesting (under 100 limit)
        nested_obj = {"payload": "data"}
        for _ in range(50):
            nested_obj = {"nested": nested_obj}

        medium_json = json.dumps(nested_obj)
        medium_payload = f"data: {medium_json}".encode()

        # Should not raise an exception
        result = parser.parse(medium_payload)
        assert result.content == nested_obj

    def test_normal_sse_functionality_preserved(self):
        """Test that normal SSE functionality still works."""
        parser = SSEBytesParser()

        # Test [DONE] marker
        result = parser.parse(b"data: [DONE]")
        assert result.is_done is True

        # Test normal JSON
        test_json = '{"choices": [{"delta": {"content": "hello"}}]}'
        result = parser.parse(f"data: {test_json}".encode())
        assert "hello" in str(result.content)

        # Test plain string
        result = parser.parse(b"plain text")
        assert result.content == "plain text"

    def test_edge_cases_handled_safely(self):
        """Test edge cases are handled safely."""
        parser = SSEBytesParser()

        # Empty payload
        result = parser.parse(b"")
        assert result.content == ""

        # Invalid UTF-8 (should be handled gracefully)
        result = parser.parse(b"\xff\xfe\x00\x00")
        assert result.content == ""

        # Malformed JSON (should fall back to string)
        result = parser.parse(b"data: {invalid json}")
        assert "{invalid json}" in result.content

    def test_size_limits_enforced_for_non_sse_content(self):
        """Test size limits also apply to non-SSE content."""
        parser = SSEBytesParser()

        # Large non-SSE string
        large_string = "x" * (15 * 1024 * 1024)
        large_payload = large_string.encode("utf-8")

        with pytest.raises(ValueError, match="too large"):
            parser.parse(large_payload)

    def test_large_array_json_rejected(self):
        """Test that large JSON arrays are rejected."""
        parser = SSEBytesParser()

        # Create a large JSON array (reduced size for performance while still exceeding limit)
        large_array = [{"id": i, "data": "x" * 400} for i in range(30000)]  # Reduced from 50000 to 30000, increased data size to maintain test coverage
        large_json = json.dumps(large_array)
        large_payload = f"data: {large_json}".encode()

        with pytest.raises(ValueError, match="too large"):
            parser.parse(large_payload)

    def test_deep_array_nesting_rejected(self):
        """Test that deeply nested arrays are rejected."""
        parser = SSEBytesParser()

        # Create deeply nested array structure
        nested_array = ["data"]
        for _ in range(150):
            nested_array = [nested_array]

        deep_json = json.dumps(nested_array)
        deep_payload = f"data: {deep_json}".encode()

        with pytest.raises(ValueError, match="too deeply nested"):
            parser.parse(deep_payload)


class TestSSEBytesParserDepthValidation:
    """Test the depth validation helper methods."""

    def test_depth_validation_limits(self):
        """Test depth validation works correctly."""
        parser = SSEBytesParser()

        # Object exactly at limit should fail
        obj_at_limit = {"level": 0}
        for i in range(100):
            obj_at_limit = {"level": i + 1, "nested": obj_at_limit}

        with pytest.raises(ValueError, match="depth 100 exceeds maximum 100"):
            parser._validate_json_depth(obj_at_limit, 0)

        # Object under limit should pass
        obj_under_limit = {"level": 0}
        for i in range(50):
            obj_under_limit = {"level": i + 1, "nested": obj_under_limit}

        # Should not raise
        parser._validate_json_depth(obj_under_limit, 0)

    def test_depth_validation_handles_mixed_structures(self):
        """Test depth validation works with mixed dict/list structures."""
        parser = SSEBytesParser()

        mixed_structure = {"level1": [{"level2": {"level3": [{"level4": "deep"}]}}]}

        # Should not raise (depth is only 4)
        parser._validate_json_depth(mixed_structure, 0)

        # Create structure that exceeds limit
        deep_mixed = mixed_structure
        for _ in range(100):
            deep_mixed = {"nested": deep_mixed}

        with pytest.raises(ValueError, match="depth 100 exceeds maximum 100"):
            parser._validate_json_depth(deep_mixed, 0)
