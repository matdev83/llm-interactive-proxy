"""Unit tests for replacement metrics tracking.

Tests verify that metrics are correctly tracked for:
- Activation rate (Requirement 3.2)
- Turn count distribution (Requirement 4.1)
- Opt-out rate (Requirements 9.1, 9.2)
"""

from __future__ import annotations

import time

import pytest
from src.core.services.replacement_metrics import ReplacementMetrics


class TestReplacementMetrics:
    """Test suite for ReplacementMetrics class."""

    def test_initial_state(self) -> None:
        """Test that metrics start with zero values."""
        metrics = ReplacementMetrics()

        assert metrics.total_activations == 0
        assert metrics.total_turns_completed == 0
        assert metrics.total_opt_outs == 0
        assert metrics.header_opt_outs == 0
        assert metrics.session_opt_outs == 0
        assert metrics.total_probability_checks == 0
        assert len(metrics.activations_by_session) == 0
        assert len(metrics.turns_by_session) == 0
        assert len(metrics.opt_outs_by_session) == 0

    def test_record_activation(self) -> None:
        """Test recording activation events."""
        metrics = ReplacementMetrics()

        metrics.record_activation("session1", 3)

        assert metrics.total_activations == 1
        assert metrics.activations_by_session["session1"] == 1
        assert len(metrics.activation_timestamps) == 1
        # Turn counts are tracked in histogram, not as a list
        assert metrics.get_turn_count_distribution() == {3: 1}

    def test_record_multiple_activations(self) -> None:
        """Test recording multiple activation events."""
        metrics = ReplacementMetrics()

        metrics.record_activation("session1", 3)
        metrics.record_activation("session1", 5)
        metrics.record_activation("session2", 2)

        assert metrics.total_activations == 3
        assert metrics.activations_by_session["session1"] == 2
        assert metrics.activations_by_session["session2"] == 1
        assert len(metrics.activation_timestamps) == 3
        assert metrics.get_turn_count_distribution() == {3: 1, 5: 1, 2: 1}

    def test_record_turn_completion(self) -> None:
        """Test recording turn completion events."""
        metrics = ReplacementMetrics()

        metrics.record_turn_completion("session1")

        assert metrics.total_turns_completed == 1
        assert metrics.turns_by_session["session1"] == 1

    def test_record_multiple_turn_completions(self) -> None:
        """Test recording multiple turn completion events."""
        metrics = ReplacementMetrics()

        metrics.record_turn_completion("session1")
        metrics.record_turn_completion("session1")
        metrics.record_turn_completion("session2")

        assert metrics.total_turns_completed == 3
        assert metrics.turns_by_session["session1"] == 2
        assert metrics.turns_by_session["session2"] == 1

    def test_record_header_opt_out(self) -> None:
        """Test recording header-based opt-out events."""
        metrics = ReplacementMetrics()

        metrics.record_opt_out("session1", "header")

        assert metrics.total_opt_outs == 1
        assert metrics.header_opt_outs == 1
        assert metrics.session_opt_outs == 0
        assert metrics.opt_outs_by_session["session1"] == 1
        assert len(metrics.opt_out_timestamps) == 1

    def test_record_session_opt_out(self) -> None:
        """Test recording session-level opt-out events."""
        metrics = ReplacementMetrics()

        metrics.record_opt_out("session1", "session")

        assert metrics.total_opt_outs == 1
        assert metrics.header_opt_outs == 0
        assert metrics.session_opt_outs == 1
        assert metrics.opt_outs_by_session["session1"] == 1
        assert len(metrics.opt_out_timestamps) == 1

    def test_record_mixed_opt_outs(self) -> None:
        """Test recording both header and session opt-outs."""
        metrics = ReplacementMetrics()

        metrics.record_opt_out("session1", "header")
        metrics.record_opt_out("session2", "session")
        metrics.record_opt_out("session1", "header")

        assert metrics.total_opt_outs == 3
        assert metrics.header_opt_outs == 2
        assert metrics.session_opt_outs == 1
        assert metrics.opt_outs_by_session["session1"] == 2
        assert metrics.opt_outs_by_session["session2"] == 1

    def test_record_probability_check(self) -> None:
        """Test recording probability check events."""
        metrics = ReplacementMetrics()

        metrics.record_probability_check("session1")

        assert metrics.total_probability_checks == 1
        assert metrics.probability_checks_by_session["session1"] == 1

    def test_get_activation_rate_all_time(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test calculating activation rate over all time."""
        import src.core.services.replacement_metrics as metrics_module

        current_time = {"value": 1000.0}

        def fake_time() -> float:
            return current_time["value"]

        # Patch time.time in the module - this affects calls made after patching
        # Note: default_factory captures time.time at class definition, so start_time
        # will use real time, but subsequent calls will use mocked time
        monkeypatch.setattr(metrics_module.time, "time", fake_time)

        metrics = ReplacementMetrics()
        # Manually set start_time to use mocked time
        metrics.start_time = current_time["value"]

        # Record some activations
        metrics.record_activation("session1", 3)
        current_time["value"] += 0.1  # Advance time to ensure elapsed time > 0
        metrics.record_activation("session2", 2)

        rate = metrics.get_activation_rate()

        # Rate should be positive and reasonable
        # With mocked time: 2 activations in 0.1 seconds = 20 activations/second
        assert rate > 0
        assert rate == pytest.approx(20.0, rel=0.1)  # 2 activations / 0.1 seconds

    def test_get_activation_rate_time_window(self) -> None:
        """Test calculating activation rate within a time window."""
        metrics = ReplacementMetrics()

        # Record activation now
        metrics.record_activation("session1", 3)

        # Get rate for last 60 seconds
        rate = metrics.get_activation_rate(60.0)

        # Should have 1 activation in 60 seconds
        assert rate == pytest.approx(1.0 / 60.0, rel=0.1)

    def test_get_activation_rate_by_session(self) -> None:
        """Test calculating activation rate for a specific session."""
        metrics = ReplacementMetrics()

        # Record probability checks and activations
        metrics.record_probability_check("session1")
        metrics.record_probability_check("session1")
        metrics.record_probability_check("session1")
        metrics.record_activation("session1", 3)

        rate = metrics.get_activation_rate_by_session("session1")

        # 1 activation out of 3 checks = 0.333...
        assert rate == pytest.approx(1.0 / 3.0)

    def test_get_activation_rate_by_session_no_checks(self) -> None:
        """Test activation rate returns 0 when no checks recorded."""
        metrics = ReplacementMetrics()

        rate = metrics.get_activation_rate_by_session("session1")

        assert rate == 0.0

    def test_get_turn_count_distribution(self) -> None:
        """Test calculating turn count distribution."""
        metrics = ReplacementMetrics()

        # Record activations with various turn counts
        metrics.record_activation("session1", 3)
        metrics.record_activation("session2", 3)
        metrics.record_activation("session3", 5)
        metrics.record_activation("session4", 2)
        metrics.record_activation("session5", 3)

        distribution = metrics.get_turn_count_distribution()

        assert distribution[3] == 3  # Three activations with 3 turns
        assert distribution[5] == 1  # One activation with 5 turns
        assert distribution[2] == 1  # One activation with 2 turns

    def test_get_average_turn_count(self) -> None:
        """Test calculating average turn count."""
        metrics = ReplacementMetrics()

        # Record activations with various turn counts
        metrics.record_activation("session1", 3)
        metrics.record_activation("session2", 5)
        metrics.record_activation("session3", 2)

        avg = metrics.get_average_turn_count()

        # Average of 3, 5, 2 = 10/3 = 3.333...
        assert avg == pytest.approx(10.0 / 3.0)

    def test_get_average_turn_count_no_activations(self) -> None:
        """Test average turn count returns 0 when no activations."""
        metrics = ReplacementMetrics()

        avg = metrics.get_average_turn_count()

        assert avg == 0.0

    def test_get_opt_out_rate_all_time(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test calculating opt-out rate over all time."""
        import src.core.services.replacement_metrics as metrics_module

        current_time = {"value": 1000.0}

        def fake_time() -> float:
            return current_time["value"]

        # Patch time.time in the module
        monkeypatch.setattr(metrics_module.time, "time", fake_time)

        metrics = ReplacementMetrics()
        # Manually set start_time to use mocked time
        metrics.start_time = current_time["value"]

        # Record some opt-outs
        metrics.record_opt_out("session1", "header")
        current_time["value"] += 0.1  # Advance time to ensure elapsed time > 0
        metrics.record_opt_out("session2", "session")

        rate = metrics.get_opt_out_rate()

        # Rate should be positive and reasonable
        # With mocked time: 2 opt-outs in 0.1 seconds = 20 opt-outs/second
        assert rate > 0
        assert rate == pytest.approx(20.0, rel=0.1)  # 2 opt-outs / 0.1 seconds

    def test_get_opt_out_rate_time_window(self) -> None:
        """Test calculating opt-out rate within a time window."""
        metrics = ReplacementMetrics()

        # Record opt-out now
        metrics.record_opt_out("session1", "header")

        # Get rate for last 60 seconds
        rate = metrics.get_opt_out_rate(60.0)

        # Should have 1 opt-out in 60 seconds
        assert rate == pytest.approx(1.0 / 60.0, rel=0.1)

    def test_get_opt_out_rate_by_session(self) -> None:
        """Test calculating opt-out rate for a specific session."""
        metrics = ReplacementMetrics()

        # Record probability checks and opt-outs
        metrics.record_probability_check("session1")
        metrics.record_probability_check("session1")
        metrics.record_probability_check("session1")
        metrics.record_probability_check("session1")
        metrics.record_opt_out("session1", "header")

        rate = metrics.get_opt_out_rate_by_session("session1")

        # 1 opt-out out of 4 checks = 0.25
        assert rate == pytest.approx(0.25)

    def test_get_opt_out_rate_by_session_no_checks(self) -> None:
        """Test opt-out rate returns 0 when no checks recorded."""
        metrics = ReplacementMetrics()

        rate = metrics.get_opt_out_rate_by_session("session1")

        assert rate == 0.0

    def test_get_summary(self) -> None:
        """Test getting comprehensive metrics summary."""
        metrics = ReplacementMetrics()

        # Record various events
        metrics.record_activation("session1", 3)
        metrics.record_activation("session2", 5)
        metrics.record_turn_completion("session1")
        metrics.record_opt_out("session3", "header")
        metrics.record_opt_out("session4", "session")
        metrics.record_probability_check("session1")

        summary = metrics.get_summary()

        # Verify summary structure
        assert "elapsed_seconds" in summary
        assert "activation_metrics" in summary
        assert "turn_count_metrics" in summary
        assert "opt_out_metrics" in summary
        assert "probability_check_metrics" in summary

        # Verify activation metrics
        assert summary["activation_metrics"]["total_activations"] == 2
        assert summary["activation_metrics"]["unique_sessions_activated"] == 2

        # Verify turn count metrics
        assert summary["turn_count_metrics"]["total_turns_completed"] == 1
        assert summary["turn_count_metrics"]["average_turn_count"] == 4.0  # (3+5)/2

        # Verify opt-out metrics
        assert summary["opt_out_metrics"]["total_opt_outs"] == 2
        assert summary["opt_out_metrics"]["header_opt_outs"] == 1
        assert summary["opt_out_metrics"]["session_opt_outs"] == 1

        # Verify probability check metrics
        assert summary["probability_check_metrics"]["total_probability_checks"] == 1

    def test_reset(self) -> None:
        """Test resetting all metrics."""
        metrics = ReplacementMetrics()

        # Record various events
        metrics.record_activation("session1", 3)
        metrics.record_turn_completion("session1")
        metrics.record_opt_out("session2", "header")
        metrics.record_probability_check("session1")

        # Reset metrics
        metrics.reset()

        # Verify all metrics are reset
        assert metrics.total_activations == 0
        assert metrics.total_turns_completed == 0
        assert metrics.total_opt_outs == 0
        assert metrics.header_opt_outs == 0
        assert metrics.session_opt_outs == 0
        assert metrics.total_probability_checks == 0
        assert len(metrics.activations_by_session) == 0
        assert len(metrics.turns_by_session) == 0
        assert len(metrics.opt_outs_by_session) == 0
        assert len(metrics.get_turn_count_distribution()) == 0
        assert len(metrics.activation_timestamps) == 0
        assert len(metrics.opt_out_timestamps) == 0

    def test_log_summary_does_not_crash(self) -> None:
        """Test that log_summary can be called without errors."""
        metrics = ReplacementMetrics()

        # Record some events
        metrics.record_activation("session1", 3)
        metrics.record_turn_completion("session1")

        # Should not raise any exceptions
        metrics.log_summary()
