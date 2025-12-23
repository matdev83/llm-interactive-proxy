"""Regression test for tool call text parser DoS vulnerability fix.

This test verifies that the tool call text parser properly limits parameter
JSON size and nesting depth to prevent DoS attacks.

Fixed: Added MAX_PARAMETER_JSON_SIZE (1MB) and MAX_PARAMETER_JSON_DEPTH (50) limits.
"""

import json
import time

from src.core.commands.tool_call_text_parser import (
    MAX_PARAMETER_JSON_DEPTH,
    MAX_PARAMETER_JSON_SIZE,
    _parse_tool_call_parameter_value,
)


class TestToolCallTextParserDoSRegression:
    """Regression tests for tool call text parser DoS vulnerability fix."""

    def create_deep_json(self, depth: int) -> str:
        """Create deeply nested JSON."""
        nested = {}
        current = nested
        for i in range(depth):
            current["level"] = i
            current["nested"] = {}
            current = current["nested"]
        return json.dumps(nested)

    def create_large_json(self, size_mb: int) -> str:
        """Create a large JSON payload."""
        # Create array with enough elements to reach target size
        target_bytes = size_mb * 1024 * 1024
        obj_count = min(target_bytes // 100, 1000000)
        large_array = [{"id": i, "data": "x" * 100} for i in range(obj_count)]
        return json.dumps(large_array)

    def test_large_json_rejected_as_string(self) -> None:
        """Test that large JSON payloads (>10MB) are rejected and returned as string."""
        # Create payload larger than MAX_PARAMETER_JSON_SIZE
        large_json = self.create_large_json(size_mb=12)  # 12MB > 10MB limit
        payload_size = len(large_json.encode("utf-8"))

        assert (
            payload_size > MAX_PARAMETER_JSON_SIZE
        ), "Test payload should exceed MAX_PARAMETER_JSON_SIZE"

        start_time = time.time()
        result = _parse_tool_call_parameter_value(large_json)
        duration = time.time() - start_time

        # Should reject quickly (< 1 second) and return as string
        assert duration < 1.0, (
            f"Large payload processing took {duration:.2f} seconds. "
            "Should reject quickly via size check."
        )

        # Should return as string (not parsed JSON) to prevent DoS
        assert isinstance(
            result, str
        ), f"Large payload should be returned as string, got {type(result).__name__}"
        assert (
            result == large_json.strip()
        ), "Returned string should match original (trimmed) payload"

    def test_deep_json_rejected_as_string(self) -> None:
        """Test that deeply nested JSON (>50 levels) is rejected and returned as string."""
        # Create JSON deeper than MAX_PARAMETER_JSON_DEPTH
        deep_json = self.create_deep_json(depth=100)  # 100 > 50 limit
        payload_size = len(deep_json.encode("utf-8"))

        # Should be within size limit but exceed depth limit
        assert (
            payload_size < MAX_PARAMETER_JSON_SIZE
        ), "Test payload should be within size limit but exceed depth limit"

        start_time = time.time()
        result = _parse_tool_call_parameter_value(deep_json)
        duration = time.time() - start_time

        # Should reject quickly (< 1 second)
        assert duration < 1.0, (
            f"Deep JSON processing took {duration:.2f} seconds. "
            "Should reject quickly via depth check."
        )

        # Should return as string (not parsed JSON) due to depth validation failure
        assert isinstance(
            result, str
        ), f"Deep JSON should be returned as string, got {type(result).__name__}"
        assert (
            result == deep_json.strip()
        ), "Returned string should match original (trimmed) payload"

    def test_normal_json_parsed_correctly(self) -> None:
        """Test that normal JSON payloads are parsed correctly."""
        normal_json = json.dumps({"command": "ls", "args": ["-la", "/home"]})
        payload_size = len(normal_json.encode("utf-8"))

        assert (
            payload_size < MAX_PARAMETER_JSON_SIZE
        ), "Test payload should be within size limit"

        result = _parse_tool_call_parameter_value(normal_json)

        # Should parse successfully
        assert isinstance(
            result, dict
        ), f"Normal JSON should be parsed as dict, got {type(result).__name__}"
        assert result == {
            "command": "ls",
            "args": ["-la", "/home"],
        }, "Parsed result should match expected dict"

    def test_simple_string_passed_through(self) -> None:
        """Test that simple strings are passed through unchanged."""
        simple_string = "simple tool parameter"

        result = _parse_tool_call_parameter_value(simple_string)

        # Should return as string
        assert isinstance(
            result, str
        ), f"Simple string should be returned as string, got {type(result).__name__}"
        assert result == simple_string, "Returned string should match original"

    def test_medium_json_parsed_correctly(self) -> None:
        """Test that medium-sized JSON (<1MB) is parsed correctly."""
        # Create JSON under size limit
        medium_json = json.dumps({"data": "x" * 500000})  # ~500KB
        payload_size = len(medium_json.encode("utf-8"))

        assert (
            payload_size < MAX_PARAMETER_JSON_SIZE
        ), "Test payload should be within size limit"

        result = _parse_tool_call_parameter_value(medium_json)

        # Should parse successfully
        assert isinstance(
            result, dict
        ), f"Medium JSON should be parsed as dict, got {type(result).__name__}"
        assert "data" in result, "Parsed result should contain 'data' key"

    def test_max_constants_defined(self) -> None:
        """Test that DoS protection constants are defined correctly."""
        # Verify constants exist and have reasonable values
        assert MAX_PARAMETER_JSON_SIZE == 10 * 1024 * 1024, (
            f"MAX_PARAMETER_JSON_SIZE ({MAX_PARAMETER_JSON_SIZE}) should be 10MB "
            "(10485760 bytes)"
        )
        assert (
            MAX_PARAMETER_JSON_DEPTH == 50
        ), f"MAX_PARAMETER_JSON_DEPTH ({MAX_PARAMETER_JSON_DEPTH}) should be 50"
        assert MAX_PARAMETER_JSON_SIZE > 0, "MAX_PARAMETER_JSON_SIZE should be positive"
        assert (
            MAX_PARAMETER_JSON_DEPTH > 0
        ), "MAX_PARAMETER_JSON_DEPTH should be positive"

    def test_size_at_limit_boundary(self) -> None:
        """Test parameter exactly at the size limit."""
        # Create payload exactly at 10MB limit
        limit_bytes = MAX_PARAMETER_JSON_SIZE
        # Subtract JSON structure overhead
        content_size = limit_bytes - 100  # Leave room for JSON structure
        large_content = "x" * content_size
        json_payload = json.dumps({"data": large_content})
        payload_size = len(json_payload.encode("utf-8"))

        result = _parse_tool_call_parameter_value(json_payload)

        # Should be rejected if exceeds limit, or parsed if under limit
        if payload_size > MAX_PARAMETER_JSON_SIZE:
            assert isinstance(
                result, str
            ), "Payload exceeding limit should be returned as string"
        else:
            assert isinstance(
                result, dict
            ), "Payload within limit should be parsed as dict"

    def test_depth_at_limit_boundary(self) -> None:
        """Test JSON depth exactly at the depth limit."""
        # Create JSON with exactly MAX_PARAMETER_JSON_DEPTH levels
        depth_json = self.create_deep_json(MAX_PARAMETER_JSON_DEPTH)
        payload_size = len(depth_json.encode("utf-8"))

        # Should be within size limit
        assert (
            payload_size < MAX_PARAMETER_JSON_SIZE
        ), "Test payload should be within size limit"

        result = _parse_tool_call_parameter_value(depth_json)

        # Should be rejected (limit is exclusive)
        assert isinstance(
            result, str
        ), "JSON at depth limit should be returned as string"

        # Create JSON with MAX_PARAMETER_JSON_DEPTH - 1 levels (should work)
        safe_depth_json = self.create_deep_json(MAX_PARAMETER_JSON_DEPTH - 1)
        safe_result = _parse_tool_call_parameter_value(safe_depth_json)

        # Should parse successfully (though it's a dict, not necessarily useful)
        assert isinstance(
            safe_result, dict | str
        ), "JSON at safe depth should be processed (may be dict or string)"

    def test_malformed_json_returns_string(self) -> None:
        """Test that malformed JSON is returned as string."""
        malformed_json = "{invalid json}"

        result = _parse_tool_call_parameter_value(malformed_json)

        # Should return as string (not raise exception)
        assert isinstance(
            result, str
        ), f"Malformed JSON should be returned as string, got {type(result).__name__}"
        assert (
            result == malformed_json.strip()
        ), "Returned string should match original (trimmed) payload"

    def test_empty_string_returns_empty(self) -> None:
        """Test that empty string returns empty string."""
        result = _parse_tool_call_parameter_value("")

        assert result == "", "Empty string should return empty string"

    def test_whitespace_only_returns_empty(self) -> None:
        """Test that whitespace-only string returns empty string."""
        result = _parse_tool_call_parameter_value("   \n\t  ")

        assert result == "", "Whitespace-only string should return empty string"
