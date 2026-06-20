"""Regression test for ToolCallRepairService 10MB limit scenarios.

This test verifies various payload size scenarios around the limit:
1. Small payloads (should work)
2. Medium payloads (should work)
3. Large payloads over limit (should be rejected)
4. Just under limit (should work)
5. Just over limit (should be rejected)

Fixed: MAX_JSON_PARSE_SIZE limit prevents DoS attacks while allowing
legitimate large payloads.
"""

from __future__ import annotations

import json
import sys

import pytest
from src.core.services.tool_call_repair_service import (
    MAX_JSON_PARSE_SIZE,
    ToolCallRepairService,
)

# Mark memory-intensive tests with timeout to prevent hangs
pytestmark = pytest.mark.timeout(60)


@pytest.fixture(autouse=True)
def override_max_json_parse_size(monkeypatch: pytest.MonkeyPatch) -> None:
    """Override MAX_JSON_PARSE_SIZE to 10 KB for testing to avoid huge memory/CPU overhead."""
    import src.core.services.tool_call_repair_service as service

    TEST_LIMIT = 10 * 1024  # 10 KB
    monkeypatch.setattr(service, "MAX_JSON_PARSE_SIZE", TEST_LIMIT)

    # Correctly monkeypatch the currently executing test module namespace
    current_mod = sys.modules[__name__]
    monkeypatch.setattr(current_mod, "MAX_JSON_PARSE_SIZE", TEST_LIMIT)


class TestToolCallRepairService10MBScenariosRegression:
    """Regression tests for ToolCallRepairService limit scenarios."""

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
        # Use 1KB payload (under the 10KB limit)
        medium_data = {
            "function_call": {
                "name": "test",
                "arguments": {"data": "x" * (1 * 1024)},  # 1KB
            }
        }
        medium_payload = json.dumps(medium_data)
        medium_size_kb = len(medium_payload.encode("utf-8")) / 1024

        # Should be under the limit
        assert medium_size_kb < (
            MAX_JSON_PARSE_SIZE / 1024
        ), f"Test payload ({medium_size_kb:.2f}KB) should be under limit"

        result = repair_service.repair_tool_calls(f"```json\n{medium_payload}\n```")

        assert result is not None, "Medium payload should be processed successfully"

    def test_large_payload_rejected(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """Test that large payloads over the limit are rejected."""
        # Create valid JSON that exceeds the limit
        target_size = MAX_JSON_PARSE_SIZE + 50
        large_payload = f'{{"function_call":{{"name":"test","arguments":{{"data":"{"x" * target_size}"}}}}}}'
        large_size_kb = len(large_payload.encode("utf-8")) / 1024

        # Should be over the limit
        assert large_size_kb > (
            MAX_JSON_PARSE_SIZE / 1024
        ), f"Test payload ({large_size_kb:.2f}KB) should exceed limit"

        result = repair_service.repair_tool_calls(f"```json\n{large_payload}\n```")

        assert result is None, "Large payload should be rejected"

    def test_just_under_10mb_processed(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """Test that payloads just under the limit are processed."""
        # Create payload that's well under the limit but still substantial (5 KB)
        target_size = 5 * 1024

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
        """Test that payloads just over the limit are rejected."""
        # Create payload that's just over the limit
        json_overhead = 50  # Approximate overhead for JSON structure
        target_size = MAX_JSON_PARSE_SIZE - json_overhead + 50

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

        assert result is None, "Payload just over limit should be rejected"

    def test_boundary_conditions(self, repair_service: ToolCallRepairService) -> None:
        """Test boundary conditions around limit."""
        limit = MAX_JSON_PARSE_SIZE

        test_cases = [
            # (size_description, data_length, should_pass)
            ("small", 100, True),
            ("large_under", limit - 100, True),
            ("large_over", limit + 50, False),
        ]

        for size_desc, data_len, should_pass in test_cases:
            if data_len > 1024:
                test_payload = f'{{"function_call":{{"name":"test","arguments":{{"data":"{"x" * data_len}"}}}}}}'
            else:
                test_data = {
                    "function_call": {
                        "name": "test",
                        "arguments": {"data": "x" * data_len},
                    }
                }
                test_payload = json.dumps(test_data)
            test_size_kb = len(test_payload.encode("utf-8")) / 1024

            result = repair_service.repair_tool_calls(f"```json\n{test_payload}\n```")

            if should_pass:
                assert (
                    result is not None
                ), f"{size_desc} payload ({test_size_kb:.2f}KB) should be processed"
            else:
                assert (
                    result is None
                ), f"{size_desc} payload ({test_size_kb:.2f}KB) should be rejected"
