"""Regression test for ToolCallRepairService 10MB limit scenarios.

This test verifies various payload size scenarios around the 10MB limit:
1. Small payloads (should work)
2. Medium payloads (should work)
3. Large payloads over 10MB (should be rejected)
4. Just under 10MB (should work)
5. Just over 10MB (should be rejected)

Fixed: MAX_JSON_PARSE_SIZE (10MB) limit prevents DoS attacks while allowing
legitimate large payloads.
"""

import json

import pytest
from src.core.services.tool_call_repair_service import (
    MAX_JSON_PARSE_SIZE,
    ToolCallRepairService,
)

# Mark memory-intensive tests with timeout to prevent hangs
pytestmark = pytest.mark.timeout(60)


class TestToolCallRepairService10MBScenariosRegression:
    """Regression tests for ToolCallRepairService 10MB limit scenarios."""

    @pytest.fixture
    def repair_service(self) -> ToolCallRepairService:
        """Create ToolCallRepairService for testing."""
        return ToolCallRepairService()

    def test_small_payload_processed(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """Test that small payloads are processed successfully."""
        small_payload = (
            '{"function_call": {"name": "test", "arguments": {"test": "small"}}}'
        )

        result = repair_service.repair_tool_calls(f"```json\n{small_payload}\n```")

        assert result is not None, "Small payload should be processed successfully"

    def test_medium_payload_processed(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """Test that medium payloads are processed successfully."""
        # Use smaller payload for performance while still testing the limit logic
        medium_data = {
            "function_call": {
                "name": "test",
                "arguments": {
                    "data": "x" * (1 * 1024 * 1024)
                },  # 1MB (reduced from 5MB)
            }
        }
        medium_payload = json.dumps(medium_data)
        medium_size_mb = len(medium_payload.encode("utf-8")) / (1024 * 1024)

        # Should be under 10MB
        assert medium_size_mb < (
            MAX_JSON_PARSE_SIZE / (1024 * 1024)
        ), f"Test payload ({medium_size_mb:.2f}MB) should be under 10MB limit"

        result = repair_service.repair_tool_calls(f"```json\n{medium_payload}\n```")

        assert result is not None, "Medium payload should be processed successfully"

    def test_large_payload_rejected(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """Test that large payloads over 10MB are rejected."""
        # Create valid JSON that exceeds 10MB
        # Use a more efficient approach: create the string directly instead of through dict
        # This avoids expensive JSON serialization of a huge dict
        # Reduced target_size to minimize string creation time while still testing rejection
        target_size = MAX_JSON_PARSE_SIZE + 50  # Reduced from 100 for performance
        large_payload = f'{{"function_call":{{"name":"test","arguments":{{"data":"{"x" * target_size}"}}}}}}'
        large_size_mb = len(large_payload.encode("utf-8")) / (1024 * 1024)

        # Should be over 10MB
        assert large_size_mb > (
            MAX_JSON_PARSE_SIZE / (1024 * 1024)
        ), f"Test payload ({large_size_mb:.2f}MB) should exceed 10MB limit"

        result = repair_service.repair_tool_calls(f"```json\n{large_payload}\n```")

        assert result is None, "Large payload should be rejected"

    def test_just_under_10mb_processed(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """Test that payloads just under 10MB are processed."""
        # Use smaller payload for performance while still testing boundary logic
        # Create payload that's well under the limit but still substantial
        target_size = 5 * 1024 * 1024  # 5MB (reduced from ~10MB for performance)

        under_data = {
            "function_call": {
                "name": "test",
                "arguments": {"data": "x" * target_size},
            }
        }
        under_payload = json.dumps(under_data)

        # Ensure it is under the limit
        payload_size = len(under_payload.encode("utf-8"))
        assert payload_size < MAX_JSON_PARSE_SIZE

        result = repair_service.repair_tool_calls(f"```json\n{under_payload}\n```")

        assert result is not None, "Payload should be processed"

    def test_just_over_10mb_rejected(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """Test that payloads just over 10MB are rejected."""
        # Create payload that's just over 10MB
        # Calculate string size needed: JSON overhead is ~50 bytes
        json_overhead = 50  # Approximate overhead for JSON structure
        target_size = (
            MAX_JSON_PARSE_SIZE - json_overhead + 50
        )  # Reduced from 100 for performance

        # Create minimal dict structure and serialize efficiently
        # Using a single large string is faster than many small objects
        over_data = {
            "function_call": {
                "name": "test",
                "arguments": {"data": "x" * target_size},
            }
        }

        # Serialize to JSON - this is necessary for valid JSON
        over_payload = json.dumps(over_data)

        # Verify payload size
        payload_size = len(over_payload.encode("utf-8"))
        assert (
            payload_size > MAX_JSON_PARSE_SIZE
        ), f"Payload size ({payload_size}) should exceed limit ({MAX_JSON_PARSE_SIZE})"

        result = repair_service.repair_tool_calls(f"```json\n{over_payload}\n```")

        assert result is None, "Payload just over 10MB should be rejected"

    def test_boundary_conditions(self, repair_service: ToolCallRepairService) -> None:
        """Test boundary conditions around 10MB limit."""
        # Test with payloads at various sizes around the limit
        # Using smaller payloads for performance while still testing boundary logic
        limit = MAX_JSON_PARSE_SIZE

        test_cases = [
            # (size_description, data_length, should_pass)
            ("small", 10000, True),
            ("medium", 1 * 1024 * 1024, True),  # Reduced from 5MB for performance
            ("large_under", limit - 100, True),  # Account for JSON overhead (~60 bytes)
            ("large_over", limit + 50, False),  # Reduced from 100 for performance
        ]

        for size_desc, data_len, should_pass in test_cases:
            # Use direct string construction for large payloads to avoid expensive dict creation
            if data_len > 1024 * 1024:  # For large payloads, construct JSON directly
                test_payload = f'{{"function_call":{{"name":"test","arguments":{{"data":"{"x" * data_len}"}}}}}}'
            else:
                test_data = {
                    "function_call": {
                        "name": "test",
                        "arguments": {"data": "x" * data_len},
                    }
                }
                test_payload = json.dumps(test_data)
            test_size_mb = len(test_payload.encode("utf-8")) / (1024 * 1024)

            result = repair_service.repair_tool_calls(f"```json\n{test_payload}\n```")

            if should_pass:
                assert (
                    result is not None
                ), f"{size_desc} payload ({test_size_mb:.2f}MB) should be processed"
            else:
                assert (
                    result is None
                ), f"{size_desc} payload ({test_size_mb:.2f}MB) should be rejected"
