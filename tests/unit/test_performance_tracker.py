import logging
from collections import deque

from src import performance_tracker
from src.performance_tracker import (
    PerformanceMetrics,
    track_phase,
    track_request_performance,
)


def _time_sequence(*values: float):
    queue = deque(values)

    def _next_time() -> float:
        if not queue:
            raise AssertionError("No more time values available")
        return queue.popleft()

    return _next_time


def test_log_summary_includes_breakdown_and_overhead(monkeypatch, caplog):
    import time as original_time

    time_values = _time_sequence(100.1, 100.4, 100.5, 101.0, 101.6, 101.7)
    monkeypatch.setattr(performance_tracker.time, "time", time_values)
    # Also patch the logging time to avoid running out of values
    monkeypatch.setattr(original_time, "time", time_values)

    metrics = PerformanceMetrics(request_start=100.0)
    metrics.session_id = "session-123"
    metrics.backend_used = "backend-a"
    metrics.model_used = "model-b"
    metrics.commands_processed = True
    metrics.streaming = True

    metrics.start_phase("command_processing")
    metrics.end_phase()
    metrics.start_phase("backend_selection")
    metrics.end_phase()

    caplog.set_level(logging.INFO)
    metrics.log_summary()

    assert len(caplog.records) == 1
    message = caplog.records[0].message
    assert "PERF_SUMMARY session=session-123" in message
    assert "total=1.600s" in message
    assert "backend=backend-a" in message
    assert "model=model-b" in message
    assert "streaming=True" in message
    assert "commands=True" in message
    assert "breakdown=[cmd_proc=0.300s, backend_sel=0.500s]" in message
    assert "overhead=0.800s" in message


def test_log_summary_includes_overhead_without_breakdown(monkeypatch, caplog):
    import time as original_time

    time_values = _time_sequence(101.0, 101.5)
    monkeypatch.setattr(performance_tracker.time, "time", time_values)
    monkeypatch.setattr(original_time, "time", time_values)

    metrics = PerformanceMetrics(request_start=100.0)
    metrics.session_id = "session-456"
    metrics.backend_used = "backend-b"
    metrics.model_used = "model-c"

    metrics.finalize()

    caplog.set_level(logging.INFO)
    metrics.log_summary()

    assert len(caplog.records) == 1
    message = caplog.records[0].message
    assert "breakdown=" not in message
    assert "overhead=1.000s" in message


def test_track_request_performance_finalizes(monkeypatch):
    calls: list[PerformanceMetrics] = []

    def fake_log_summary(self: PerformanceMetrics) -> None:
        self.commands_processed = True
        calls.append(self)

    monkeypatch.setattr(PerformanceMetrics, "log_summary", fake_log_summary)

    with track_request_performance(session_id="abc") as metrics:
        assert isinstance(metrics, PerformanceMetrics)
        assert metrics.session_id == "abc"
        metrics.backend_used = "backend"

    assert calls == [metrics]
    assert metrics.commands_processed is True


def test_track_phase_wraps_start_and_end(monkeypatch):
    metrics = PerformanceMetrics()
    events: list[tuple[str, str | None]] = []

    def fake_start(phase_name: str) -> None:
        events.append(("start", phase_name))

    def fake_end() -> None:
        events.append(("end", None))

    monkeypatch.setattr(metrics, "start_phase", fake_start)
    monkeypatch.setattr(metrics, "end_phase", fake_end)

    with track_phase(metrics, "backend_call"):
        events.append(("inside", None))

    assert events == [
        ("start", "backend_call"),
        ("inside", None),
        ("end", None),
    ]
