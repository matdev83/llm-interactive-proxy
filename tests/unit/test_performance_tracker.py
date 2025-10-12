import logging
from collections import deque

import pytest
from src import performance_tracker
from src.performance_tracker import (
    PerformanceMetrics,
    track_phase,
    track_request_performance,
)


class TimeStub:
    def __init__(self, values: list[float]) -> None:
        self._iterator = iter(values)
        self._last = values[-1]

    def __call__(self) -> float:
        from contextlib import suppress

        with suppress(StopIteration):
            self._last = next(self._iterator)
        return self._last


class DummyMetrics:
    def __init__(self) -> None:
        self.started: list[str] = []
        self.ended = 0

    def start_phase(self, phase_name: str) -> None:
        self.started.append(phase_name)

    def end_phase(self) -> None:
        self.ended += 1


def _time_sequence(*values: float):
    queue = deque(values)

    def _next_time() -> float:
        if not queue:
            raise AssertionError("No more time values available")
        return queue.popleft()

    return _next_time


def test_performance_metrics_phase_tracking_and_finalize(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    time_stub = TimeStub([1.0, 4.0, 5.0])
    monkeypatch.setattr("src.performance_tracker.time.time", time_stub)

    metrics = PerformanceMetrics()
    metrics.request_start = 0.0

    metrics.start_phase("command_processing")
    metrics.end_phase()
    metrics.finalize()

    assert metrics.command_processing_time == pytest.approx(3.0)
    assert metrics.total_time == pytest.approx(5.0)
    assert metrics._current_phase is None


def test_performance_metrics_log_summary_logs_breakdown_and_overhead(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    time_stub = TimeStub([2.0, 5.0, 8.0])
    monkeypatch.setattr("src.performance_tracker.time.time", time_stub)

    metrics = PerformanceMetrics(session_id="session-123")
    metrics.request_start = 0.0
    metrics.command_processing_time = 1.0
    metrics.backend_selection_time = None
    metrics.response_processing_time = 1.5
    metrics.backend_used = "backend-a"
    metrics.model_used = "model-x"
    metrics.streaming = True
    metrics.commands_processed = True

    metrics.start_phase("backend_call")

    caplog.set_level(logging.INFO)
    metrics.log_summary()

    assert "PERF_SUMMARY session=session-123" in caplog.text
    assert "total=8.000s" in caplog.text
    assert "backend=backend-a" in caplog.text
    assert "model=model-x" in caplog.text
    assert "breakdown=[cmd_proc=1.000s" in caplog.text
    assert "backend_call=3.000s" in caplog.text
    assert "resp_proc=1.500s" in caplog.text
    assert "overhead=2.500s" in caplog.text


def test_track_request_performance_context_manager_logs_on_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: list[PerformanceMetrics] = []

    def fake_log_summary(self: PerformanceMetrics) -> None:
        called.append(self)

    monkeypatch.setattr(PerformanceMetrics, "log_summary", fake_log_summary)

    with track_request_performance(session_id="abc") as metrics:
        assert isinstance(metrics, PerformanceMetrics)
        assert metrics.session_id == "abc"

    assert called and called[0] is metrics


def test_track_phase_context_manager_ensures_end_called_on_exception() -> None:
    dummy = DummyMetrics()

    with pytest.raises(RuntimeError), track_phase(dummy, "phase-one"):
        raise RuntimeError("boom")

    assert dummy.started == ["phase-one"]
    assert dummy.ended == 1


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


def test_finalize_completes_active_phase(monkeypatch):
    time_values = _time_sequence(10.0, 12.5, 15.0)
    monkeypatch.setattr(performance_tracker.time, "time", time_values)

    metrics = PerformanceMetrics(request_start=5.0)
    metrics.start_phase("backend_call")

    metrics.finalize()

    assert metrics.backend_call_time == 2.5
    assert metrics.total_time == 10.0


def test_summary_helpers_include_defaults():
    metrics = PerformanceMetrics()
    metrics.total_time = 2.3456
    metrics.command_processing_time = 0.123
    metrics.response_processing_time = 0.456

    summary_prefix = metrics._format_summary_prefix()
    assert summary_prefix == [
        "PERF_SUMMARY session=unknown",
        "total=2.346s",
        "backend=unknown",
        "model=unknown",
        "streaming=False",
        "commands=False",
    ]

    timing_parts = metrics._format_timing_parts()
    assert timing_parts == [
        "cmd_proc=0.123s",
        "resp_proc=0.456s",
    ]


def test_track_phase_ends_on_exception(monkeypatch):
    metrics = PerformanceMetrics()
    called: list[str] = []

    def fake_end_phase() -> None:
        called.append("end")

    monkeypatch.setattr(metrics, "end_phase", fake_end_phase)

    try:
        with track_phase(metrics, "response_processing"):
            raise RuntimeError("boom")
    except RuntimeError:
        pass

    assert called == ["end"]


def test_start_phase_switches_phases(monkeypatch: pytest.MonkeyPatch) -> None:
    metrics = PerformanceMetrics()
    metrics._current_phase = "command_processing"
    metrics._markers["command_processing_start"] = 5.0

    ended: list[str] = []

    def fake_end_phase() -> None:
        ended.append(metrics._current_phase or "")
        metrics._current_phase = None

    monkeypatch.setattr(metrics, "end_phase", fake_end_phase)
    monkeypatch.setattr(performance_tracker.time, "time", lambda: 11.25)

    metrics.start_phase("backend_selection")

    assert ended == ["command_processing"]
    assert metrics._current_phase == "backend_selection"
    assert metrics._markers["backend_selection_start"] == pytest.approx(11.25)


def test_end_phase_ignores_missing_start(monkeypatch: pytest.MonkeyPatch) -> None:
    metrics = PerformanceMetrics()
    metrics._current_phase = "backend_call"

    monkeypatch.setattr(performance_tracker.time, "time", lambda: 3.5)
    metrics._markers.clear()

    metrics.end_phase()

    assert metrics.backend_call_time is None
    assert metrics._current_phase is None


def test_log_summary_finalizes_when_total_missing(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    time_stub = TimeStub([0.0, 4.0])
    monkeypatch.setattr("src.performance_tracker.time.time", time_stub)

    metrics = PerformanceMetrics(session_id="sess-1")
    metrics.request_start = 0.0
    metrics.backend_used = "backend-b"
    metrics.model_used = "model-y"
    metrics.command_processing_time = 1.5

    called: list[bool] = []
    original_finalize = metrics.finalize

    def recording_finalize() -> None:
        called.append(True)
        original_finalize()

    monkeypatch.setattr(metrics, "finalize", recording_finalize)

    caplog.set_level(logging.INFO)
    metrics.log_summary()

    assert called == [True]
    assert metrics.total_time == pytest.approx(4.0)
    assert "PERF_SUMMARY session=sess-1" in caplog.text
