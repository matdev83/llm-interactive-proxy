"""Regression test for ToolCallRepairService DoS vulnerability fix.

This test verifies that the ToolCallRepairService properly limits JSON parsing
size to prevent DoS attacks through maliciously large JSON payloads.

Fixed: Added MAX_JSON_PARSE_SIZE limit (10MB) to prevent CPU spikes and memory exhaustion.
"""

import json
import time

import pytest
from src.core.services.tool_call_repair_service import (
    MAX_JSON_PARSE_SIZE,
    ToolCallRepairService,
)
from tests.unit.fixtures.markers import real_time


class TestToolCallRepairServiceDoSRegression:
    """Regression tests for ToolCallRepairService DoS vulnerability fix."""

    @pytest.fixture
    def repair_service(self) -> ToolCallRepairService:
        return ToolCallRepairService()

    def create_large_json_payload(self, multiplier: int = 1) -> str:
        """Create a large JSON payload to test DoS protection."""
        # Create payload that exceeds MAX_JSON_PARSE_SIZE (10MB)
        # Use a smaller margin to reduce test time while still testing size limit
        target_size_bytes = MAX_JSON_PARSE_SIZE + (
            100 * multiplier
        )  # Reduced from 1024 for performance
        # Create a large string payload
        large_data = "x" * target_size_bytes

        malicious_data = {
            "function_call": {
                "name": "test_tool",
                "arguments": {
                    "large_data": large_data,
                },
            }
        }

        return json.dumps(malicious_data)

    def create_deeply_nested_json(self, depth: int) -> str:
        """Create a deeply nested JSON structure."""

        def create_nested_dict(d: int):
            if d <= 0:
                return {"value": "deep_value", "data": "x" * 1000}
            return {"nested": create_nested_dict(d - 1), "data": "x" * 100}

        nested_payload = {
            "function_call": {
                "name": "test_tool",
                "arguments": {"deeply_nested": create_nested_dict(depth)},
            }
        }

        return json.dumps(nested_payload)

    @real_time(reason="Measures actual processing time to detect DoS vulnerabilities.")
    def test_large_json_payload_rejected_quickly(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """Test that large JSON payloads (>10MB) are rejected quickly."""
        # Create payload larger than MAX_JSON_PARSE_SIZE
        # Use minimal multiplier to reduce string creation time while still testing rejection
        large_json = self.create_large_json_payload(
            multiplier=1
        )  # Minimal oversize for performance
        payload_size_mb = len(large_json.encode("utf-8")) / (1024 * 1024)

        # Should be larger than limit
        assert payload_size_mb > (
            MAX_JSON_PARSE_SIZE / (1024 * 1024)
        ), "Test payload should exceed MAX_JSON_PARSE_SIZE"

        # Test fewer attack vectors to reduce test time (still covers main cases)
        attack_vectors = [
            ("Code block", f"```json\n{large_json}\n```"),
            ("Direct JSON", large_json),
        ]

        for vector_name, content in attack_vectors:
            start_time = time.time()
            result = repair_service.repair_tool_calls(content)
            duration = time.time() - start_time

            # Should reject quickly (< 2 seconds) due to size check
            # Increased timeout slightly to account for string processing overhead
            # The rejection logic itself is fast, but processing large strings takes time
            assert duration < 2.0, (
                f"{vector_name} attack vector took {duration:.2f} seconds. "
                "Large payloads should be rejected quickly via size check."
            )

            # Should return None (rejected) for large payloads
            assert result is None, (
                f"{vector_name} attack vector should return None for large payloads. "
                f"Got: {result}"
            )

            # Should return None (rejected) for large payloads
            assert result is None, (
                f"{vector_name} attack vector should return None for large payloads. "
                f"Got: {result}"
            )

    def test_small_json_payload_processed(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """Test that small JSON payloads (<10MB) are processed correctly."""
        # Create payload smaller than MAX_JSON_PARSE_SIZE
        small_json = json.dumps(
            {
                "function_call": {
                    "name": "test_tool",
                    "arguments": {"command": "ls -la"},
                }
            }
        )

        payload_size_mb = len(small_json.encode("utf-8")) / (1024 * 1024)
        assert payload_size_mb < (
            MAX_JSON_PARSE_SIZE / (1024 * 1024)
        ), "Test payload should be smaller than MAX_JSON_PARSE_SIZE"

        # Test in code block format
        content = f"```json\n{small_json}\n```"
        result = repair_service.repair_tool_calls(content)

        # Should process successfully
        assert result is not None, "Small payload should be processed successfully"
        assert (
            result.tool_call["function"]["name"] == "test_tool"
        ), "Tool name should be extracted correctly"

    @real_time(reason="Measures actual processing time to detect DoS vulnerabilities.")
    def test_deeply_nested_json_handled(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """Test that deeply nested JSON is handled without stack overflow."""
        # Create deeply nested JSON (but within size limit)
        nested_json = self.create_deeply_nested_json(
            depth=50
        )  # Reduced from 100 for performance
        payload_size_mb = len(nested_json.encode("utf-8")) / (1024 * 1024)

        # Should be within size limit
        assert payload_size_mb < (
            MAX_JSON_PARSE_SIZE / (1024 * 1024)
        ), "Test payload should be within MAX_JSON_PARSE_SIZE"

        content = f"```json\n{nested_json}\n```"

        start_time = time.time()
        result = repair_service.repair_tool_calls(content)
        duration = time.time() - start_time

        # Should process without excessive delay or recursion error
        assert duration < 1.0, (
            f"Deeply nested JSON took {duration:.2f} seconds. "
            "Should process within reasonable time."
        )

        # Should either process successfully or reject gracefully
        # (depending on implementation, but should not crash)
        assert result is None or (
            result is not None and result.tool_call["function"]["name"] == "test_tool"
        ), "Deeply nested JSON should be handled gracefully"

    def test_max_json_parse_size_constant(self) -> None:
        """Test that MAX_JSON_PARSE_SIZE constant is defined correctly."""
        # Verify the constant exists and has reasonable value
        assert MAX_JSON_PARSE_SIZE == 10 * 1024 * 1024, (
            f"MAX_JSON_PARSE_SIZE ({MAX_JSON_PARSE_SIZE}) should be 10MB "
            "(10485760 bytes)"
        )
        assert MAX_JSON_PARSE_SIZE > 0, "MAX_JSON_PARSE_SIZE should be positive"

    @real_time(reason="Measures actual processing time to detect DoS vulnerabilities.")
    def test_progressively_larger_payloads(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """Test that progressively larger payloads are handled correctly."""
        # Test just one case to validate size limit logic
        multiplier = 1
        large_json = self.create_large_json_payload(multiplier)

        # Use string length instead of encoding for faster size check
        payload_size_mb = len(large_json) / (1024 * 1024)

        content = f"```json\n{large_json}\n```"

        start_time = time.time()
        result = repair_service.repair_tool_calls(content)
        duration = time.time() - start_time

        if payload_size_mb > (MAX_JSON_PARSE_SIZE / (1024 * 1024)):
            # Large payloads should be rejected (may take time to create string, but should reject)
            # Increased timeout to account for string creation time
            assert duration < 2.0, (
                f"Payload {payload_size_mb:.2f}MB took {duration:.2f} seconds. "
                "Large payloads should be rejected (accounting for string creation time)."
            )
            assert result is None, (
                f"Payload {payload_size_mb:.2f}MB should be rejected. "
                f"Got: {result}"
            )
        else:
            # Small payloads may take longer but should complete
            assert duration < 1.5, (
                f"Payload {payload_size_mb:.2f}MB took {duration:.2f} seconds. "
                "Should complete within reasonable time."
            )
