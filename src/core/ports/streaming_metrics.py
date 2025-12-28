"""
Streaming metrics infrastructure for observability.

This module provides metrics collection and tracking for the streaming
pipeline, enabling performance monitoring and debugging without impacting
hot-path performance.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import MutableMapping
from dataclasses import dataclass, field
from typing import Any

from cachetools import TTLCache  # type: ignore

logger = logging.getLogger(__name__)

# Define TRACE_LEVEL for hot-path logging
TRACE_LEVEL = 5


@dataclass
class StreamingMetrics:
    """Metrics collector for streaming operations.

    This class tracks key metrics for streaming operations:
    - chunks_sent: Number of chunks sent to client
    - sentinels_emitted: Number of [DONE] markers emitted
    - middleware_mutations: Number of times middleware modified chunks
    - error_terminations: Number of streams that ended with errors

    Metrics are tracked per stream using stream_id for isolation.
    Uses TTLCache to prevent memory leaks if end_stream() is not called.

    Thread-safety: All mutations are protected by a lock for concurrent access.
    """

    # Per-stream metrics: stream_id -> metric_name -> count
    # TTL: 1 hour, Max size: 10,000 active streams
    _stream_metrics: MutableMapping[str, dict[str, int]] = field(
        default_factory=lambda: TTLCache(maxsize=10000, ttl=3600)
    )

    # Per-stream timers: stream_id -> timer_name -> start_time
    # TTL: 1 hour, Max size: 10,000 active streams
    _stream_timers: MutableMapping[str, dict[str, float]] = field(
        default_factory=lambda: TTLCache(maxsize=10000, ttl=3600)
    )

    # Global aggregated metrics
    _global_metrics: dict[str, int] = field(
        default_factory=lambda: {
            "chunks_sent": 0,
            "sentinels_emitted": 0,
            "middleware_mutations": 0,
            "error_terminations": 0,
            "total_streams": 0,
        }
    )

    # Lock for thread-safe mutations (protects all instance-level state)
    _lock: threading.Lock = field(
        default_factory=threading.Lock, init=False, repr=False
    )

    def _get_or_init_stream_metrics(self, stream_id: str) -> dict[str, int]:
        """Get metrics for a stream, initializing if needed.

        Note: This method should be called with the lock already held.
        """
        return self._stream_metrics.setdefault(
            stream_id,
            {
                "chunks_sent": 0,
                "sentinels_emitted": 0,
                "middleware_mutations": 0,
                "error_terminations": 0,
            },
        )

    def increment_chunks_sent(self, stream_id: str | None = None) -> None:
        """Increment the chunks_sent counter.

        Args:
            stream_id: Optional stream identifier for per-stream tracking
        """
        with self._lock:
            self._global_metrics["chunks_sent"] += 1
            if stream_id:
                # Use setdefault for atomic check-then-act
                stream_metrics = self._stream_metrics.setdefault(
                    stream_id,
                    {
                        "chunks_sent": 0,
                        "sentinels_emitted": 0,
                        "middleware_mutations": 0,
                        "error_terminations": 0,
                    },
                )
                stream_metrics["chunks_sent"] += 1

    def increment_sentinels_emitted(self, stream_id: str | None = None) -> None:
        """Increment the sentinels_emitted counter.

        Args:
            stream_id: Optional stream identifier for per-stream tracking
        """
        with self._lock:
            self._global_metrics["sentinels_emitted"] += 1
            if stream_id:
                # Use setdefault for atomic check-then-act
                stream_metrics = self._stream_metrics.setdefault(
                    stream_id,
                    {
                        "chunks_sent": 0,
                        "sentinels_emitted": 0,
                        "middleware_mutations": 0,
                        "error_terminations": 0,
                    },
                )
                stream_metrics["sentinels_emitted"] += 1

    def increment_middleware_mutations(self, stream_id: str | None = None) -> None:
        """Increment the middleware_mutations counter.

        Args:
            stream_id: Optional stream identifier for per-stream tracking
        """
        with self._lock:
            if stream_id:
                self._get_or_init_stream_metrics(stream_id)["middleware_mutations"] += 1
            self._global_metrics["middleware_mutations"] += 1

    def increment_error_terminations(self, stream_id: str | None = None) -> None:
        """Increment the error_terminations counter.

        Args:
            stream_id: Optional stream identifier for per-stream tracking
        """
        with self._lock:
            if stream_id:
                self._get_or_init_stream_metrics(stream_id)["error_terminations"] += 1
            self._global_metrics["error_terminations"] += 1

    def start_timer(self, stream_id: str, timer_name: str) -> None:
        """Start a timer for a specific operation.

        Args:
            stream_id: Stream identifier
            timer_name: Name of the timer (e.g., "normalization", "processing")
        """
        start_time = time.perf_counter()
        with self._lock:
            if stream_id not in self._stream_timers:
                self._stream_timers[stream_id] = {}
            self._stream_timers[stream_id][timer_name] = start_time

    def stop_timer(self, stream_id: str, timer_name: str) -> float | None:
        """Stop a timer and return the elapsed time.

        Args:
            stream_id: Stream identifier
            timer_name: Name of the timer

        Returns:
            Elapsed time in seconds, or None if timer wasn't started
        """
        end_time = time.perf_counter()
        with self._lock:
            if stream_id not in self._stream_timers:
                return None

            start_time = self._stream_timers[stream_id].get(timer_name)
            if start_time is None:
                return None

            elapsed = end_time - start_time
            del self._stream_timers[stream_id][timer_name]
            return elapsed

    def get_stream_metrics(self, stream_id: str) -> dict[str, int]:
        """Get metrics for a specific stream.

        Args:
            stream_id: Stream identifier

        Returns:
            Dictionary of metrics for the stream
        """
        with self._lock:
            return dict(self._stream_metrics.get(stream_id, {}))

    def get_global_metrics(self) -> dict[str, int]:
        """Get global aggregated metrics.

        Returns:
            Dictionary of global metrics
        """
        with self._lock:
            return dict(self._global_metrics)

    def start_stream(self, stream_id: str) -> None:
        """Mark the start of a new stream.

        Args:
            stream_id: Stream identifier
        """
        start_time = time.perf_counter()
        with self._lock:
            # Initialize metrics for this stream
            self._stream_metrics[stream_id] = {
                "chunks_sent": 0,
                "sentinels_emitted": 0,
                "middleware_mutations": 0,
                "error_terminations": 0,
            }
            self._global_metrics["total_streams"] += 1
            # Initialize timers dict for this stream
            if stream_id not in self._stream_timers:
                self._stream_timers[stream_id] = {}
            self._stream_timers[stream_id]["total_duration"] = start_time

    def end_stream(self, stream_id: str) -> None:
        """Mark the end of a stream and log metrics.

        Args:
            stream_id: Stream identifier
        """
        # Stop total duration timer (returns elapsed, already handles locks internally)
        duration = self.stop_timer(stream_id, "total_duration")

        # Get final metrics for this stream (snapshot under lock)
        with self._lock:
            metrics = dict(self._stream_metrics.get(stream_id, {}))

        # Log metrics with guarded logging (snapshot already copied, no lock needed)
        if logger.isEnabledFor(logging.INFO):
            logger.info(
                "Stream completed",
                extra={
                    "stream_id": stream_id,
                    "duration_seconds": duration,
                    "chunks_sent": metrics.get("chunks_sent", 0),
                    "sentinels_emitted": metrics.get("sentinels_emitted", 0),
                    "middleware_mutations": metrics.get("middleware_mutations", 0),
                    "error_terminations": metrics.get("error_terminations", 0),
                },
            )

        # Clean up stream-specific data under lock
        with self._lock:
            if stream_id in self._stream_metrics:
                del self._stream_metrics[stream_id]
            if stream_id in self._stream_timers:
                del self._stream_timers[stream_id]

    def reset(self) -> None:
        """Reset all metrics.

        This is primarily useful for testing.
        """
        with self._lock:
            self._stream_metrics.clear()
            self._stream_timers.clear()
            self._global_metrics = {
                "chunks_sent": 0,
                "sentinels_emitted": 0,
                "middleware_mutations": 0,
                "error_terminations": 0,
                "total_streams": 0,
            }


# Global metrics instance
_global_metrics_instance: StreamingMetrics | None = None
_global_metrics_lock = threading.Lock()


def get_metrics_instance() -> StreamingMetrics:
    """Get the global metrics instance.

    Returns:
        The global StreamingMetrics instance
    """
    global _global_metrics_instance
    if _global_metrics_instance is None:
        with _global_metrics_lock:
            if _global_metrics_instance is None:
                _global_metrics_instance = StreamingMetrics()
    return _global_metrics_instance


def reset_metrics() -> None:
    """Reset the global metrics instance.

    This is primarily useful for testing.
    """
    global _global_metrics_instance
    if _global_metrics_instance is not None:
        _global_metrics_instance.reset()


@dataclass
class StreamingSampler:
    """Request/response sampler for debugging.

    This class provides sampling capabilities for debugging streaming
    issues without overwhelming logs with data.
    """

    sample_rate: float = 0.01  # Sample 1% of requests by default
    max_samples: int = 100  # Maximum number of samples to keep
    _samples: list[dict[str, Any]] = field(default_factory=list)
    _sample_count: int = 0

    def should_sample(self) -> bool:
        """Determine if the current request should be sampled.

        Returns:
            True if this request should be sampled
        """
        import random

        self._sample_count += 1
        return random.random() < self.sample_rate

    def add_sample(
        self,
        stream_id: str,
        sample_type: str,
        data: Any,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Add a sample to the collection.

        Args:
            stream_id: Stream identifier
            sample_type: Type of sample (e.g., "request", "response", "chunk")
            data: The data to sample
            metadata: Optional metadata about the sample
        """
        if len(self._samples) >= self.max_samples:
            # Remove oldest sample
            self._samples.pop(0)

        sample = {
            "stream_id": stream_id,
            "type": sample_type,
            "data": data,
            "metadata": metadata or {},
            "timestamp": time.time(),
        }
        self._samples.append(sample)

        # Log sample with guarded logging
        if logger.isEnabledFor(TRACE_LEVEL):
            logger.log(
                TRACE_LEVEL,
                "Sampled %s for stream %s",
                sample_type,
                stream_id,
                extra={"sample": sample},
            )

    def get_samples(
        self, stream_id: str | None = None, sample_type: str | None = None
    ) -> list[dict[str, Any]]:
        """Get samples matching the criteria.

        Args:
            stream_id: Optional stream identifier to filter by
            sample_type: Optional sample type to filter by

        Returns:
            List of matching samples
        """
        samples = self._samples

        if stream_id:
            samples = [s for s in samples if s["stream_id"] == stream_id]

        if sample_type:
            samples = [s for s in samples if s["type"] == sample_type]

        return samples

    def clear_samples(self) -> None:
        """Clear all samples.

        This is primarily useful for testing.
        """
        self._samples.clear()
        self._sample_count = 0


