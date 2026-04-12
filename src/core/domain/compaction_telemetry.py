"""Telemetry domain models for history compaction.

Mirrors dynamic compression telemetry shape while keeping compaction
semantics honest — no fake method pipelines, no recovery handles unless
intentionally added later.
"""

from __future__ import annotations

from pydantic import Field

from src.core.interfaces.model_bases import DomainModel


class CompactionEventRecord(DomainModel):
    """Diagnostics for one compaction evaluation (per stale resource or no-op pass)."""

    correlation_id: str | None = None
    tool_call_id: str | None = None
    tool_name: str = ""
    tool_category: str = ""
    resource_identity_hash: str = ""
    resource_identity_preview: str | None = None
    resource_preview_redacted: bool = False
    original_bytes: int = Field(default=0, ge=0)
    compacted_bytes: int = Field(default=0, ge=0)
    saved_bytes: int = Field(default=0, ge=0)
    original_tokens_estimate: int = Field(default=0, ge=0)
    saved_tokens_estimate: int = Field(default=0, ge=0)
    applied: bool = False
    decision_reason: str = "no_stale_results"
    failed_open: bool = False
    failure_reason: str | None = None
    elapsed_total_ms: float = Field(default=0.0, ge=0)
    original_sha256: str | None = None
    compacted_sha256: str | None = None
    warnings: list[str] = Field(default_factory=list)
    message_index: int | None = None


class CompactionAggregateMetrics(DomainModel):
    """Running aggregate stats for operator diagnostics."""

    processed_evaluations: int = Field(default=0, ge=0)
    applied_evaluations: int = Field(default=0, ge=0)
    fail_open_count: int = Field(default=0, ge=0)
    total_original_bytes: int = Field(default=0, ge=0)
    total_compacted_bytes: int = Field(default=0, ge=0)
    total_saved_bytes: int = Field(default=0, ge=0)
    total_saved_tokens_estimate: int = Field(default=0, ge=0)
    by_category: dict[str, int] = Field(default_factory=dict)
    by_decision_reason: dict[str, int] = Field(default_factory=dict)


class CompactionAlertRecord(DomainModel):
    """Rate-limited alert emitted for frequent compaction issues."""

    alert_type: str
    threshold: int = Field(ge=1)
    observed_count: int = Field(ge=0)
    window_seconds: int = Field(ge=1)
    warning: str
    category: str | None = None


class EffectiveCompactionConfigDiagnostics(DomainModel):
    """Redaction-safe effective-configuration diagnostics for operators."""

    active_controls: list[str] = Field(default_factory=list)
    inactive_controls: list[str] = Field(default_factory=list)
    ignored_controls: list[str] = Field(default_factory=list)
    reasons: dict[str, str] = Field(default_factory=dict)
    fingerprint: str | None = None
    warnings: list[str] = Field(default_factory=list)
