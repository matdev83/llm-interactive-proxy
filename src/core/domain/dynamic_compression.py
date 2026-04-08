"""Domain models for dynamic tool-output compression."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import Field

from src.core.domain.configuration.dynamic_compression_config import CompressionLevel
from src.core.interfaces.model_bases import DomainModel


class ToolOutputContentType(str, Enum):
    """Detected content kind for a tool payload."""

    TEXT = "text"
    JSON = "json"
    NDJSON = "ndjson"
    XML = "xml"


class ToolIdentity(DomainModel):
    """Deterministic identity metadata extracted from a tool output."""

    tool_name: str
    tool_category: str
    command_signature: str | None = None
    command_prefix: str | None = None
    explicit_format_flags: list[str] = Field(default_factory=list)


class ToolOutputContext(DomainModel):
    """Observable context used for deterministic rule matching."""

    identity: ToolIdentity
    content: str
    content_type: ToolOutputContentType = ToolOutputContentType.TEXT
    byte_size: int = Field(ge=0)
    line_count: int = Field(ge=0)
    has_line_numbers: bool = False
    has_ansi: bool = False
    has_diff_markers: bool = False
    has_explicit_format: bool = False
    structured_format: str | None = None
    is_machine_parseable: bool = False

    @classmethod
    def for_text(
        cls,
        *,
        tool_name: str,
        tool_category: str,
        content: str,
        command_signature: str | None = None,
        command_prefix: str | None = None,
    ) -> ToolOutputContext:
        return cls(
            identity=ToolIdentity(
                tool_name=tool_name,
                tool_category=tool_category,
                command_signature=command_signature,
                command_prefix=command_prefix,
            ),
            content=content,
            byte_size=len(content.encode("utf-8")),
            line_count=max(1, content.count("\n") + 1) if content else 0,
        )


class CompressionMethodRecord(DomainModel):
    """Per-method execution outcome for observability and debugging."""

    name: str
    applied: bool
    elapsed_ms: float = Field(ge=0)
    original_bytes: int = Field(ge=0)
    result_bytes: int = Field(ge=0)
    error: str | None = None
    skipped_reason: str | None = None


class CompressionMethodAggregate(DomainModel):
    """Aggregate counters for one compression method."""

    attempts: int = Field(default=0, ge=0)
    applied: int = Field(default=0, ge=0)
    failures: int = Field(default=0, ge=0)
    fallbacks: int = Field(default=0, ge=0)
    bytes_saved: int = Field(default=0, ge=0)
    elapsed_ms_total: float = Field(default=0.0, ge=0)


class CompressionAggregateMetrics(DomainModel):
    """Aggregate metrics surface for operator diagnostics."""

    processed_outputs: int = Field(default=0, ge=0)
    compressed_outputs: int = Field(default=0, ge=0)
    fail_open_count: int = Field(default=0, ge=0)
    fallback_count: int = Field(default=0, ge=0)
    total_original_bytes: int = Field(default=0, ge=0)
    total_compressed_bytes: int = Field(default=0, ge=0)
    total_saved_bytes: int = Field(default=0, ge=0)
    total_saved_tokens_estimate: int = Field(default=0, ge=0)
    by_method: dict[str, CompressionMethodAggregate] = Field(default_factory=dict)
    by_category: dict[str, int] = Field(default_factory=dict)
    by_level: dict[str, int] = Field(default_factory=dict)


class CompressionAlertRecord(DomainModel):
    """Rate-safe operator alert emitted for frequent failures/fallbacks."""

    alert_type: str
    method: str
    threshold: int = Field(ge=1)
    observed_count: int = Field(ge=0)
    window_seconds: int = Field(ge=1)
    category: str | None = None
    level: CompressionLevel | None = None
    warning: str


class EffectiveCompressionConfigDiagnostics(DomainModel):
    """Redaction-safe effective-configuration diagnostics for operators."""

    active_controls: list[str] = Field(default_factory=list)
    inactive_controls: list[str] = Field(default_factory=list)
    ignored_controls: list[str] = Field(default_factory=list)
    reasons: dict[str, str] = Field(default_factory=dict)
    fingerprint: str | None = None
    warnings: list[str] = Field(default_factory=list)


class ToolOutputCompressionRecord(DomainModel):
    """Compression diagnostics for one tool message."""

    tool_call_id: str | None = None
    identity: ToolIdentity
    original_bytes: int = Field(ge=0)
    compressed_bytes: int = Field(ge=0)
    saved_bytes: int = Field(default=0, ge=0)
    methods: list[CompressionMethodRecord] = Field(default_factory=list)
    methods_applied: list[str] = Field(default_factory=list)
    elapsed_total_ms: float = Field(default=0.0, ge=0)
    marker_inserted: bool = False
    failed_open: bool = False
    fallback_applied: bool = False
    failure_reason: str | None = None
    applied: bool = False
    final_level: CompressionLevel = CompressionLevel.CONSERVATIVE
    warnings: list[str] = Field(default_factory=list)
    explicit_format_note: str | None = None
    original_sha256: str | None = None
    compressed_sha256: str | None = None
    correlation_id: str | None = None
    recovery_handle: str | None = None
    recovery_persisted: bool = False
    recovery_hint_inserted: bool = False


class ToolOutputCompressionBatchResult(DomainModel):
    """Batch result for request-bound compression pass."""

    messages: list[Any]
    records: list[ToolOutputCompressionRecord] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    aggregate_metrics: CompressionAggregateMetrics = Field(
        default_factory=CompressionAggregateMetrics
    )
    alerts: list[CompressionAlertRecord] = Field(default_factory=list)
    effective_config: EffectiveCompressionConfigDiagnostics | None = None
