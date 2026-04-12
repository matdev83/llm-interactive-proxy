"""Aggregate compaction metrics and rate-safe alerting."""

from __future__ import annotations

import time
from dataclasses import dataclass
from threading import Lock

from src.core.domain.compaction_telemetry import (
    CompactionAggregateMetrics,
    CompactionAlertRecord,
    CompactionEventRecord,
)
from src.core.domain.configuration.compaction_config import CompactionAlertsConfig


@dataclass
class _AlertState:
    count: int = 0
    window_started_at: float = 0.0
    last_emitted_at: float = 0.0


class CompactionMetricsRecorder:
    """Collect aggregate metrics and emit rate-limited alert records."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._metrics = CompactionAggregateMetrics()
        self._fail_open_alert_state: dict[str, _AlertState] = {}
        self._overflow_alert_state: dict[str, _AlertState] = {}
        self._no_op_alert_state: dict[str, _AlertState] = {}

    def record(
        self,
        record: CompactionEventRecord,
        *,
        alerts_config: CompactionAlertsConfig,
    ) -> list[CompactionAlertRecord]:
        """Record one compaction event and return emitted alerts."""
        now = time.monotonic()
        with self._lock:
            self._record_locked(record)
            if not alerts_config.enabled:
                return []
            alerts: list[CompactionAlertRecord] = []
            alerts.extend(
                self._evaluate_fail_open_alerts_locked(
                    record=record,
                    alerts_config=alerts_config,
                    now=now,
                )
            )
            alerts.extend(
                self._evaluate_overflow_alerts_locked(
                    record=record,
                    alerts_config=alerts_config,
                    now=now,
                )
            )
            alerts.extend(
                self._evaluate_no_op_alerts_locked(
                    record=record,
                    alerts_config=alerts_config,
                    now=now,
                )
            )
            return alerts

    def snapshot(self) -> CompactionAggregateMetrics:
        """Return a deterministic deep copy of current aggregate metrics."""
        with self._lock:
            return self._metrics.model_copy(deep=True)

    def _record_locked(self, record: CompactionEventRecord) -> None:
        self._metrics.processed_evaluations += 1
        if record.applied:
            self._metrics.applied_evaluations += 1
        if record.failed_open:
            self._metrics.fail_open_count += 1
        self._metrics.total_original_bytes += record.original_bytes
        self._metrics.total_compacted_bytes += record.compacted_bytes
        self._metrics.total_saved_bytes += record.saved_bytes
        self._metrics.total_saved_tokens_estimate += record.saved_tokens_estimate

        category_key = record.tool_category or "unknown"
        self._metrics.by_category[category_key] = (
            self._metrics.by_category.get(category_key, 0) + 1
        )

        reason_key = record.decision_reason or "unknown"
        self._metrics.by_decision_reason[reason_key] = (
            self._metrics.by_decision_reason.get(reason_key, 0) + 1
        )

    @staticmethod
    def _bump_alert_counter(
        *,
        state: _AlertState,
        now: float,
        window_seconds: int,
    ) -> int:
        if state.window_started_at <= 0.0 or (now - state.window_started_at) >= float(
            window_seconds
        ):
            state.window_started_at = now
            state.count = 0
        state.count += 1
        return state.count

    def _evaluate_fail_open_alerts_locked(
        self,
        *,
        record: CompactionEventRecord,
        alerts_config: CompactionAlertsConfig,
        now: float,
    ) -> list[CompactionAlertRecord]:
        if not record.failed_open:
            return []
        state = self._fail_open_alert_state.setdefault(
            record.tool_category or "unknown", _AlertState()
        )
        observed_count = self._bump_alert_counter(
            state=state,
            now=now,
            window_seconds=alerts_config.window_seconds,
        )
        cooldown_elapsed = state.last_emitted_at <= 0.0 or (
            now - state.last_emitted_at
        ) >= float(alerts_config.cooldown_seconds)
        if observed_count >= alerts_config.fail_open_threshold and cooldown_elapsed:
            warning = (
                "History compaction fail-open events are frequent; "
                f"category={record.tool_category}, count={observed_count}, "
                f"window_seconds={alerts_config.window_seconds}."
            )
            alert = CompactionAlertRecord(
                alert_type="fail_open_rate",
                threshold=alerts_config.fail_open_threshold,
                observed_count=observed_count,
                window_seconds=alerts_config.window_seconds,
                category=record.tool_category or None,
                warning=warning,
            )
            state.last_emitted_at = now
            state.window_started_at = now
            state.count = 0
            return [alert]
        return []

    def _evaluate_overflow_alerts_locked(
        self,
        *,
        record: CompactionEventRecord,
        alerts_config: CompactionAlertsConfig,
        now: float,
    ) -> list[CompactionAlertRecord]:
        if record.decision_reason != "fail_open" and not record.failed_open:
            return []
        if not record.failure_reason or "overflow" not in record.failure_reason.lower():
            return []
        state = self._overflow_alert_state.setdefault(
            record.tool_category or "unknown", _AlertState()
        )
        observed_count = self._bump_alert_counter(
            state=state,
            now=now,
            window_seconds=alerts_config.window_seconds,
        )
        cooldown_elapsed = state.last_emitted_at <= 0.0 or (
            now - state.last_emitted_at
        ) >= float(alerts_config.cooldown_seconds)
        if observed_count >= alerts_config.overflow_risk_threshold and cooldown_elapsed:
            warning = (
                "History compaction overflow-risk events are frequent; "
                f"category={record.tool_category}, count={observed_count}, "
                f"window_seconds={alerts_config.window_seconds}."
            )
            alert = CompactionAlertRecord(
                alert_type="overflow_risk_rate",
                threshold=alerts_config.overflow_risk_threshold,
                observed_count=observed_count,
                window_seconds=alerts_config.window_seconds,
                category=record.tool_category or None,
                warning=warning,
            )
            state.last_emitted_at = now
            state.window_started_at = now
            state.count = 0
            return [alert]
        return []

    def _evaluate_no_op_alerts_locked(
        self,
        *,
        record: CompactionEventRecord,
        alerts_config: CompactionAlertsConfig,
        now: float,
    ) -> list[CompactionAlertRecord]:
        if record.decision_reason != "no_op_above_threshold":
            return []
        state = self._no_op_alert_state.setdefault(
            record.tool_category or "unknown", _AlertState()
        )
        observed_count = self._bump_alert_counter(
            state=state,
            now=now,
            window_seconds=alerts_config.window_seconds,
        )
        cooldown_elapsed = state.last_emitted_at <= 0.0 or (
            now - state.last_emitted_at
        ) >= float(alerts_config.cooldown_seconds)
        if (
            observed_count >= alerts_config.no_op_above_threshold_threshold
            and cooldown_elapsed
        ):
            warning = (
                "History compaction no-op evaluations above threshold are frequent; "
                f"category={record.tool_category}, count={observed_count}, "
                f"window_seconds={alerts_config.window_seconds}."
            )
            alert = CompactionAlertRecord(
                alert_type="no_op_above_threshold_rate",
                threshold=alerts_config.no_op_above_threshold_threshold,
                observed_count=observed_count,
                window_seconds=alerts_config.window_seconds,
                category=record.tool_category or None,
                warning=warning,
            )
            state.last_emitted_at = now
            state.window_started_at = now
            state.count = 0
            return [alert]
        return []
