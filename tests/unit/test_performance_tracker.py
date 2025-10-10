import logging

import pytest

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
        try:
            self._last = next(self._iterator)
        except StopIteration:
            pass
        return self._last


class DummyMetrics:
    def __init__(self) -> None:
        self.started: list[str] = []
        self.ended = 0

    def start_phase(self, phase_name: str) -> None:
        self.started.append(phase_name)

    def end_phase(self) -> None:
        self.ended += 1


def test_performance_metrics_phase_tracking_and_finalize(monkeypatch: pytest.MonkeyPatch) -> None:
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


def test_track_request_performance_context_manager_logs_on_exit(monkeypatch: pytest.MonkeyPatch) -> None:
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

    with pytest.raises(RuntimeError):
        with track_phase(dummy, "phase-one"):
            raise RuntimeError("boom")

    assert dummy.started == ["phase-one"]
    assert dummy.ended == 1
