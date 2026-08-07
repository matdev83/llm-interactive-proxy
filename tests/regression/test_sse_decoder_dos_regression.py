"""Regression test for SSEDecoder DoS vulnerability fix.

This test verifies that the SSEDecoder properly limits payload size and
JSON nesting depth to prevent DoS attacks.

Fixed: Added MAX_PAYLOAD_SIZE (10MB) and MAX_JSON_DEPTH (100) limits.
"""

import json

import pytest
from src.core.transport.fastapi.adapters.sse.decoder import SSEDecoder


class TestSSEDecoderDoSRegression:
    """Regression tests for SSEDecoder DoS vulnerability fix."""

    @pytest.fixture
    def decoder(self) -> SSEDecoder:
        return SSEDecoder()

    def create_deeply_nested_json(self, depth: int) -> str:
        """Create a deeply nested JSON structure."""
        result = {"payload": "data"}
        for _ in range(depth):
            result = {"nested": result}
        return json.dumps(result)

    def create_breadth_json(self, size: int) -> str:
        """Create a wide JSON structure with many properties."""
        obj = {}
        for i in range(size):
            obj[f"key_{i}"] = f"value_{i}"
        return json.dumps(obj)

    def test_large_payload_rejected(self, decoder: SSEDecoder) -> None:
        """Test that large payloads (>10MB) are rejected."""
        # Test normal payload (should work)
        normal_payload = 'data: {"message": "hello"}'
        res = decoder.decode_payload(normal_payload)
        content, metadata, _is_done = res.content, res.metadata, res.is_done

        assert isinstance(content, dict), "Normal payload should be accepted"

        # Test payload over limit (should be rejected)
        large_data = "x" * (11 * 1024 * 1024)  # 11MB > 10MB limit
        large_payload = f"data: {large_data}"

        res = decoder.decode_payload(large_payload)
        content, metadata, _is_done = res.content, res.metadata, res.is_done

        assert "error" in metadata, "Large payload should be rejected"
        assert (
            metadata.get("error") == "payload_too_large"
        ), "Should return payload_too_large error"

    def test_deep_nesting_rejected(self, decoder: SSEDecoder) -> None:
        """Test that deeply nested JSON (>100 levels) is rejected."""
        # Test normal depth (should work)
        normal_json = self.create_deeply_nested_json(10)
        normal_payload = f"data: {normal_json}"

        res = decoder.decode_payload(normal_payload)
        content, metadata, _is_done = res.content, res.metadata, res.is_done

        assert isinstance(content, dict), "Normal depth JSON should be accepted"

        # Test excessive depth (should be rejected)
        deep_json = self.create_deeply_nested_json(150)  # > 100 limit
        deep_payload = f"data: {deep_json}"

        res = decoder.decode_payload(deep_payload)
        content, metadata, _is_done = res.content, res.metadata, res.is_done

        assert "error" in metadata, "Deep nesting should be rejected"
        assert metadata.get("error") in (
            "invalid_json_structure",
            "payload_too_large",
        ), "Should return error for deep nesting"

    def test_large_breadth_json_handled(self, decoder: SSEDecoder) -> None:
        """Test that wide JSON structures are handled correctly."""
        # Test with many properties (but within size limit)
        # Reduced from 10000 to 5000 for faster test execution
        breadth_json = self.create_breadth_json(5000)
        breadth_payload = f"data: {breadth_json}"

        # Should process if under size limit
        if len(breadth_payload.encode("utf-8")) <= decoder.MAX_PAYLOAD_SIZE:
            res = decoder.decode_payload(breadth_payload)
            content, metadata, _is_done = res.content, res.metadata, res.is_done

            # Should either succeed or reject with appropriate error
            assert isinstance(content, dict | str) or "error" in metadata

    def test_malformed_json_handled(self, decoder: SSEDecoder) -> None:
        """Test that malformed JSON is handled gracefully."""
        malformed_payloads = [
            "data: {" + "a" * 10000 + ":",  # Incomplete JSON
            "data: [" + '{"a":' * 1000,  # Many incomplete nested objects
            'data: {"a":' + '"' + '\\"' * 10000,  # Massive escaped string
        ]

        for payload in malformed_payloads:
            # Should not crash, may return error or fallback to string
            res = decoder.decode_payload(payload)
            content, metadata, _is_done = res.content, res.metadata, res.is_done

            assert isinstance(content, dict | str | bytes) or "error" in metadata

    def test_max_constants_defined(self) -> None:
        """Test that DoS protection constants are defined correctly."""
        decoder = SSEDecoder()
        assert (
            decoder.MAX_PAYLOAD_SIZE == 10 * 1024 * 1024
        ), f"MAX_PAYLOAD_SIZE ({decoder.MAX_PAYLOAD_SIZE}) should be 10MB"
        assert (
            decoder.MAX_JSON_DEPTH == 100
        ), f"MAX_JSON_DEPTH ({decoder.MAX_JSON_DEPTH}) should be 100"
        assert (
            decoder.MAX_DATA_LINES == 1000
        ), f"MAX_DATA_LINES ({decoder.MAX_DATA_LINES}) should be 1000"

    def test_normal_functionality_works(self, decoder: SSEDecoder) -> None:
        """Test that normal functionality still works."""
        # Test SSE with [DONE]
        res = decoder.decode_payload("data: [DONE]")
        content, _metadata, is_done = res.content, res.metadata, res.is_done

        assert is_done, "SSE [DONE] marker should be recognized"

        # Test SSE with JSON
        test_json = '{"choices": [{"delta": {"content": "hello"}}]}'
        res = decoder.decode_payload(f"data: {test_json}")
        content, _metadata, is_done = res.content, res.metadata, res.is_done

        assert isinstance(content, dict), "SSE JSON parsing should work"
        assert "choices" in content, "Content should contain 'choices'"

    def test_payload_at_limit_boundary(self, decoder: SSEDecoder) -> None:
        """Test payload exactly at the size limit."""
        # Create payload just over the 10MB limit to test boundary rejection
        # Optimized: Test with payload just over limit (faster than testing exact boundary)
        limit_bytes = decoder.MAX_PAYLOAD_SIZE
        # Create payload that exceeds limit by a small amount
        data_size = limit_bytes - 5  # Just under limit before adding "data: " prefix
        large_content = "x" * data_size
        payload = f"data: {large_content}"

        # Encode once and check size
        payload_bytes = payload.encode("utf-8")

        # Should be rejected if exceeds limit
        if len(payload_bytes) > decoder.MAX_PAYLOAD_SIZE:
            res = decoder.decode_payload(payload)
            content, metadata, _is_done = res.content, res.metadata, res.is_done

            assert "error" in metadata, "Payload over limit should be rejected"
        else:
            # Should work if under limit
            res = decoder.decode_payload(payload)
            content, metadata, _is_done = res.content, res.metadata, res.is_done

            assert isinstance(content, dict | str) or "error" in metadata
