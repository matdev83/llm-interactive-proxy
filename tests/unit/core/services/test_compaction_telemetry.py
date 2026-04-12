"""Tests for compaction telemetry models and metrics recorder."""

from __future__ import annotations

import pytest
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


class TestCompactionEventRecord:
    def test_defaults(self) -> None:
        record = CompactionEventRecord()
        assert record.applied is False
        assert record.decision_reason == "no_stale_results"
        assert record.failed_open is False
        assert record.saved_bytes == 0
        assert record.warnings == []

    def test_serialization(self) -> None:
        record = CompactionEventRecord(
            correlation_id="cmp_01",
            tool_call_id="call_abc",
            tool_name="read",
            tool_category="file_read",
            resource_identity_hash="sha256:abc123",
            resource_identity_preview="src/foo.py",
            original_bytes=12450,
            compacted_bytes=146,
            saved_bytes=12304,
            original_tokens_estimate=3112,
            saved_tokens_estimate=3076,
            applied=True,
            decision_reason="applied",
            elapsed_total_ms=1.72,
            original_sha256="sha256:orig",
            compacted_sha256="sha256:comp",
        )
        dumped = record.model_dump(mode="json")
        assert dumped["tool_name"] == "read"
        assert dumped["saved_bytes"] == 12304
        assert dumped["applied"] is True
        assert dumped["decision_reason"] == "applied"

    def test_negative_bytes_rejected(self) -> None:
        with pytest.raises(ValueError):
            CompactionEventRecord(original_bytes=-1)


class TestCompactionAggregateMetrics:
    def test_defaults(self) -> None:
        metrics = CompactionAggregateMetrics()
        assert metrics.processed_evaluations == 0
        assert metrics.total_saved_bytes == 0
        assert metrics.by_category == {}
        assert metrics.by_decision_reason == {}

    def test_deep_copy(self) -> None:
        metrics = CompactionAggregateMetrics(
            processed_evaluations=1,
            by_category={"file_read": 1},
            by_decision_reason={"applied": 1},
        )
        copy = metrics.model_copy(deep=True)
        copy.by_category["file_read"] = 5
        assert metrics.by_category["file_read"] == 1


class TestCompactionAlertRecord:
    def test_minimal(self) -> None:
        alert = CompactionAlertRecord(
            alert_type="fail_open_rate",
            threshold=3,
            observed_count=3,
            window_seconds=300,
            warning="test",
        )
        assert alert.category is None

    def test_with_category(self) -> None:
        alert = CompactionAlertRecord(
            alert_type="overflow_risk_rate",
            threshold=3,
            observed_count=5,
            window_seconds=300,
            warning="test",
            category="file_read",
        )
        assert alert.category == "file_read"


class TestEffectiveCompactionConfigDiagnostics:
    def test_defaults(self) -> None:
        diag = EffectiveCompactionConfigDiagnostics()
        assert diag.active_controls == []
        assert diag.inactive_controls == []
        assert diag.ignored_controls == []
        assert diag.reasons == {}
        assert diag.fingerprint is None
        assert diag.warnings == []


class TestCompactionAlertsConfig:
    def test_defaults(self) -> None:
        config = CompactionAlertsConfig()
        assert config.enabled is False
        assert config.window_seconds == 300
        assert config.cooldown_seconds == 600
        assert config.fail_open_threshold == 3
        assert config.overflow_risk_threshold == 3
        assert config.no_op_above_threshold_threshold == 5


class TestCompactionConfigAlerts:
    def test_default_config_has_alerts(self) -> None:
        config = CompactionConfig.default()
        assert config.alerts is not None
        assert config.alerts.enabled is False

    def test_disabled_config_has_alerts(self) -> None:
        config = CompactionConfig.disabled()
        assert config.alerts is not None
        assert config.alerts.enabled is False

    def test_from_dict_with_alerts(self) -> None:
        config = CompactionConfig.from_dict(
            {
                "enabled": True,
                "alerts": {
                    "enabled": True,
                    "window_seconds": 600,
                    "cooldown_seconds": 1200,
                    "fail_open_threshold": 5,
                    "overflow_risk_threshold": 4,
                    "no_op_above_threshold_threshold": 7,
                },
            }
        )
        assert config.enabled is True
        assert config.alerts.enabled is True
        assert config.alerts.window_seconds == 600
        assert config.alerts.cooldown_seconds == 1200
        assert config.alerts.fail_open_threshold == 5
        assert config.alerts.overflow_risk_threshold == 4
        assert config.alerts.no_op_above_threshold_threshold == 7


