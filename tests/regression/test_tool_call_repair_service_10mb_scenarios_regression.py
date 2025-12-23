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
        # Create valid JSON with many small items
        medium_data = {
            "function_call": {
                "name": "test",
                "arguments": {
                    "items": [{"id": i, "value": f"item_{i}"} for i in range(50000)],
                },
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
        large_data = {
            "function_call": {
                "name": "test",
                "arguments": {
                    "items": [
                        {"id": i, "value": "x" * 100} for i in range(800000)
                    ],  # Much larger
                },
            }
        }
        large_payload = json.dumps(large_data)
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
        # Create payload that's approximately just under 10MB
        # Adjust size to account for JSON overhead
        under_data = {
            "function_call": {
                "name": "test",
                "arguments": {
                    "items": [
                        {"id": i, "value": "x" * 40} for i in range(120000)
                    ],  # Just under limit accounting for JSON overhead
                },
            }
        }
        under_payload = json.dumps(under_data)
        under_size_mb = len(under_payload.encode("utf-8")) / (1024 * 1024)

        # Should be under 10MB
        assert under_size_mb < (
            MAX_JSON_PARSE_SIZE / (1024 * 1024)
        ), f"Test payload ({under_size_mb:.2f}MB) should be under 10MB limit"

        result = repair_service.repair_tool_calls(f"```json\n{under_payload}\n```")

        assert result is not None, "Payload just under 10MB should be processed"

    def test_just_over_10mb_rejected(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """Test that payloads just over 10MB are rejected."""
        # Create payload that's approximately just over 10MB
        over_data = {
            "function_call": {
                "name": "test",
                "arguments": {
                    "items": [
                        {"id": i, "value": "x" * 50} for i in range(170000)
                    ],  # Just over limit
                },
            }
        }
        over_payload = json.dumps(over_data)
        over_size_mb = len(over_payload.encode("utf-8")) / (1024 * 1024)

        # Should be over 10MB
        assert over_size_mb > (
            MAX_JSON_PARSE_SIZE / (1024 * 1024)
        ), f"Test payload ({over_size_mb:.2f}MB) should exceed 10MB limit"

        result = repair_service.repair_tool_calls(f"```json\n{over_payload}\n```")

        assert result is None, "Payload just over 10MB should be rejected"

    def test_boundary_conditions(self, repair_service: ToolCallRepairService) -> None:
        """Test boundary conditions around 10MB limit."""
        # Test with payloads at various sizes around the limit
        test_cases = [
            # (size_description, num_items, item_size, should_pass)
            ("very_small", 100, 10, True),
            ("small", 10000, 100, True),
            ("medium", 50000, 100, True),
            ("large_under", 120000, 40, True),  # Adjusted to account for JSON overhead
            ("large_over", 200000, 50, False),
        ]

        for size_desc, num_items, item_size, should_pass in test_cases:
            test_data = {
                "function_call": {
                    "name": "test",
                    "arguments": {
                        "items": [
                            {"id": i, "value": "x" * item_size}
                            for i in range(num_items)
                        ],
                    },
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
