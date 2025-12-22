from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass

from src.core.domain.metrics import TimerStats

logger = logging.getLogger(__name__)

# Maximum number of metrics to track to prevent unbounded memory growth
_MAX_METRICS = 10000

_lock = threading.RLock()
_counters: OrderedDict[str, int] = OrderedDict()


@dataclass
class TimerData:
    """Internal storage for timer metrics."""

    count: int = 0
    total: float = 0.0
    min: float = float("inf")
    max: float = float("-inf")


_timers: OrderedDict[str, TimerData] = OrderedDict()


def inc(name: str, by: int = 1) -> None:
    """Increment a counter metric by the specified amount.

    Args:
        name: The name of the counter metric
        by: The amount to increment by (default: 1)
    """
    with _lock:
        if name in _counters:
            _counters[name] += by
            _counters.move_to_end(name)
        else:
            if len(_counters) >= _MAX_METRICS:
                # Evict oldest entry (FIFO behavior with OrderedDict)
                _counters.popitem(last=False)
            _counters[name] = by


def get(name: str) -> int:
    """Get the current value of a counter metric.

    Args:
        name: The name of the counter metric

    Returns:
        The current counter value, or 0 if not found
    """
    with _lock:
        val = _counters.get(name, 0)
        if name in _counters:
            _counters.move_to_end(name)
        return int(val)


def snapshot() -> dict[str, int]:
    """Get a snapshot of all counter metrics.

    Returns:
        A dictionary of all counter metrics and their values
    """
    with _lock:
        return dict(_counters)


def record_duration(name: str, duration_seconds: float) -> None:
    """Record a duration measurement for a timer metric.

    Args:
        name: The name of the timer metric
        duration_seconds: The duration to record in seconds
    """
    with _lock:
        if name in _timers:
            data = _timers[name]
            _timers.move_to_end(name)
        else:
            if len(_timers) >= _MAX_METRICS:
                # Evict oldest entry
                _timers.popitem(last=False)
            data = TimerData()
            _timers[name] = data

        data.count += 1
        data.total += duration_seconds
        if duration_seconds < data.min:
            data.min = duration_seconds
        if duration_seconds > data.max:
            data.max = duration_seconds


@contextmanager
def timer(name: str) -> Generator[None, None, None]:
    """Context manager to time a block of code and record the duration.

    Args:
        name: The name of the timer metric

    Example:
        >>> with timer("my_operation"):
        ...     # code to time
        ...     pass
    """
    start_time = time.perf_counter()
    try:
        yield
    finally:
        duration = time.perf_counter() - start_time
        record_duration(name, duration)


def get_timer_stats(name: str) -> TimerStats:
    """Get statistics for a timer metric.

    Args:
        name: The name of the timer metric

    Returns:
        TimerStats containing count, total, average, min, and max durations
    """
    with _lock:
        if name not in _timers:
            return TimerStats(
                count=0,
                total=0.0,
                average=0.0,
                min=0.0,
                max=0.0,
            )

        data = _timers[name]
        # Handle case where count is 0 (shouldn't happen if in dict, but for safety)
        if data.count == 0:
            return TimerStats(
                count=0,
                total=0.0,
                average=0.0,
                min=0.0,
                max=0.0,
            )

        return TimerStats(
            count=data.count,
            total=data.total,
            average=data.total / data.count,
            min=data.min,
            max=data.max,
        )


def get_all_timer_stats() -> dict[str, TimerStats]:
    """Get statistics for all timer metrics.

    Returns:
        A dictionary mapping timer names to their statistics
    """
    with _lock:
        return {name: get_timer_stats(name) for name in _timers}


def log_performance_stats() -> None:
    """Log performance statistics for tool call processing."""
    messages_processed = get("tool_call.messages.processed")
    messages_skipped = get("tool_call.messages.skipped")
    total_messages = messages_processed + messages_skipped

    if total_messages == 0:
        return

    skip_percentage = (messages_skipped / total_messages) * 100

    logger.info(
        f"Tool call processing stats: "
        f"processed={messages_processed}, "
        f"skipped={messages_skipped}, "
        f"skip_rate={skip_percentage:.1f}%"
    )

    # Log timing stats if available
    processing_stats = get_timer_stats("tool_call.processing.duration")
    if processing_stats.count > 0:
        logger.info(
            f"Tool call processing timing: "
            f"count={processing_stats.count}, "
            f"avg={processing_stats.average*1000:.2f}ms, "
            f"min={processing_stats.min*1000:.2f}ms, "
            f"max={processing_stats.max*1000:.2f}ms"
        )
