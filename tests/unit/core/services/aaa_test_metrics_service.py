"""
Unit tests for the metrics service.
"""

from __future__ import annotations

import time

import pytest
from src.core.services import metrics_service


class TestMetricsService:
    """Test the metrics service functionality."""

    def setup_method(self):
        """Reset metrics before each test."""
        # Clear counters and timers
        with metrics_service._lock:
            metrics_service._counters.clear()
            metrics_service._timers.clear()

    def test_counter_increment(self):
        """Test basic counter increment functionality."""
        metrics_service.inc("test.counter")
        assert metrics_service.get("test.counter") == 1

        metrics_service.inc("test.counter", by=5)
        assert metrics_service.get("test.counter") == 6

    def test_counter_get_nonexistent(self):
        """Test getting a counter that doesn't exist returns 0."""
        assert metrics_service.get("nonexistent.counter") == 0

    def test_counter_snapshot(self):
        """Test getting a snapshot of all counters."""
        metrics_service.inc("counter1")
        metrics_service.inc("counter2", by=3)
        metrics_service.inc("counter3", by=10)

        snapshot = metrics_service.snapshot()
        assert snapshot["counter1"] == 1
        assert snapshot["counter2"] == 3
        assert snapshot["counter3"] == 10

    def test_record_duration(self):
        """Test recording duration measurements."""
        metrics_service.record_duration("test.timer", 0.5)
        metrics_service.record_duration("test.timer", 1.0)
        metrics_service.record_duration("test.timer", 0.75)

        stats = metrics_service.get_timer_stats("test.timer")
        assert stats.count == 3
        assert stats.total == 2.25
        assert stats.average == 0.75
        assert stats.min == 0.5
        assert stats.max == 1.0

    def test_timer_context_manager(self, monkeypatch: pytest.MonkeyPatch):
        """Test the timer context manager."""
        current_time = {"value": 1000.0}

        def fake_perf_counter() -> float:
            return current_time["value"]

        monkeypatch.setattr(time, "perf_counter", fake_perf_counter)
        monkeypatch.setattr(
            "src.core.services.metrics_service.time.perf_counter", fake_perf_counter
        )

        with metrics_service.timer("test.operation"):
            current_time["value"] += 0.01  # Advance time by 10ms

        stats = metrics_service.get_timer_stats("test.operation")
        assert stats.count == 1
        assert stats.total == pytest.approx(0.01, rel=0.001)  # Should be exactly 10ms
        assert stats.average == pytest.approx(0.01, rel=0.001)

    def test_timer_stats_empty(self):
        """Test getting stats for a timer with no measurements."""
        stats = metrics_service.get_timer_stats("nonexistent.timer")
        assert stats.count == 0
        assert stats.total == 0.0
        assert stats.average == 0.0
        assert stats.min == 0.0
        assert stats.max == 0.0

    def test_get_all_timer_stats(self):
        """Test getting stats for all timers."""
        metrics_service.record_duration("timer1", 0.5)
        metrics_service.record_duration("timer2", 1.0)

        all_stats = metrics_service.get_all_timer_stats()
        assert "timer1" in all_stats
        assert "timer2" in all_stats
        assert all_stats["timer1"].count == 1
        assert all_stats["timer2"].count == 1

    def test_tool_call_processing_metrics(self):
        """Test metrics specific to tool call processing."""
        # Simulate processing and skipping messages
        metrics_service.inc("tool_call.messages.processed", by=5)
        metrics_service.inc("tool_call.messages.skipped", by=45)

        assert metrics_service.get("tool_call.messages.processed") == 5
        assert metrics_service.get("tool_call.messages.skipped") == 45

        # Calculate skip rate
        total = 5 + 45
        skip_rate = (45 / total) * 100
        assert skip_rate == 90.0

    def test_log_performance_stats_with_data(self, caplog):
        """Test logging performance statistics with data."""
        metrics_service.inc("tool_call.messages.processed", by=10)
        metrics_service.inc("tool_call.messages.skipped", by=90)
        metrics_service.record_duration("tool_call.processing.duration", 0.05)
        metrics_service.record_duration("tool_call.processing.duration", 0.03)

        metrics_service.log_performance_stats()

        # Check that log messages were generated
        assert any("processed=10" in record.message for record in caplog.records)
        assert any("skipped=90" in record.message for record in caplog.records)
        assert any("skip_rate=90.0%" in record.message for record in caplog.records)

    def test_log_performance_stats_no_data(self, caplog):
        """Test logging performance statistics with no data."""
        metrics_service.log_performance_stats()

        # Should not log anything when there's no data
        assert len(caplog.records) == 0