class TestCompactionMetricsRecorder:
    def test_empty_snapshot(self) -> None:
        recorder = CompactionMetricsRecorder()
        snapshot = recorder.snapshot()
        assert snapshot.processed_evaluations == 0
        assert snapshot.total_saved_bytes == 0

    def test_record_applied_event(self) -> None:
        recorder = CompactionMetricsRecorder()
        record = CompactionEventRecord(
            tool_name="read",
            tool_category="file_read",
            resource_identity_hash="sha256:abc",
            original_bytes=10000,
            compacted_bytes=100,
            saved_bytes=9900,
            original_tokens_estimate=2500,
            saved_tokens_estimate=2475,
            applied=True,
            decision_reason="applied",
        )
        alerts = recorder.record(
            record,
            alerts_config=CompactionAlertsConfig(enabled=False),
        )
        assert alerts == []

        snapshot = recorder.snapshot()
        assert snapshot.processed_evaluations == 1
        assert snapshot.applied_evaluations == 1
        assert snapshot.total_original_bytes == 10000
        assert snapshot.total_saved_bytes == 9900
        assert snapshot.by_category["file_read"] == 1
        assert snapshot.by_decision_reason["applied"] == 1

    def test_record_failed_open_emits_no_alert_when_disabled(self) -> None:
        recorder = CompactionMetricsRecorder()
        record = CompactionEventRecord(
            tool_name="read",
            tool_category="file_read",
            resource_identity_hash="sha256:abc",
            original_bytes=5000,
            compacted_bytes=5000,
            saved_bytes=0,
            applied=False,
            decision_reason="fail_open",
            failed_open=True,
            failure_reason="unexpected error",
        )
        alerts = recorder.record(
            record,
            alerts_config=CompactionAlertsConfig(enabled=False),
        )
        assert alerts == []

        snapshot = recorder.snapshot()
        assert snapshot.fail_open_count == 1

    def test_fail_open_alert_emitted_after_threshold(self) -> None:
        recorder = CompactionMetricsRecorder()
        alerts_config = CompactionAlertsConfig(
            enabled=True,
            fail_open_threshold=2,
            window_seconds=300,
            cooldown_seconds=600,
        )

        for _ in range(2):
            record = CompactionEventRecord(
                tool_name="read",
                tool_category="file_read",
                resource_identity_hash="sha256:abc",
                original_bytes=5000,
                compacted_bytes=5000,
                saved_bytes=0,
                applied=False,
                decision_reason="fail_open",
                failed_open=True,
                failure_reason="unexpected error",
            )
            alerts = recorder.record(record, alerts_config=alerts_config)

        assert len(alerts) >= 1
        assert alerts[0].alert_type == "fail_open_rate"
        assert alerts[0].category == "file_read"

    def test_multiple_records_aggregate(self) -> None:
        recorder = CompactionMetricsRecorder()
        alerts_config = CompactionAlertsConfig(enabled=False)

        for i in range(3):
            record = CompactionEventRecord(
                tool_name="read" if i < 2 else "fff_multi_grep",
                tool_category="file_read" if i < 2 else "search",
                resource_identity_hash=f"sha256:{i}",
                original_bytes=1000,
                compacted_bytes=100,
                saved_bytes=900,
                original_tokens_estimate=250,
                saved_tokens_estimate=225,
                applied=True,
                decision_reason="applied",
            )
            recorder.record(record, alerts_config=alerts_config)

        snapshot = recorder.snapshot()
        assert snapshot.processed_evaluations == 3
        assert snapshot.applied_evaluations == 3
        assert snapshot.total_saved_bytes == 2700
        assert snapshot.by_category["file_read"] == 2
        assert snapshot.by_category["search"] == 1

    def test_no_op_record(self) -> None:
        recorder = CompactionMetricsRecorder()
        record = CompactionEventRecord(
            tool_name="read",
            tool_category="file_read",
            resource_identity_hash="sha256:abc",
            original_bytes=0,
            compacted_bytes=0,
            saved_bytes=0,
            applied=False,
            decision_reason="no_stale_results",
        )
        recorder.record(record, alerts_config=CompactionAlertsConfig(enabled=False))

        snapshot = recorder.snapshot()
        assert snapshot.processed_evaluations == 1
        assert snapshot.applied_evaluations == 0
        assert snapshot.by_decision_reason["no_stale_results"] == 1

    def test_no_op_above_threshold_alert_emitted_after_threshold(self) -> None:
        recorder = CompactionMetricsRecorder()
        alerts_config = CompactionAlertsConfig(
            enabled=True,
            no_op_above_threshold_threshold=2,
            window_seconds=300,
            cooldown_seconds=600,
        )

        for _ in range(2):
            record = CompactionEventRecord(
                tool_name="read",
                tool_category="file_read",
                resource_identity_hash="sha256:abc",
                original_bytes=8000,
                compacted_bytes=8000,
                saved_bytes=0,
                applied=False,
                decision_reason="no_op_above_threshold",
                failed_open=False,
            )
            alerts = recorder.record(record, alerts_config=alerts_config)

        assert len(alerts) == 1
        assert alerts[0].alert_type == "no_op_above_threshold_rate"
        assert alerts[0].threshold == 2
