"""Tests for history compaction telemetry domain models, config, and metrics recorder.

TDD: Written BEFORE implementation — these tests should fail initially.

Tests coverage:
- CompactionEventRecord: serialization, validation, field correctness
- CompactionAggregateMetrics: accumulation, snapshot correctness
- CompactionAlertRecord: validation, threshold tracking
- EffectiveCompactionConfigDiagnostics: active/inactive/ignored controls
- CompactionAlertsConfig: defaults, from_dict integration
- CompactionConfig: alerts field integration in default(), from_dict(), disabled()
- CompactionMetricsRecorder: aggregation correctness, alert thresholds, cooldown, concurrency
"""

import threading
import time

from src.core.domain.compaction_telemetry import (
    CompactionAggregateMetrics,
    CompactionAlertRecord,
    CompactionEventRecord,
    EffectiveCompactionConfigDiagnostics,
)
from src.core.domain.configuration.compaction_config import (
    CompactionAlertsConfig,
    CompactionConfig,
)
from src.core.services.compaction_metrics_recorder import CompactionMetricsRecorder


def _make_event(
    *,
    tool_name: str = "view_file",
    tool_category: str = "file_read",
    applied: bool = True,
    failed_open: bool = False,
    decision_reason: str = "applied",
    original_bytes: int = 5000,
    compacted_bytes: int = 1500,
    failure_reason: str | None = None,
    resource_identity_hash: str = "abc123",
    correlation_id: str | None = None,
    tool_call_id: str | None = None,
    message_index: int | None = None,
    warnings: list[str] | None = None,
    original_tokens_estimate: int = 1250,
    saved_tokens_estimate: int = 875,
) -> CompactionEventRecord:
    """Helper to create CompactionEventRecord with sensible defaults."""
    return CompactionEventRecord(
        correlation_id=correlation_id,
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        tool_category=tool_category,
        resource_identity_hash=resource_identity_hash,
        resource_identity_preview=None,
        resource_preview_redacted=False,
        original_bytes=original_bytes,
        compacted_bytes=compacted_bytes,
        saved_bytes=original_bytes - compacted_bytes,
        original_tokens_estimate=original_tokens_estimate,
        saved_tokens_estimate=saved_tokens_estimate,
        applied=applied,
        decision_reason=decision_reason,
        failed_open=failed_open,
        failure_reason=failure_reason,
        elapsed_total_ms=12.5,
        original_sha256=None,
        compacted_sha256=None,
        warnings=warnings or [],
        message_index=message_index,
    )


# ─── CompactionEventRecord ───────────────────────────────────────────

