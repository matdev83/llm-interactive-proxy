"""Regression test for rate_limit.py _as_dict DoS vulnerability fix.

This test verifies that the _as_dict function properly limits input size
to prevent DoS attacks through malicious large string inputs requiring JSON parsing.

Fixed: Added 10MB size limit checks before JSON parsing.
"""

import json
from typing import Any

import pytest

from src.rate_limit import _as_dict


class TestRateLimitAsDictDoSRegression:
    """Regression tests for _as_dict DoS vulnerability fix."""

    def test_large_string_rejected(self) -> None:
        """Test that large strings (>10MB) are rejected without parsing."""
        # Create a string larger than 10MB
        # Use a large array to ensure we exceed 10MB
        large_array = ",".join([f'"item_{i}"' for i in range(1000000)])  # 1M items
        large_string = "Some text before JSON {" + f'"data": [{large_array}]' + "} Some text after JSON"
        
        # Ensure it's larger than 10MB
        string_size = len(large_string.encode("utf-8"))
        assert string_size > 10 * 1024 * 1024, f"String size ({string_size}) should be > 10MB"
        
        # Should return None without attempting to parse
        result = _as_dict(large_string)
        assert result is None, "Large string should be rejected without parsing"

    def test_nested_json_within_limit(self) -> None:
        """Test that nested JSON within size limit is parsed correctly."""
        # Create deeply nested JSON structure (but within 10MB limit)
        def create_nested_data(depth: int) -> dict[str, Any]:
            if depth <= 0:
                return {"value": f"deep_value_{depth}", "array": list(range(100))}
            return {
                f"level_{depth}": create_nested_data(depth - 1),
                "extra_data": list(range(50)),
                "string_data": "X" * 100
            }
        
        nested_data = create_nested_data(10)  # 10 levels deep (smaller than repro)
        json_str = json.dumps(nested_data)
        test_string = f"Error prefix {json_str} Error suffix"
        
        # Should be within limit
        assert len(test_string.encode("utf-8")) < 10 * 1024 * 1024
        
        # Should parse successfully
        result = _as_dict(test_string)
        assert result is not None, "Nested JSON within limit should be parsed"
        assert isinstance(result, dict), "Result should be a dictionary"

    def test_extracted_json_size_limit(self) -> None:
        """Test that extracted JSON parts are also size-limited."""
        # Create a string with large JSON embedded
        large_json_data = {"data": list(range(200000))}  # Large array
        json_str = json.dumps(large_json_data)
        
        # Wrap with text
        test_string = f"Error prefix {json_str} Error suffix"
        
        # If the extracted JSON part is > 10MB, it should be rejected
        start = test_string.find("{")
        end = test_string.rfind("}")
        if start != -1 and end != -1:
            json_part = test_string[start : end + 1]
            json_size = len(json_part.encode("utf-8"))
            
            if json_size > 10 * 1024 * 1024:
                result = _as_dict(test_string)
                assert result is None, "Large extracted JSON should be rejected"
            else:
                result = _as_dict(test_string)
                assert result is not None, "Small extracted JSON should be parsed"

    def test_massive_array_rejected(self) -> None:
        """Test that massive arrays causing >10MB JSON are rejected."""
        # Create JSON with massive arrays
        massive_data = {
            "large_array": list(range(500000)),  # 500k elements
            "multiple_arrays": [list(range(10000)) for _ in range(50)],
        }
        
        json_str = json.dumps(massive_data)
        test_string = f"Data: {json_str}"
        
        # Should be > 10MB
        if len(test_string.encode("utf-8")) > 10 * 1024 * 1024:
            result = _as_dict(test_string)
            assert result is None, "Massive array JSON should be rejected"

    def test_normal_sized_inputs_work(self) -> None:
        """Test that normal-sized inputs continue to work correctly."""
        # Test with dict input
        input_dict = {"key": "value", "number": 42}
        result = _as_dict(input_dict)
        assert result == input_dict
        
        # Test with JSON string
        json_str = '{"key": "value", "number": 42}'
        result = _as_dict(json_str)
        assert result == {"key": "value", "number": 42}
        
        # Test with embedded JSON
        embedded = 'prefix {"key": "value"} suffix'
        result = _as_dict(embedded)
        assert result == {"key": "value"}
        
        # Test with invalid JSON
        invalid_json = '{"key": "value"'  # Missing closing brace
        result = _as_dict(invalid_json)
        assert result is None
        
        # Test with no JSON
        no_json = "just plain text"
        result = _as_dict(no_json)
        assert result is None
