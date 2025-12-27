"""Regression test for StreamingResponseAccumulator DoS vulnerability fix.

This test verifies that the StreamingResponseAccumulator properly handles
large JSON payloads in SSE data lines to prevent DoS attacks through
maliciously large JSON payloads.

Fixed: Should add size validation before json.loads() to prevent CPU spikes
and memory exhaustion.
"""

import json
import time

import pytest
from src.connectors.gemini_base.response_accumulator import StreamingResponseAccumulator
from src.core.domain.responses import StreamingResponseEnvelope
from tests.unit.fixtures.markers import real_time


class MockChunk:
    """Mock chunk for testing."""

    def __init__(self, data: bytes):
        self.content = data


class MockStreamingResponse:
    """Mock streaming response for testing."""

    def __init__(self, chunks: list[MockChunk]):
        self.content = chunks
        self.headers = {"content-type": "text/event-stream"}
        self.status_code = 200

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.content:
            raise StopAsyncIteration
        return self.content.pop(0)


class TestStreamingResponseAccumulatorDoSRegression:
    """Regression tests for StreamingResponseAccumulator DoS vulnerability fix."""

    @pytest.fixture
    def accumulator(self) -> StreamingResponseAccumulator:
        return StreamingResponseAccumulator()

    def create_malicious_sse_chunk(self, size_mb: int = 2) -> bytes:
        """Create a malicious SSE chunk with large JSON payload."""
        # Create a very large JSON object
        large_payload = {
            "choices": [
                {
                    "delta": {
                        "content": "A" * (size_mb * 1024 * 1024),  # Large content
                    }
                }
            ],
            "usage": {
                "prompt_tokens": 1000,
                "completion_tokens": 50000,
                "total_tokens": 51000,
            },
            # Add massive nested structure to increase parsing complexity
            "large_array": list(range(100000)),  # 100k elements
            "deep_nested": {
                "level1": {
                    "level2": {
                        "level3": {
                            # Deep nesting that can cause stack issues
                            "data": [{"nested": i} for i in range(10000)]
                        }
                    }
                }
            },
        }

        # Convert to JSON and wrap in SSE format
        json_data = json.dumps(large_payload)
        sse_line = f"data: {json_data}\n"

        return sse_line.encode("utf-8")

    def create_deeply_nested_sse_chunk(self, depth: int = 100) -> bytes:
        """Create an SSE chunk with deeply nested JSON."""

        def create_nested_dict(d: int):
            if d <= 0:
                return {"value": "deep_value", "data": "x" * 1000}
            return {"nested": create_nested_dict(d - 1), "data": "x" * 100}

        nested_payload = {
            "choices": [
                {
                    "delta": {
                        "content": "test",
                    }
                }
            ],
            "deeply_nested": create_nested_dict(depth),
        }

        json_data = json.dumps(nested_payload)
        sse_line = f"data: {json_data}\n"

        return sse_line.encode("utf-8")

    @pytest.mark.asyncio
    @real_time(
        reason="Measures actual processing time to verify DoS protection performance"
    )
    async def test_large_json_payload_handled_quickly(
        self, accumulator: StreamingResponseAccumulator
    ) -> None:
        """Test that large JSON payloads are handled within reasonable time."""
        # Create payload that would cause DoS if not protected
        malicious_chunk = self.create_malicious_sse_chunk(size_mb=2)
        response = MockStreamingResponse([MockChunk(malicious_chunk)])

        start_time = time.time()
        try:
            await accumulator.accumulate(
                StreamingResponseEnvelope(content=response, headers={}, status_code=200)
            )
            duration = time.time() - start_time

            # Should process within reasonable time (< 2 seconds for 2MB payload)
            # If protection is in place, it should reject quickly or process efficiently
            assert duration < 5.0, (
                f"Large payload processing took {duration:.2f} seconds. "
                "Should complete within reasonable time to prevent DoS."
            )

        except Exception:
            duration = time.time() - start_time
            # Errors are acceptable if they occur quickly (protection working)
            # but not if they occur after long processing (DoS vulnerability)
            assert duration < 2.0, (
                f"Exception occurred after {duration:.2f} seconds. "
                "If protection is in place, errors should occur quickly."
            )

    @pytest.mark.asyncio
    @real_time(
        reason="Measures actual processing time to verify DoS protection performance"
    )
    async def test_multiple_large_payloads(
        self, accumulator: StreamingResponseAccumulator
    ) -> None:
        """Test that multiple large payloads are handled correctly."""
        # Create multiple progressively larger payloads (reduced sizes for performance)
        sizes_mb = [1, 5, 10]

        for size_mb in sizes_mb:
            malicious_chunk = self.create_malicious_sse_chunk(size_mb=size_mb)
            response = MockStreamingResponse([MockChunk(malicious_chunk)])

            start_time = time.time()
            try:
                await accumulator.accumulate(
                    StreamingResponseEnvelope(
                        content=response, headers={}, status_code=200
                    )
                )
                duration = time.time() - start_time

                # Processing time should not grow linearly with payload size
                # If protection is working, larger payloads should be rejected quickly
                # or processing should be bounded
                max_expected_time = min(5.0, size_mb * 0.5)  # Reasonable bound
                assert duration < max_expected_time, (
                    f"Payload {size_mb}MB took {duration:.2f} seconds. "
                    f"Should complete within {max_expected_time:.2f} seconds."
                )

            except Exception:
                duration = time.time() - start_time
                # Errors should occur quickly if protection is in place
                assert duration < 2.0, (
                    f"Exception for {size_mb}MB payload occurred after "
                    f"{duration:.2f} seconds. Should fail quickly if protected."
                )

    @pytest.mark.asyncio
    @real_time(
        reason="Measures actual processing time to verify DoS protection performance"
    )
    async def test_deeply_nested_json_handled(
        self, accumulator: StreamingResponseAccumulator
    ) -> None:
        """Test that deeply nested JSON is handled without stack overflow."""
        # Create deeply nested JSON
        nested_chunk = self.create_deeply_nested_sse_chunk(depth=100)
        response = MockStreamingResponse([MockChunk(nested_chunk)])

        start_time = time.time()
        try:
            await accumulator.accumulate(
                StreamingResponseEnvelope(content=response, headers={}, status_code=200)
            )
            duration = time.time() - start_time

            # Should process without excessive delay or recursion error
            assert duration < 2.0, (
                f"Deeply nested JSON took {duration:.2f} seconds. "
                "Should process within reasonable time."
            )

        except RecursionError:
            duration = time.time() - start_time
            # RecursionError indicates vulnerability - should not occur
            pytest.fail(
                f"RecursionError with deeply nested JSON after {duration:.2f} seconds. "
                "This indicates a DoS vulnerability."
            )
        except Exception:
            duration = time.time() - start_time
            # Other errors are acceptable if they occur quickly
            assert duration < 1.0, (
                f"Exception occurred after {duration:.2f} seconds. "
                "Should fail quickly if protected."
            )

    @pytest.mark.asyncio
    async def test_normal_sse_streams_work(
        self, accumulator: StreamingResponseAccumulator
    ) -> None:
        """Test that normal SSE streams work correctly."""
        # Create normal SSE stream
        normal_chunk = b'data: {"choices": [{"delta": {"content": "Hello"}}]}\n'
        response = MockStreamingResponse([MockChunk(normal_chunk)])

        result = await accumulator.accumulate(
            StreamingResponseEnvelope(content=response, headers={}, status_code=200)
        )

        # Should process successfully
        assert result is not None, "Normal SSE stream should be processed successfully"
        assert result.status_code == 200, "Should return success status"

    @pytest.mark.asyncio
    @real_time(
        reason="Measures actual processing time to verify DoS protection performance"
    )
    async def test_edge_cases_handled(
        self, accumulator: StreamingResponseAccumulator
    ) -> None:
        """Test edge cases that might trigger vulnerabilities."""
        edge_cases = [
            # Deeply nested JSON
            json.dumps(
                {
                    "a": {
                        "b": {
                            "c": {
                                "d": {
                                    "e": {
                                        "f": {"g": {"h": {"i": {"j": {"k": "deep"}}}}}
                                    }
                                }
                            }
                        }
                    }
                }
            ),
            # Massive array
            json.dumps({"large_array": list(range(50000))}),
            # Many small objects
            json.dumps(
                {"objects": [{"id": i, "data": f"item_{i}"} for i in range(10000)]}
            ),
            # Wide object with many keys
            json.dumps({f"key_{i}": f"value_{i}" for i in range(1000)}),
        ]

        for i, json_data in enumerate(edge_cases, 1):
            sse_line = f"data: {json_data}\n"
            response = MockStreamingResponse([MockChunk(sse_line.encode("utf-8"))])

            start_time = time.time()
            try:
                await accumulator.accumulate(
                    StreamingResponseEnvelope(
                        content=response, headers={}, status_code=200
                    )
                )
                duration = time.time() - start_time

                # Should process within reasonable time
                assert duration < 1.0, (
                    f"Edge case {i} took {duration:.2f} seconds. "
                    "Should process within reasonable time."
                )

            except Exception:
                duration = time.time() - start_time
                # Errors should occur quickly
                assert duration < 0.5, (
                    f"Edge case {i} failed after {duration:.2f} seconds. "
                    "Should fail quickly if protected."
                )
