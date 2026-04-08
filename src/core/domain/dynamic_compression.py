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


class ToolOutputCompressionRecord(DomainModel):
    """Compression diagnostics for one tool message."""

    tool_call_id: str | None = None
    identity: ToolIdentity
    original_bytes: int = Field(ge=0)
    compressed_bytes: int = Field(ge=0)
    methods: list[CompressionMethodRecord] = Field(default_factory=list)
    marker_inserted: bool = False
    failed_open: bool = False
    applied: bool = False
    final_level: CompressionLevel = CompressionLevel.CONSERVATIVE
    warnings: list[str] = Field(default_factory=list)


class ToolOutputCompressionBatchResult(DomainModel):
    """Batch result for request-bound compression pass."""

    messages: list[Any]
    records: list[ToolOutputCompressionRecord] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