class TestCompactionEventRecord:
    """Tests for per-compaction-event diagnostics model."""

    def test_minimal_creation(self) -> None:
        """Can create record with required fields only."""
        record = CompactionEventRecord(
            tool_name="view_file",
            tool_category="file_read",
            resource_identity_hash="sha256hash",
            original_bytes=1000,
            compacted_bytes=500,
            saved_bytes=500,
            original_tokens_estimate=250,
            saved_tokens_estimate=125,
            applied=True,
            decision_reason="applied",
            failed_open=False,
            failure_reason=None,
            elapsed_total_ms=5.0,
        )
        assert record.tool_name == "view_file"
        assert record.applied is True
        assert record.failed_open is False
        assert record.failure_reason is None
        assert record.warnings == []
        assert record.correlation_id is None
        assert record.message_index is None

    def test_full_creation(self) -> None:
        """Can create record with all fields populated."""
        record = CompactionEventRecord(
            correlation_id="corr-123",
            tool_call_id="tc-456",
            tool_name="grep_search",
            tool_category="search",
            resource_identity_hash="deadbeef",
            resource_identity_preview="grep:pattern...",
            resource_preview_redacted=True,
            original_bytes=10000,
            compacted_bytes=2000,
            saved_bytes=8000,
            original_tokens_estimate=2500,
            saved_tokens_estimate=2000,
            applied=True,
            decision_reason="applied",
            failed_open=False,
            failure_reason=None,
            elapsed_total_ms=45.2,
            original_sha256="orig_sha",
            compacted_sha256="compact_sha",
            warnings=["large output"],
            message_index=3,
        )
        assert record.correlation_id == "corr-123"
        assert record.tool_call_id == "tc-456"
        assert record.resource_preview_redacted is True
        assert record.original_sha256 == "orig_sha"
        assert record.compacted_sha256 == "compact_sha"
        assert record.warnings == ["large output"]
        assert record.message_index == 3

    def test_decision_reason_values(self) -> None:
        """All expected decision reason values are accepted."""
        valid_reasons = [
            "feature_disabled",
            "below_token_threshold",
            "no_tool_results",
            "no_stale_results",
            "policy_denied",
            "below_min_output_size",
            "already_compacted",
            "applied",
            "fail_open",
        ]
        for reason in valid_reasons:
            record = _make_event(decision_reason=reason)
            assert record.decision_reason == reason

    def test_fail_open_with_failure_reason(self) -> None:
        """Fail-open records include failure reason."""
        record = _make_event(
            failed_open=True,
            failure_reason="database timeout",
            decision_reason="fail_open",
            applied=False,
        )
        assert record.failed_open is True
        assert record.failure_reason == "database timeout"
        assert record.applied is False

    def test_saved_bytes_computed_correctly(self) -> None:
        """saved_bytes = original_bytes - compacted_bytes."""
        record = _make_event(original_bytes=8000, compacted_bytes=2000)
        assert record.saved_bytes == 6000

    def test_not_applied_zero_saved(self) -> None:
        """Non-applied events have zero savings."""
        record = _make_event(
            applied=False,
            decision_reason="policy_denied",
            original_bytes=5000,
            compacted_bytes=5000,
        )
        assert record.applied is False
        assert record.saved_bytes == 0
        assert record.decision_reason == "policy_denied"

    def test_model_dump_roundtrip(self) -> None:
        """Can serialize to dict and reconstruct."""
        original = _make_event(
            correlation_id="corr-1",
            tool_name="run_command",
            tool_category="command_execution",
            applied=False,
            decision_reason="policy_denied",
            warnings=["category denied"],
        )
        dumped = original.model_dump()
        restored = CompactionEventRecord(**dumped)
        assert restored.tool_name == original.tool_name
        assert restored.decision_reason == original.decision_reason
        assert restored.warnings == original.warnings


# ─── CompactionAggregateMetrics ──────────────────────────────────────

class TestCompactionAggregateMetrics:
    """Tests for running aggregate stats."""

    def test_initial_state(self) -> None:
        """Fresh aggregate has zero counters."""
        metrics = CompactionAggregateMetrics()
        assert metrics.processed_evaluations == 0
        assert metrics.applied_evaluations == 0
        assert metrics.fail_open_count == 0
        assert metrics.total_original_bytes == 0
        assert metrics.total_compacted_bytes == 0
        assert metrics.total_saved_bytes == 0
        assert metrics.total_saved_tokens_estimate == 0
        assert metrics.by_category == {}
        assert metrics.by_decision_reason == {}

    def test_model_copy_deep(self) -> None:
        """Deep copy produces independent instance."""
        metrics = CompactionAggregateMetrics(
            processed_evaluations=10,
            by_category={"file_read": 5, "search": 5},
        )
        copy = metrics.model_copy(deep=True)
        copy.by_category["file_read"] = 999
        assert metrics.by_category["file_read"] == 5


# ─── CompactionAlertRecord ──────────────────────────────────────────

class TestCompactionAlertRecord:
    """Tests for rate-limited alert model."""

    def test_minimal_alert(self) -> None:
        """Can create alert with required fields."""
        alert = CompactionAlertRecord(
            alert_type="fail_open_frequency",
            threshold=3,
            observed_count=5,
            window_seconds=300,
            warning="Fail-open events are frequent",
        )
        assert alert.alert_type == "fail_open_frequency"
        assert alert.category is None

    def test_alert_with_category(self) -> None:
        """Alert can include optional category."""
        alert = CompactionAlertRecord(
            alert_type="overflow_risk",
            threshold=3,
            observed_count=4,
            window_seconds=300,
            warning="Overflow risk detected",
            category="file_read",
        )
        assert alert.category == "file_read"

    def test_alert_serialization(self) -> None:
        """Alert serializes correctly."""
        alert = CompactionAlertRecord(
            alert_type="fail_open_frequency",
            threshold=3,
            observed_count=10,
            window_seconds=600,
            warning="Frequent failures",
            category="command_execution",
        )
        dumped = alert.model_dump()
        assert dumped["alert_type"] == "fail_open_frequency"
        assert dumped["category"] == "command_execution"


# ─── EffectiveCompactionConfigDiagnostics ────────────────────────────

