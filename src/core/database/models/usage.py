"""SQLModel models for usage tracking and statistics.

This module provides SQLModel table definitions for storing usage records
and session metrics in the database.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import Column as SAColumn
from sqlalchemy import Index, Text
from sqlmodel import Field, SQLModel

if TYPE_CHECKING:
    from src.core.domain.openrouter_usage import OpenRouterUsage
    from src.core.domain.usage_record import UsageRecord


class UsageRecordTable(SQLModel, table=True):
    """SQLModel table for usage records.

    Stores detailed usage metrics for each request/response cycle,
    including token counts, timing, and backend-reported usage.
    """

    __tablename__ = "usage_records"  # type: ignore[assignment]

    # Primary key
    id: str = Field(primary_key=True, max_length=64)

    # Timestamp and session info
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    session_id: str = Field(nullable=False, max_length=128, index=True)
    turn_number: int = Field(nullable=False, default=1)

    # Traffic identification
    backend_type: str = Field(nullable=False, max_length=64, index=True)
    backend_instance_id: str | None = Field(default=None, max_length=128, index=True)
    model: str = Field(nullable=False, max_length=256, index=True)
    frontend_type: str = Field(nullable=False, max_length=64)
    leg: str = Field(nullable=False, max_length=8)  # CTP, PTB, BTP, PTC

    # Proxy-calculated token metrics (verbatim - before mutations)
    verbatim_prompt_tokens: int = Field(nullable=False, default=0)
    verbatim_completion_tokens: int = Field(nullable=False, default=0)

    # Proxy-calculated token metrics (mutated - after mutations)
    mutated_prompt_tokens: int = Field(nullable=False, default=0)
    mutated_completion_tokens: int = Field(nullable=False, default=0)

    # Computed totals
    total_tokens: int = Field(nullable=False, default=0, index=True)

    # Backend-reported usage stored as JSON
    backend_reported_usage_json: str | None = Field(
        default=None, sa_column=SAColumn("backend_reported_usage_json", Text)
    )

    # Request/response metadata
    http_status_code: int | None = Field(default=None, index=True)
    tool_call_count: int = Field(nullable=False, default=0)
    native_tool_call_count: int = Field(nullable=False, default=0)
    vtc_tool_call_count: int = Field(nullable=False, default=0)
    tool_names_json: str | None = Field(
        default=None, sa_column=SAColumn("tool_names_json", Text)
    )

    # Timing metrics (in milliseconds)
    ttft_ms: float | None = Field(default=None)
    stream_tps: float | None = Field(default=None)
    backend_wait_ms: float | None = Field(default=None)
    proxy_processing_ms: float = Field(nullable=False, default=0.0)
    total_duration_ms: float = Field(nullable=False, default=0.0)

    # Context
    user_agent: str | None = Field(default=None, max_length=512)
    app_title: str | None = Field(default=None, max_length=256)
    proxy_user: str | None = Field(default=None, max_length=256, index=True)

    # Define composite indexes for common queries
    __table_args__ = (
        Index("idx_usage_records_timestamp", "timestamp"),
        Index("idx_usage_records_session_timestamp", "session_id", "timestamp"),
        Index("idx_usage_records_backend_model", "backend_type", "model"),
        Index(
            "idx_usage_records_backend_model_timestamp",
            "backend_type",
            "model",
            "timestamp",
        ),
        Index("idx_usage_records_status_timestamp", "http_status_code", "timestamp"),
        Index("idx_usage_records_proxy_user_timestamp", "proxy_user", "timestamp"),
        Index(
            "idx_usage_records_backend_instance",
            "backend_instance_id",
        ),
        Index(
            "idx_usage_records_backend_instance_model",
            "backend_instance_id",
            "model",
        ),
    )

    @classmethod
    def from_domain(cls, record: UsageRecord) -> UsageRecordTable:
        """Create a table instance from a domain UsageRecord.

        Args:
            record: Domain UsageRecord instance

        Returns:
            UsageRecordTable instance ready for database insertion
        """
        # Serialize backend_reported_usage to JSON
        backend_usage_json: str | None = None
        if record.backend_reported_usage is not None:
            backend_usage_json = json.dumps(
                record.backend_reported_usage.to_openrouter_dict()
            )

        # Serialize tool_names to JSON
        tool_names_json: str | None = None
        if record.tool_names:
            tool_names_json = json.dumps(record.tool_names)

        return cls(
            id=record.id,
            timestamp=record.timestamp,
            session_id=record.session_id,
            turn_number=record.turn_number,
            backend_type=record.backend_type,
            backend_instance_id=record.backend_instance_id,
            model=record.model,
            frontend_type=record.frontend_type,
            leg=record.leg.value,
            verbatim_prompt_tokens=record.verbatim_prompt_tokens,
            verbatim_completion_tokens=record.verbatim_completion_tokens,
            mutated_prompt_tokens=record.mutated_prompt_tokens,
            mutated_completion_tokens=record.mutated_completion_tokens,
            total_tokens=record.total_tokens,
            backend_reported_usage_json=backend_usage_json,
            http_status_code=record.http_status_code,
            tool_call_count=record.tool_call_count,
            native_tool_call_count=record.native_tool_call_count,
            vtc_tool_call_count=record.vtc_tool_call_count,
            tool_names_json=tool_names_json,
            ttft_ms=record.ttft_ms,
            stream_tps=record.stream_tps,
            backend_wait_ms=record.backend_wait_ms,
            proxy_processing_ms=record.proxy_processing_ms,
            total_duration_ms=record.total_duration_ms,
            user_agent=record.user_agent,
            app_title=record.app_title,
            proxy_user=record.proxy_user,
        )

    def to_domain(self) -> UsageRecord:
        """Convert to a domain UsageRecord.

        Returns:
            Domain UsageRecord instance
        """
        from src.core.domain.openrouter_usage import OpenRouterUsage
        from src.core.domain.traffic_leg import TrafficLeg
        from src.core.domain.usage_record import UsageRecord

        # Deserialize backend_reported_usage from JSON
        backend_usage: OpenRouterUsage | None = None
        if self.backend_reported_usage_json:
            usage_data = json.loads(self.backend_reported_usage_json)
            backend_usage = OpenRouterUsage.from_dict(usage_data)

        # Deserialize tool_names from JSON
        tool_names: list[str] = []
        if self.tool_names_json:
            tool_names = json.loads(self.tool_names_json)

        return UsageRecord(
            id=self.id,
            timestamp=self.timestamp,
            session_id=self.session_id,
            turn_number=self.turn_number,
            backend_type=self.backend_type,
            backend_instance_id=self.backend_instance_id,
            model=self.model,
            frontend_type=self.frontend_type,
            leg=TrafficLeg(self.leg),
            verbatim_prompt_tokens=self.verbatim_prompt_tokens,
            verbatim_completion_tokens=self.verbatim_completion_tokens,
            mutated_prompt_tokens=self.mutated_prompt_tokens,
            mutated_completion_tokens=self.mutated_completion_tokens,
            total_tokens=self.total_tokens,
            backend_reported_usage=backend_usage,
            http_status_code=self.http_status_code,
            tool_call_count=self.tool_call_count,
            native_tool_call_count=self.native_tool_call_count,
            vtc_tool_call_count=self.vtc_tool_call_count,
            tool_names=tool_names,
            ttft_ms=self.ttft_ms,
            stream_tps=self.stream_tps,
            backend_wait_ms=self.backend_wait_ms,
            proxy_processing_ms=self.proxy_processing_ms,
            total_duration_ms=self.total_duration_ms,
            user_agent=self.user_agent,
            app_title=self.app_title,
            proxy_user=self.proxy_user,
        )


class SessionMetricsTable(SQLModel, table=True):
    """SQLModel table for session metrics.

    Stores aggregated metrics per session for quick lookups.
    """

    __tablename__ = "session_metrics"  # type: ignore[assignment]

    # Primary key
    session_id: str = Field(primary_key=True, max_length=128)

    # Session timing
    start_time: datetime = Field(nullable=False)
    last_activity: datetime = Field(nullable=False, index=True)

    # Counters
    turn_count: int = Field(nullable=False, default=0)
    total_tokens: int = Field(nullable=False, default=0)
    total_tool_calls: int = Field(nullable=False, default=0)

    # Status
    is_completed: bool = Field(nullable=False, default=False, index=True)

    # Context (denormalized for quick filtering)
    backend_type: str | None = Field(default=None, max_length=64)
    model: str | None = Field(default=None, max_length=256)
    proxy_user: str | None = Field(default=None, max_length=256, index=True)

    # End-of-Session (EoS) metadata
    eos_emitted_at: datetime | None = Field(default=None, nullable=True)
    eos_signal_type: str | None = Field(default=None, max_length=64, nullable=True)
    eos_reason: str | None = Field(default=None, max_length=512, nullable=True)
    eos_error_classification: str | None = Field(
        default=None, max_length=64, nullable=True
    )
    eos_error_status_code: int | None = Field(default=None, nullable=True)

    __table_args__ = (
        Index("idx_session_metrics_last_activity", "last_activity"),
        Index("idx_session_metrics_user_activity", "proxy_user", "last_activity"),
        Index("idx_session_metrics_eos_emitted_at", "eos_emitted_at"),
    )
