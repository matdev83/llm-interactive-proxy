"""Regression test for race condition in StreamingMetrics.

This test ensures that concurrent mutations of StreamingMetrics are thread-safe.
"""

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest
from src.core.ports.streaming_metrics import StreamingMetrics


class TestStreamingMetricsConcurrency:
    """Tests for thread-safety of StreamingMetrics mutations."""

    def test_concurrent_increments(self):
        """Test that concurrent increment operations don't cause race conditions."""
        metrics = StreamingMetrics()
        stream_id = "test-stream"

        num_threads = 20
        num_increments = 100

        def increment_chunks_sent():
            for _ in range(num_increments):
                metrics.increment_chunks_sent(stream_id)

        def increment_sentinels():
            for _ in range(num_increments):
                metrics.increment_sentinels_emitted(stream_id)

        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = []
            # Launch threads for incrementing chunks_sent
            for _ in range(num_threads):
                futures.append(executor.submit(increment_chunks_sent))
            # Launch threads for incrementing sentinels
            for _ in range(num_threads):
                futures.append(executor.submit(increment_sentinels))

            for future in as_completed(futures):
                future.result()

        # Verify counts are correct (no lost or duplicated increments)
        global_metrics = metrics.get_global_metrics()
        # Each function runs num_threads * num_increments times
        expected_chunks = num_threads * num_increments
        assert global_metrics["chunks_sent"] == expected_chunks, (
            f"Expected {expected_chunks} chunks_sent, got {global_metrics['chunks_sent']}"
        )
        assert global_metrics["sentinels_emitted"] == expected_chunks, (
            f"Expected {expected_chunks} sentinels_emitted, got {global_metrics['sentinels_emitted']}"
        )