class TestEffectiveCompactionConfigDiagnostics:
    """Tests for effective config snapshot."""

    def test_initial_state(self) -> None:
        """Fresh diagnostics has empty collections."""
        diag = EffectiveCompactionConfigDiagnostics()
        assert diag.active_controls == []
        assert diag.inactive_controls == []
        assert diag.ignored_controls == []
        assert diag.reasons == {}
        assert diag.fingerprint is None
        assert diag.warnings == []

    def test_populated_diagnostics(self) -> None:
        """Can create with populated fields."""
        diag = EffectiveCompactionConfigDiagnostics(
            active_controls=["token_budget", "staleness_detection"],
            inactive_controls=["aggressive_compaction"],
            ignored_controls=["legacy_mode"],
            reasons={
                "aggressive_compaction": "feature disabled in config",
                "legacy_mode": "not applicable",
            },
            fingerprint="fp-123",
            warnings=["config has conflicting settings"],
        )
        assert len(diag.active_controls) == 2
        assert len(diag.reasons) == 2
        assert diag.fingerprint == "fp-123"


# ─── CompactionAlertsConfig ──────────────────────────────────────────

class TestCompactionAlertsConfig:
    """Tests for alert configuration."""

    def test_default_values(self) -> None:
        """Default config has correct values."""
        config = CompactionAlertsConfig()
        assert config.enabled is False
        assert config.window_seconds == 300
        assert config.cooldown_seconds == 600
        assert config.fail_open_threshold == 3
        assert config.overflow_risk_threshold == 3
        assert config.no_op_above_threshold_threshold == 5

    def test_from_dict_all_fields(self) -> None:
        """Can override all fields from dict."""
        data = {
            "enabled": True,
            "window_seconds": 600,
            "cooldown_seconds": 1200,
            "fail_open_threshold": 5,
            "overflow_risk_threshold": 4,
            "no_op_above_threshold_threshold": 10,
        }
        config = CompactionAlertsConfig.from_dict(data)
        assert config.enabled is True
        assert config.window_seconds == 600
        assert config.cooldown_seconds == 1200
        assert config.fail_open_threshold == 5
        assert config.overflow_risk_threshold == 4
        assert config.no_op_above_threshold_threshold == 10

    def test_from_dict_partial(self) -> None:
        """Partial dict uses defaults for missing fields."""
        config = CompactionAlertsConfig.from_dict({"enabled": True})
        assert config.enabled is True
        assert config.window_seconds == 300  # default
        assert config.fail_open_threshold == 3  # default


# ─── CompactionConfig with alerts ───────────────────────────────────

class TestCompactionConfigWithAlerts:
    """Tests for alerts field integration in CompactionConfig."""

    def test_default_has_alerts(self) -> None:
        """Default config includes alerts field."""
        config = CompactionConfig()
        assert hasattr(config, "alerts")
        assert isinstance(config.alerts, CompactionAlertsConfig)
        assert config.alerts.enabled is False

    def test_default_factory_has_alerts(self) -> None:
        """CompactionConfig.default() includes alerts."""
        config = CompactionConfig.default()
        assert hasattr(config, "alerts")
        assert isinstance(config.alerts, CompactionAlertsConfig)

    def test_disabled_factory_has_alerts(self) -> None:
        """CompactionConfig.disabled() includes alerts."""
        config = CompactionConfig.disabled()
        assert hasattr(config, "alerts")
        assert isinstance(config.alerts, CompactionAlertsConfig)

    def test_from_dict_includes_alerts(self) -> None:
        """from_dict creates alerts config."""
        data = {
            "enabled": True,
            "token_threshold": 50_000,
            "alerts": {
                "enabled": True,
                "fail_open_threshold": 10,
            },
        }
        config = CompactionConfig.from_dict(data)
        assert config.alerts.enabled is True
        assert config.alerts.fail_open_threshold == 10

    def test_from_dict_without_alerts_uses_default(self) -> None:
        """from_dict without alerts key uses default alerts."""
        data = {"enabled": True}
        config = CompactionConfig.from_dict(data)
        assert isinstance(config.alerts, CompactionAlertsConfig)
        assert config.alerts.enabled is False  # default


# ─── CompactionMetricsRecorder ──────────────────────────────────────