# Global sampler instance
_global_sampler_instance: StreamingSampler | None = None
_global_sampler_lock = threading.Lock()


def get_sampler_instance() -> StreamingSampler:
    """Get the global sampler instance.

    Returns:
        The global StreamingSampler instance
    """
    global _global_sampler_instance
    if _global_sampler_instance is None:
        with _global_sampler_lock:
            if _global_sampler_instance is None:
                _global_sampler_instance = StreamingSampler()
    return _global_sampler_instance


def configure_sampler(
    sample_rate: float = 0.01,
    max_samples: int = 100,
    enabled: bool = True,
) -> StreamingSampler:
    """Configure the global sampler instance with custom settings.

    This function should be called during application startup to configure
    the sampler with settings from AppConfig.

    Args:
        sample_rate: Probability of sampling a stream (0.0 to 1.0)
        max_samples: Maximum number of samples to retain
        enabled: Whether sampling is enabled

    Returns:
        The configured StreamingSampler instance
    """
    global _global_sampler_instance

    with _global_sampler_lock:
        # Create new instance with configured settings
        _global_sampler_instance = StreamingSampler(
            sample_rate=sample_rate if enabled else 0.0,
            max_samples=max_samples,
        )

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Configured streaming sampler: enabled=%s, sample_rate=%s, max_samples=%s",
                enabled,
                sample_rate,
                max_samples,
            )

        return _global_sampler_instance


def reset_sampler() -> None:
    """Reset the global sampler instance.

    This is primarily useful for testing.
    """
    global _global_sampler_instance
    with _global_sampler_lock:
        if _global_sampler_instance is not None:
            _global_sampler_instance.clear_samples()
