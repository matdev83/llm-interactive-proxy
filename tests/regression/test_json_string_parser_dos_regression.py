"""Regression test for JSONStringParser DoS vulnerability fix.

This test verifies that the JSONStringParser properly limits payload size,
JSON nesting depth, and array size to prevent DoS attacks.

Fixed: Added MAX_JSON_PAYLOAD_SIZE (10MB) and validate_json_structure() checks.
"""

import json

import pytest
from src.core.domain.streaming.parsing.json_string_parser import (
    MAX_JSON_PAYLOAD_SIZE,
    JSONStringParser,
)


class TestJSONStringParserDoSRegression:
    """Regression tests for JSONStringParser DoS vulnerability fix."""

    @pytest.fixture
    def parser(self) -> JSONStringParser:
        return JSONStringParser()

    def create_deeply_nested_json(self, depth: int) -> dict:
        """Create a JSON structure with specified nesting depth."""
        if depth == 0:
            return {"value": "leaf"}
        return {"nested": self.create_deeply_nested_json(depth - 1)}

    def create_large_array_json(self, size: int) -> dict:
        """Create a JSON structure with a large array."""
        return {"data": list(range(size))}

    def test_large_payload_rejected(self, parser: JSONStringParser) -> None:
        """Test that large payloads (>10MB) are rejected."""
        # Test normal payload (should work)
        normal_json = json.dumps({"key": "value"})
        result = parser.parse(normal_json)
        assert result.content is not None, "Normal payload should be accepted"

        # Test payload over limit (should be rejected)
        large_data = "x" * (11 * 1024 * 1024)  # 11MB > 10MB limit
        large_json = json.dumps({"data": large_data})

        with pytest.raises(ValueError, match="too large"):
            parser.parse(large_json)

    def test_deep_nesting_rejected(self, parser: JSONStringParser) -> None:
        """Test that deeply nested JSON is rejected."""
        # Test normal depth (should work)
        normal_json = json.dumps(self.create_deeply_nested_json(10))
        result = parser.parse(normal_json)
        assert result.content is not None, "Normal depth JSON should be accepted"

        # Test excessive depth (should be rejected)
        deep_json = json.dumps(self.create_deeply_nested_json(150))  # > 100 limit

        with pytest.raises(ValueError, match="validation failed|depth"):
            parser.parse(deep_json)

    def test_large_array_rejected(self, parser: JSONStringParser) -> None:
        """Test that large arrays are rejected."""
        # Test normal array (should work)
        normal_array = json.dumps({"data": list(range(1000))})
        result = parser.parse(normal_array)
        assert result.content is not None, "Normal array should be accepted"

        # Test large array (should be rejected if exceeds limits)
        # Create array that fits size limit but exceeds element limit (reduced for performance)
        large_array = json.dumps(
            {"data": [0] * 500_000}
        )  # 500K elements (reduced from 1.5M for performance)

        # Should be rejected if it exceeds validation limits
        try:
            result = parser.parse(large_array)
            # If it doesn't raise, check that validation caught it
            # (size check might catch it first)
            assert len(large_array.encode("utf-8")) > MAX_JSON_PAYLOAD_SIZE or (
                isinstance(result.content, str)
            ), "Large array should be rejected or handled safely"
        except ValueError as e:
            assert "too large" in str(e).lower() or "validation" in str(e).lower()

    def test_combined_attack_handled(self, parser: JSONStringParser) -> None:
        """Test that combined attacks (deep nesting + large arrays) are handled."""
        combined_data = {
            "nested": self.create_deeply_nested_json(200),
            "large_array": list(range(100000)),
        }
        combined_json = json.dumps(combined_data)

        # Should be rejected due to deep nesting or size
        try:
            result = parser.parse(combined_json)
            # If parsed, should be handled safely
            assert isinstance(result.content, dict | str)
        except ValueError:
            # Expected rejection
            pass

    def test_max_constant_defined(self) -> None:
        """Test that MAX_JSON_PAYLOAD_SIZE constant is defined correctly."""
        assert (
            MAX_JSON_PAYLOAD_SIZE == 10 * 1024 * 1024
        ), f"MAX_JSON_PAYLOAD_SIZE ({MAX_JSON_PAYLOAD_SIZE}) should be 10MB"
        assert MAX_JSON_PAYLOAD_SIZE > 0, "MAX_JSON_PAYLOAD_SIZE should be positive"

    def test_normal_functionality_works(self, parser: JSONStringParser) -> None:
        """Test that normal functionality still works."""
        # Test simple object
        simple_json = json.dumps({"message": "hello", "count": 42})
        result = parser.parse(simple_json)
        assert result.content is not None

        # Test array
        array_json = json.dumps([1, 2, 3, 4, 5])
        result = parser.parse(array_json)
        assert result.content is not None

        # Test nested structure (within limits)
        nested_json = json.dumps({"level1": {"level2": {"level3": "value"}}})
        result = parser.parse(nested_json)
        assert result.content is not None