class TestCompactionMetricsRecorder:
    """Tests for metrics recorder: aggregation, alert thresholds, cooldown."""

    def test_initial_snapshot(self) -> None:
        """Fresh recorder has zero metrics."""
        recorder = CompactionMetricsRecorder()
        snapshot = recorder.snapshot()
        assert snapshot.processed_evaluations == 0
        assert snapshot.applied_evaluations == 0
        assert snapshot.fail_open_count == 0
        assert snapshot.total_saved_bytes == 0

    def test_record_single_applied_event(self) -> None:
        """Recording an applied event updates aggregates."""
        recorder = CompactionMetricsRecorder()
        event = _make_event(
            tool_name="view_file",
            tool_category="file_read",
            applied=True,
            decision_reason="applied",
            original_bytes=5000,
            compacted_bytes=1500,
        )
        alerts = recorder.record(event, alerts_config=CompactionAlertsConfig())
        assert alerts == []  # alerts disabled by default

        snapshot = recorder.snapshot()
        assert snapshot.processed_evaluations == 1
        assert snapshot.applied_evaluations == 1
        assert snapshot.total_original_bytes == 5000
        assert snapshot.total_compacted_bytes == 1500
        assert snapshot.total_saved_bytes == 3500
        assert snapshot.by_category.get("file_read") == 1
        assert snapshot.by_decision_reason.get("applied") == 1

    def test_record_non_applied_event(self) -> None:
        """Non-applied event increments processed but not applied."""
        recorder = CompactionMetricsRecorder()
        event = _make_event(
            applied=False,
            decision_reason="policy_denied",
            original_bytes=3000,
            compacted_bytes=3000,
        )
        recorder.record(event, alerts_config=CompactionAlertsConfig())
        snapshot = recorder.snapshot()
        assert snapshot.processed_evaluations == 1
        assert snapshot.applied_evaluations == 0
        assert snapshot.total_saved_bytes == 0
        assert snapshot.by_decision_reason.get("policy_denied") == 1

    def test_record_fail_open_event(self) -> None:
        """Fail-open event increments fail_open_count."""
        recorder = CompactionMetricsRecorder()
        event = _make_event(
            failed_open=True,
            failure_reason="timeout",
            decision_reason="fail_open",
            applied=False,
        )
        recorder.record(event, alerts_config=CompactionAlertsConfig())
        snapshot = recorder.snapshot()
        assert snapshot.fail_open_count == 1

    def test_record_multiple_events_aggregate(self) -> None:
        """Multiple events accumulate correctly."""
        recorder = CompactionMetricsRecorder()
        for i in range(5):
            event = _make_event(
                tool_category="file_read" if i < 3 else "search",
                applied=i < 4,
                original_bytes=1000 * (i + 1),
                compacted_bytes=500,
            )
            recorder.record(event, alerts_config=CompactionAlertsConfig())

        snapshot = recorder.snapshot()
        assert snapshot.processed_evaluations == 5
        assert snapshot.applied_evaluations == 4
        assert snapshot.by_category.get("file_read") == 3
        assert snapshot.by_category.get("search") == 2

    def test_alerts_disabled_returns_empty(self) -> None:
        """When alerts disabled, record returns no alerts."""
        recorder = CompactionMetricsRecorder()
        event = _make_event(failed_open=True)
        config = CompactionAlertsConfig(enabled=False)
        alerts = recorder.record(event, alerts_config=config)
        assert alerts == []

    def test_fail_open_alert_threshold(self) -> None:
        """Alert emitted when fail-open count reaches threshold."""
        recorder = CompactionMetricsRecorder()
        alerts_config = CompactionAlertsConfig(
            enabled=True,
            fail_open_threshold=3,
            window_seconds=300,
            cooldown_seconds=600,
        )

        # Below threshold — no alerts
        for _ in range(2):
            event = _make_event(failed_open=True, applied=False, decision_reason="fail_open")
            alerts = recorder.record(event, alerts_config=alerts_config)
            assert alerts == []

        # At threshold — alert emitted
        event = _make_event(failed_open=True, applied=False, decision_reason="fail_open")
        alerts = recorder.record(event, alerts_config=alerts_config)
        assert len(alerts) == 1
        assert alerts[0].alert_type == "fail_open_frequency"
        assert alerts[0].observed_count == 3
        assert alerts[0].threshold == 3

    def test_alert_cooldown_prevents_duplicate(self) -> None:
        """After emitting an alert, cooldown prevents immediate re-emission."""
        recorder = CompactionMetricsRecorder()
        alerts_config = CompactionAlertsConfig(
            enabled=True,
            fail_open_threshold=2,
            window_seconds=300,
            cooldown_seconds=600,
        )

        # Trigger first alert
        for _ in range(2):
            event = _make_event(failed_open=True, applied=False, decision_reason="fail_open")
            recorder.record(event, alerts_config=alerts_config)

        # More events within cooldown — no new alerts
        event = _make_event(failed_open=True, applied=False, decision_reason="fail_open")
        alerts = recorder.record(event, alerts_config=alerts_config)
        assert alerts == []

    def test_overflow_risk_alert(self) -> None:
        """Alert emitted when overflow-risk count reaches threshold."""
        recorder = CompactionMetricsRecorder()
        alerts_config = CompactionAlertsConfig(
            enabled=True,
            overflow_risk_threshold=3,
            window_seconds=300,
            cooldown_seconds=600,
        )

        # Simulate overflow risk events via no_op_above_threshold decision
        for _ in range(3):
            event = _make_event(
                applied=False,
                decision_reason="fail_open",
            )
            alerts = recorder.record(event, alerts_config=alerts_config)

        # The overflow_risk alert should trigger based on fail_open count
        # when it exceeds overflow_risk_threshold
        assert any(a.alert_type == "overflow_risk" for a in alerts)

    def test_snapshot_is_independent(self) -> None:
        """Snapshot returns independent copy."""
        recorder = CompactionMetricsRecorder()
        event = _make_event()
        recorder.record(event, alerts_config=CompactionAlertsConfig())

        snapshot1 = recorder.snapshot()
        snapshot1.processed_evaluations = 9999
        snapshot2 = recorder.snapshot()
        assert snapshot2.processed_evaluations == 1

    def test_concurrent_record_thread_safety(self) -> None:
        """Concurrent record calls don't corrupt state."""
        recorder = CompactionMetricsRecorder()
        num_threads = 20
        events_per_thread = 50

        def record_batch(thread_id: int) -> None:
            for _i in range(events_per_thread):
                event = _make_event(
                    tool_category=f"cat_{thread_id % 3}",
                    original_bytes=1000,
                    compacted_bytes=500,
                )
                recorder.record(event, alerts_config=CompactionAlertsConfig())

        threads: list[threading.Thread] = []
        for t in range(num_threads):
            thread = threading.Thread(target=record_batch, args=(t,))
            threads.append(thread)

        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        snapshot = recorder.snapshot()
        expected = num_threads * events_per_thread
        assert snapshot.processed_evaluations == expected
        assert snapshot.total_saved_bytes == expected * 500

    def test_concurrent_snapshot_during_records(self) -> None:
        """Snapshot can be called while records are being written."""
        recorder = CompactionMetricsRecorder()
        errors: list[Exception] = []

        def writer() -> None:
            try:
                for _ in range(100):
                    event = _make_event()
                    recorder.record(event, alerts_config=CompactionAlertsConfig())
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        def reader() -> None:
            try:
                for _ in range(50):
                    snapshot = recorder.snapshot()
                    assert snapshot.processed_evaluations >= 0
                    time.sleep(0.002)
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=writer)
        t2 = threading.Thread(target=reader)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert errors == [], f"Concurrent access errors: {errors}"

    def test_large_counts(self) -> None:
        """Handles large event counts without overflow."""
        recorder = CompactionMetricsRecorder()
        for _ in range(100_000):
            event = _make_event(
                original_bytes=10_000,
                compacted_bytes=5_000,
            )
            recorder.record(event, alerts_config=CompactionAlertsConfig())

        snapshot = recorder.snapshot()
        assert snapshot.processed_evaluations == 100_000
        assert snapshot.total_original_bytes == 1_000_000_000
        assert snapshot.total_saved_bytes == 500_000_000

    def test_alert_warning_message_content(self) -> None:
        """Alert warning message contains useful diagnostics."""
        recorder = CompactionMetricsRecorder()
        alerts_config = CompactionAlertsConfig(
            enabled=True,
            fail_open_threshold=2,
            window_seconds=300,
        )

        for _ in range(2):
            event = _make_event(failed_open=True, applied=False, decision_reason="fail_open")
            recorder.record(event, alerts_config=alerts_config)

        alerts = recorder.record(
            _make_event(failed_open=True, applied=False, decision_reason="fail_open"),
            alerts_config=alerts_config,
        )
        assert len(alerts) == 1
        warning = alerts[0].warning
        assert "fail_open" in warning.lower() or "fail-open" in warning.lower()
        assert "count=" in warning
        assert "window_seconds=" in warning
