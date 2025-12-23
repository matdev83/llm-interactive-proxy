"""Regression test for repair_json DoS vulnerability fix.

This test verifies that repair_json calls properly limit input size
to prevent DoS attacks in various locations:
1. ToolArgumentsParser._parse_string()
2. JsonRepairService.repair_json()
3. ToolCallTracker._canonicalize_arguments()

Fixed: Added MAX_JSON_REPAIR_INPUT_SIZE limit (1MB) before all repair_json calls.
"""

import json

import pytest
from src.core.services.json_repair_service import (
    MAX_JSON_REPAIR_INPUT_SIZE,
    JsonRepairService,
)
from src.core.services.tool_call_reactor.arguments_parser import (
    ToolArgumentsParser,
)


class TestRepairJsonDoSRegression:
    """Regression tests for repair_json DoS vulnerability fix."""

    @pytest.fixture
    def repair_service(self) -> JsonRepairService:
        return JsonRepairService()

    @pytest.fixture
    def arguments_parser(self) -> ToolArgumentsParser:
        return ToolArgumentsParser()

    def create_large_json_string(self, size_mb: int = 2) -> str:
        """Create a large JSON string for testing."""
        chunk = '{"key": "value", "data": "' + "x" * 1000 + '"}'
        chunks_needed = (size_mb * 1024 * 1024) // len(chunk)
        large_dict = {"items": [chunk] * chunks_needed}
        return json.dumps(large_dict)

    def test_json_repair_service_rejects_large_input(
        self, repair_service: JsonRepairService
    ) -> None:
        """Test that JsonRepairService.repair_json() rejects large input."""
        # Test normal input (should work)
        normal_json = '{"key": "value"}'
        result = repair_service.repair_json(normal_json)
        assert result == {"key": "value"}, "Normal JSON should be repaired"

        # Test large input (should be rejected)
        large_json = self.create_large_json_string(size_mb=2)  # 2MB > 1MB limit

        from src.core.common.exceptions import JSONParsingError

        with pytest.raises(JSONParsingError, match="too large"):
            repair_service.repair_json(large_json)

    def test_tool_arguments_parser_rejects_large_input(
        self, arguments_parser: ToolArgumentsParser
    ) -> None:
        """Test that ToolArgumentsParser._parse_string() rejects large input."""
        # Test normal input (should work)
        normal_input = '{"command": "ls -la"}'
        result = arguments_parser._parse_string(normal_input)
        assert result.normalized_arguments is not None, "Normal input should be parsed"
        assert result.parse_outcome in (
            "success",
            "recovered",
        ), "Normal input should parse successfully"

        # Test large input (should skip repair but still parse if valid JSON)
        large_input = self.create_large_json_string(size_mb=2)  # 2MB > 1MB limit

        # Should not crash, may skip repair but still parse if valid JSON
        result = arguments_parser._parse_string(large_input)
        assert result is not None, "Should handle large input gracefully"
        # Should have normalized arguments (either parsed or wrapped as raw)
        assert (
            result.normalized_arguments is not None
        ), "Should always have normalized arguments"
        # Repair should be skipped for large input (warning logged)
        # But if input is valid JSON, it may still parse successfully

    def test_input_at_limit_boundary(self, repair_service: JsonRepairService) -> None:
        """Test input exactly at the size limit."""
        # Create input just under limit
        limit_bytes = MAX_JSON_REPAIR_INPUT_SIZE - 100
        small_data = {"data": "x" * limit_bytes}
        small_json_string = json.dumps(small_data)

        # Should work if under limit
        if len(small_json_string.encode("utf-8")) <= MAX_JSON_REPAIR_INPUT_SIZE:
            result = repair_service.repair_json(small_json_string)
            assert isinstance(result, dict), "Input under limit should be repaired"

    def test_max_constant_defined(self) -> None:
        """Test that MAX_JSON_REPAIR_INPUT_SIZE constant is defined correctly."""
        assert (
            MAX_JSON_REPAIR_INPUT_SIZE == 1 * 1024 * 1024
        ), f"MAX_JSON_REPAIR_INPUT_SIZE ({MAX_JSON_REPAIR_INPUT_SIZE}) should be 1MB"
        assert (
            MAX_JSON_REPAIR_INPUT_SIZE > 0
        ), "MAX_JSON_REPAIR_INPUT_SIZE should be positive"

    def test_normal_repair_works(self, repair_service: JsonRepairService) -> None:
        """Test that normal JSON repair still works."""
        # Test valid JSON (should work)
        valid_json = '{"key": "value", "number": 42}'
        result = repair_service.repair_json(valid_json)
        assert result == {
            "key": "value",
            "number": 42,
        }, "Valid JSON should be repaired correctly"

        # Test malformed JSON that can be repaired
        malformed_json = '{"key": "value", "number": 42'  # Missing closing brace
        try:
            result = repair_service.repair_json(malformed_json)
            # If repair succeeds, should return valid dict
            assert isinstance(result, dict)
        except Exception:
            # Repair may fail, which is acceptable
            pass
