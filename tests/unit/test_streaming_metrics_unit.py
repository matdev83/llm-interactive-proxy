"""
Unit tests for streaming metrics infrastructure.

This module tests the StreamingMetrics and StreamingSampler classes
to ensure they correctly track metrics and samples.
"""

import time

from src.core.ports.streaming_metrics import (
    StreamingMetrics,
    StreamingSampler,
    get_metrics_instance,
    get_sampler_instance,
    reset_metrics,
    reset_sampler,
)


class TestStreamingMetrics:
    """Unit tests for StreamingMetrics class."""

    def test_increment_chunks_sent(self) -> None:
        """Test incrementing chunks_sent counter."""
        metrics = StreamingMetrics()
        stream_id = "test_stream_1"

        # Increment for specific stream
        metrics.increment_chunks_sent(stream_id)
        metrics.increment_chunks_sent(stream_id)

        # Check stream metrics
        stream_metrics = metrics.get_stream_metrics(stream_id)
        assert stream_metrics["chunks_sent"] == 2

        # Check global metrics
        global_metrics = metrics.get_global_metrics()
        assert global_metrics["chunks_sent"] == 2

    def test_increment_sentinels_emitted(self) -> None:
        """Test incrementing sentinels_emitted counter."""
        metrics = StreamingMetrics()
        stream_id = "test_stream_2"

        metrics.increment_sentinels_emitted(stream_id)

        stream_metrics = metrics.get_stream_metrics(stream_id)
        assert stream_metrics["sentinels_emitted"] == 1

        global_metrics = metrics.get_global_metrics()
        assert global_metrics["sentinels_emitted"] == 1

    def test_increment_middleware_mutations(self) -> None:
        """Test incrementing middleware_mutations counter."""
        metrics = StreamingMetrics()
        stream_id = "test_stream_3"

        metrics.increment_middleware_mutations(stream_id)
        metrics.increment_middleware_mutations(stream_id)
        metrics.increment_middleware_mutations(stream_id)

        stream_metrics = metrics.get_stream_metrics(stream_id)
        assert stream_metrics["middleware_mutations"] == 3

        global_metrics = metrics.get_global_metrics()
        assert global_metrics["middleware_mutations"] == 3

    def test_increment_error_terminations(self) -> None:
        """Test incrementing error_terminations counter."""
        metrics = StreamingMetrics()
        stream_id = "test_stream_4"

        metrics.increment_error_terminations(stream_id)

        stream_metrics = metrics.get_stream_metrics(stream_id)
        assert stream_metrics["error_terminations"] == 1

        global_metrics = metrics.get_global_metrics()
        assert global_metrics["error_terminations"] == 1

    def test_stream_isolation(self) -> None:
        """Test that metrics are isolated per stream."""
        metrics = StreamingMetrics()
        stream1 = "stream_1"
        stream2 = "stream_2"

        # Increment different metrics for different streams
        metrics.increment_chunks_sent(stream1)
        metrics.increment_chunks_sent(stream1)
        metrics.increment_chunks_sent(stream2)

        # Check isolation
        stream1_metrics = metrics.get_stream_metrics(stream1)
        stream2_metrics = metrics.get_stream_metrics(stream2)

        assert stream1_metrics["chunks_sent"] == 2
        assert stream2_metrics["chunks_sent"] == 1

        # Global should be sum
        global_metrics = metrics.get_global_metrics()
        assert global_metrics["chunks_sent"] == 3

    def test_timer_operations(self) -> None:
        """Test timer start/stop operations."""
        metrics = StreamingMetrics()
        stream_id = "test_stream_timer"

        # Start timer
        metrics.start_timer(stream_id, "test_operation")

        # Simulate some work
        time.sleep(0.01)

        # Stop timer
        elapsed = metrics.stop_timer(stream_id, "test_operation")

        assert elapsed is not None
        assert elapsed >= 0.01  # Should be at least 10ms

    def test_timer_not_started(self) -> None:
        """Test stopping a timer that was never started."""
        metrics = StreamingMetrics()
        stream_id = "test_stream_no_timer"

        elapsed = metrics.stop_timer(stream_id, "nonexistent_timer")
        assert elapsed is None

    def test_start_stream(self) -> None:
        """Test starting a new stream."""
        metrics = StreamingMetrics()
        stream_id = "test_stream_start"

        metrics.start_stream(stream_id)

        # Check that metrics are initialized
        stream_metrics = metrics.get_stream_metrics(stream_id)
        assert stream_metrics["chunks_sent"] == 0
        assert stream_metrics["sentinels_emitted"] == 0
        assert stream_metrics["middleware_mutations"] == 0
        assert stream_metrics["error_terminations"] == 0

        # Check that total_streams was incremented
        global_metrics = metrics.get_global_metrics()
        assert global_metrics["total_streams"] == 1

    def test_end_stream(self) -> None:
        """Test ending a stream."""
        metrics = StreamingMetrics()
        stream_id = "test_stream_end"

        # Start and add some metrics
        metrics.start_stream(stream_id)
        metrics.increment_chunks_sent(stream_id)
        metrics.increment_sentinels_emitted(stream_id)

        # End stream
        metrics.end_stream(stream_id)

        # Stream-specific metrics should be cleaned up
        stream_metrics = metrics.get_stream_metrics(stream_id)
        assert stream_metrics == {}

    def test_reset(self) -> None:
        """Test resetting all metrics."""
        metrics = StreamingMetrics()
        stream_id = "test_stream_reset"

        # Add some metrics
        metrics.start_stream(stream_id)
        metrics.increment_chunks_sent(stream_id)
        metrics.increment_sentinels_emitted(stream_id)

        # Reset
        metrics.reset()

        # All metrics should be cleared
        stream_metrics = metrics.get_stream_metrics(stream_id)
        assert stream_metrics == {}

        global_metrics = metrics.get_global_metrics()
        assert global_metrics["chunks_sent"] == 0
        assert global_metrics["sentinels_emitted"] == 0
        assert global_metrics["total_streams"] == 0

    def test_global_metrics_instance(self) -> None:
        """Test global metrics instance."""
        # Reset first
        reset_metrics()

        # Get instance
        metrics1 = get_metrics_instance()
        metrics2 = get_metrics_instance()

        # Should be same instance
        assert metrics1 is metrics2

        # Increment on one should affect the other
        metrics1.increment_chunks_sent("test")
        global_metrics = metrics2.get_global_metrics()
        assert global_metrics["chunks_sent"] == 1


