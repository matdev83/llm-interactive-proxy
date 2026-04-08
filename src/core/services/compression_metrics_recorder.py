"""Aggregate compression metrics and rate-safe alerting."""

from __future__ import annotations

import time
from dataclasses import dataclass
from threading import Lock

from src.core.domain.configuration.dynamic_compression_config import (
    CompressionAlertsConfig,
)
from src.core.domain.dynamic_compression import (
    CompressionAggregateMetrics,
    CompressionAlertRecord,
    CompressionMethodAggregate,
    ToolOutputCompressionRecord,
)


@dataclass
class _AlertState:
    count: int = 0
    window_started_at: float = 0.0
    last_emitted_at: float = 0.0


class CompressionMetricsRecorder:
    """Collect aggregate metrics and emit rate-limited alert records."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._metrics = CompressionAggregateMetrics()
        self._failure_alert_state: dict[str, _AlertState] = {}
        self._fallback_alert_state: dict[str, _AlertState] = {}

    def record(
        self,
        record: ToolOutputCompressionRecord,
        *,
        alerts_config: CompressionAlertsConfig,
    ) -> list[CompressionAlertRecord]:
        """Record one per-output telemetry record and return emitted alerts."""
        now = time.monotonic()
        with self._lock:
            self._record_locked(record)
            if not alerts_config.enabled:
                return []
            alerts: list[CompressionAlertRecord] = []
            alerts.extend(
                self._evaluate_failure_alerts_locked(
                    record=record,
                    alerts_config=alerts_config,
                    now=now,
                )
            )
            alerts.extend(
                self._evaluate_fallback_alerts_locked(
                    record=record,
                    alerts_config=alerts_config,
                    now=now,
                )
            )
            return alerts

    def snapshot(self) -> CompressionAggregateMetrics:
        """Return a deterministic deep copy of current aggregate metrics."""
        with self._lock:
            return self._metrics.model_copy(deep=True)

    def _record_locked(self, record: ToolOutputCompressionRecord) -> None:
        self._metrics.processed_outputs += 1
        if record.applied:
            self._metrics.compressed_outputs += 1
        if record.failed_open:
            self._metrics.fail_open_count += 1
        if record.fallback_applied:
            self._metrics.fallback_count += 1
        self._metrics.total_original_bytes += record.original_bytes
        self._metrics.total_compressed_bytes += record.compressed_bytes
        self._metrics.total_saved_bytes += record.saved_bytes
        self._metrics.total_saved_tokens_estimate += (record.saved_bytes + 3) // 4

        category_key = record.identity.tool_category
        self._metrics.by_category[category_key] = (
            self._metrics.by_category.get(category_key, 0) + 1
        )
        level_key = record.final_level.value
        self._metrics.by_level[level_key] = self._metrics.by_level.get(level_key, 0) + 1

        for method in record.methods:
            aggregate = self._metrics.by_method.get(method.name)
            if aggregate is None:
                aggregate = CompressionMethodAggregate()
                self._metrics.by_method[method.name] = aggregate
            aggregate.attempts += 1
            if method.applied:
                aggregate.applied += 1
            if method.error:
                aggregate.failures += 1
            if method.skipped_reason:
                aggregate.fallbacks += 1
            aggregate.bytes_saved += max(0, method.original_bytes - method.result_bytes)
            aggregate.elapsed_ms_total += method.elapsed_ms

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

    def _evaluate_failure_alerts_locked(
        self,
        *,
        record: ToolOutputCompressionRecord,
        alerts_config: CompressionAlertsConfig,
        now: float,
    ) -> list[CompressionAlertRecord]:
        alerts: list[CompressionAlertRecord] = []
        for method in record.methods:
            if not method.error:
                continue
            state = self._failure_alert_state.setdefault(method.name, _AlertState())
            observed_count = self._bump_alert_counter(
                state=state,
                now=now,
                window_seconds=alerts_config.window_seconds,
            )
            cooldown_elapsed = state.last_emitted_at <= 0.0 or (
                now - state.last_emitted_at
            ) >= float(alerts_config.cooldown_seconds)
            if observed_count >= alerts_config.failure_threshold and cooldown_elapsed:
                warning = (
                    "Dynamic compression strategy failures are frequent; "
                    f"method={method.name}, count={observed_count}, "
                    f"window_seconds={alerts_config.window_seconds}."
                )
                alerts.append(
                    CompressionAlertRecord(
                        alert_type="method_failure_rate",
                        method=method.name,
                        threshold=alerts_config.failure_threshold,
                        observed_count=observed_count,
                        window_seconds=alerts_config.window_seconds,
                        category=record.identity.tool_category,
                        level=record.final_level,
                        warning=warning,
                    )
                )
                state.last_emitted_at = now
                state.window_started_at = now
                state.count = 0
        return alerts

    def _evaluate_fallback_alerts_locked(
        self,
        *,
        record: ToolOutputCompressionRecord,
        alerts_config: CompressionAlertsConfig,
        now: float,
    ) -> list[CompressionAlertRecord]:
        alerts: list[CompressionAlertRecord] = []
        for method in record.methods:
            if not method.skipped_reason:
                continue
            state = self._fallback_alert_state.setdefault(method.name, _AlertState())
            observed_count = self._bump_alert_counter(
                state=state,
                now=now,
                window_seconds=alerts_config.window_seconds,
            )
            cooldown_elapsed = state.last_emitted_at <= 0.0 or (
                now - state.last_emitted_at
            ) >= float(alerts_config.cooldown_seconds)
            if observed_count >= alerts_config.fallback_threshold and cooldown_elapsed:
                warning = (
                    "Dynamic compression fallbacks are frequent; "
                    f"method={method.name}, count={observed_count}, "
                    f"window_seconds={alerts_config.window_seconds}."
                )
                alerts.append(
                    CompressionAlertRecord(
                        alert_type="fallback_rate",
                        method=method.name,
                        threshold=alerts_config.fallback_threshold,
                        observed_count=observed_count,
                        window_seconds=alerts_config.window_seconds,
                        category=record.identity.tool_category,
                        level=record.final_level,
                        warning=warning,
                    )
                )
                state.last_emitted_at = now
                state.window_started_at = now
                state.count = 0
        return alerts
