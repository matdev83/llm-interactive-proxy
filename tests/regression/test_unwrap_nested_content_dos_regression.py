"""Regression test for _unwrap_nested_content DoS vulnerability fix.

This test verifies that the _unwrap_nested_content method properly limits
JSON parsing size to prevent DoS attacks.

Fixed: Added MAX_JSON_PARSE_SIZE limit (1MB) before json.loads() call.
"""

import json

import pytest
from src.core.services.tool_call_repair_service import (
    MAX_JSON_PARSE_SIZE,
    ToolCallRepairService,
)

# Mark memory-intensive tests with timeout to prevent hangs
pytestmark = pytest.mark.timeout(60)


class TestUnwrapNestedContentDoSRegression:
    """Regression tests for _unwrap_nested_content DoS vulnerability fix."""

    @pytest.fixture
    def repair_service(self) -> ToolCallRepairService:
        return ToolCallRepairService()

    def create_large_nested_content(self, size_mb: int = 12) -> dict:
        """Create a nested content structure with large JSON string."""
        large_data = {"data": "x" * (size_mb * 1024 * 1024)}
        large_json_string = json.dumps(large_data)
        return {"content": large_json_string}

    def test_large_content_rejected(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """Test that large content strings (>10MB) are rejected."""
        # Test normal content (should work)
        normal_content = {"content": json.dumps({"key": "value"})}
        result = repair_service._unwrap_nested_content(normal_content)
        assert result == {"key": "value"}, "Normal content should be unwrapped"

        # Test large content (should be rejected)
        large_content = self.create_large_nested_content(
            size_mb=12
        )  # 12MB > 10MB limit
        result = repair_service._unwrap_nested_content(large_content)

        # Should return original arguments without unwrapping
        # Check identity first to avoid expensive comparison of large objects
        assert (
            result is large_content
        ), "Large content should be rejected and original returned (identity check)"

        # Fallback to equality check if identity check fails (though it shouldn't)
        if result is not large_content:
            # Verify keys match without comparing the massive content value
            assert result.keys() == large_content.keys()
            # We assume content is the same if keys match and it wasn't unwrapped
            # This avoids crashing pytest with massive string diffs

    def test_content_at_limit_boundary(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """Test content exactly at the size limit."""
        # Create content just under limit (accounting for JSON overhead)
        # Use smaller size to account for JSON encoding overhead
        limit_bytes = (MAX_JSON_PARSE_SIZE // 2) - 100  # Safe margin
        small_data = {"data": "x" * limit_bytes}
        small_json_string = json.dumps(small_data)
        small_content = {"content": small_json_string}

        # Should work if under limit
        if len(small_json_string.encode("utf-8")) <= MAX_JSON_PARSE_SIZE:
            result = repair_service._unwrap_nested_content(small_content)
            assert isinstance(result, dict), "Content under limit should be unwrapped"
            # Verify result content without full string comparison if possible
            assert result["data"] == small_data["data"]

    def test_invalid_json_handled(self, repair_service: ToolCallRepairService) -> None:
        """Test that invalid JSON is handled gracefully."""
        invalid_content = {"content": "{invalid json}"}
        result = repair_service._unwrap_nested_content(invalid_content)

        # Should return original if JSON is invalid
        assert result == invalid_content, "Invalid JSON should return original"

    def test_non_content_pattern_unchanged(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """Test that non-matching patterns are unchanged."""
        # Test with multiple keys (not the pattern)
        multi_key = {"key1": "value1", "key2": "value2"}
        result = repair_service._unwrap_nested_content(multi_key)
        assert result == multi_key, "Non-matching pattern should be unchanged"

        # Test with non-string content
        non_string_content = {"content": 12345}
        result = repair_service._unwrap_nested_content(non_string_content)
        assert result == non_string_content, "Non-string content should be unchanged"

        # Test with non-JSON string
        non_json_content = {"content": "just a string"}
        result = repair_service._unwrap_nested_content(non_json_content)
        assert result == non_json_content, "Non-JSON string should be unchanged"

    def test_max_constant_defined(self) -> None:
        """Test that MAX_JSON_PARSE_SIZE constant is defined correctly."""
        assert (
            MAX_JSON_PARSE_SIZE == 10 * 1024 * 1024
        ), f"MAX_JSON_PARSE_SIZE ({MAX_JSON_PARSE_SIZE}) should be 10MB"
        assert MAX_JSON_PARSE_SIZE > 0, "MAX_JSON_PARSE_SIZE should be positive"

    def test_normal_unwrapping_works(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """Test that normal unwrapping still works."""
        # Test valid nested content
        nested_content = {
            "content": json.dumps({"file_path": "/tmp/test", "data": "content"})
        }
        result = repair_service._unwrap_nested_content(nested_content)

        assert result == {
            "file_path": "/tmp/test",
            "data": "content",
        }, "Valid nested content should be unwrapped correctly"