class TestStreamingSampler:
    """Unit tests for StreamingSampler class."""

    def test_add_sample(self) -> None:
        """Test adding a sample."""
        sampler = StreamingSampler()
        stream_id = "test_stream_sample"

        sampler.add_sample(
            stream_id=stream_id,
            sample_type="request",
            data={"test": "data"},
            metadata={"provider": "openai"},
        )

        samples = sampler.get_samples(stream_id=stream_id)
        assert len(samples) == 1
        assert samples[0]["stream_id"] == stream_id
        assert samples[0]["type"] == "request"
        assert samples[0]["data"] == {"test": "data"}
        assert samples[0]["metadata"]["provider"] == "openai"

    def test_max_samples_limit(self) -> None:
        """Test that max_samples limit is enforced."""
        sampler = StreamingSampler(max_samples=5)

        # Add more than max_samples
        for i in range(10):
            sampler.add_sample(
                stream_id=f"stream_{i}",
                sample_type="chunk",
                data=f"chunk_{i}",
            )

        # Should only keep last 5
        samples = sampler.get_samples()
        assert len(samples) == 5

        # Should be the last 5 added
        assert samples[0]["data"] == "chunk_5"
        assert samples[4]["data"] == "chunk_9"

    def test_filter_by_stream_id(self) -> None:
        """Test filtering samples by stream_id."""
        sampler = StreamingSampler()

        sampler.add_sample("stream_1", "request", "data1")
        sampler.add_sample("stream_2", "request", "data2")
        sampler.add_sample("stream_1", "response", "data3")

        # Filter by stream_1
        stream1_samples = sampler.get_samples(stream_id="stream_1")
        assert len(stream1_samples) == 2
        assert all(s["stream_id"] == "stream_1" for s in stream1_samples)

    def test_filter_by_sample_type(self) -> None:
        """Test filtering samples by sample_type."""
        sampler = StreamingSampler()

        sampler.add_sample("stream_1", "request", "data1")
        sampler.add_sample("stream_1", "response", "data2")
        sampler.add_sample("stream_2", "request", "data3")

        # Filter by request type
        request_samples = sampler.get_samples(sample_type="request")
        assert len(request_samples) == 2
        assert all(s["type"] == "request" for s in request_samples)

    def test_filter_by_both(self) -> None:
        """Test filtering by both stream_id and sample_type."""
        sampler = StreamingSampler()

        sampler.add_sample("stream_1", "request", "data1")
        sampler.add_sample("stream_1", "response", "data2")
        sampler.add_sample("stream_2", "request", "data3")

        # Filter by stream_1 and request
        filtered = sampler.get_samples(stream_id="stream_1", sample_type="request")
        assert len(filtered) == 1
        assert filtered[0]["stream_id"] == "stream_1"
        assert filtered[0]["type"] == "request"

    def test_clear_samples(self) -> None:
        """Test clearing all samples."""
        sampler = StreamingSampler()

        sampler.add_sample("stream_1", "request", "data1")
        sampler.add_sample("stream_2", "response", "data2")

        sampler.clear_samples()

        samples = sampler.get_samples()
        assert len(samples) == 0

    def test_should_sample_rate(self) -> None:
        """Test sampling rate logic."""
        # Use 100% sample rate for deterministic test
        sampler = StreamingSampler(sample_rate=1.0)

        # Should always sample
        for _ in range(10):
            assert sampler.should_sample() is True

        # Use 0% sample rate
        sampler = StreamingSampler(sample_rate=0.0)

        # Should never sample
        for _ in range(10):
            assert sampler.should_sample() is False

    def test_global_sampler_instance(self) -> None:
        """Test global sampler instance."""
        # Reset first
        reset_sampler()

        # Get instance
        sampler1 = get_sampler_instance()
        sampler2 = get_sampler_instance()

        # Should be same instance
        assert sampler1 is sampler2

        # Add sample on one should affect the other
        sampler1.add_sample("test", "request", "data")
        samples = sampler2.get_samples()
        assert len(samples) == 1
