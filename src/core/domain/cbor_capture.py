"""
Domain models for CBOR-based byte-precise wire capture.

This module defines the data structures for capture entries using CBOR format
for byte-level precision and nanosecond timestamps.
"""

from __future__ import annotations

import time
import zlib
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any


class CaptureDirection(IntEnum):
    """Direction of captured traffic.

    Enum values are used directly in CBOR encoding for compactness.
    """

    CLIENT_TO_PROXY = 0  # Inbound request from client
    PROXY_TO_CLIENT = 1  # Outbound response/stream chunk to client
    PROXY_TO_BACKEND = 2  # Outbound request to backend
    BACKEND_TO_PROXY = 3  # Inbound response/stream chunk from backend


@dataclass(frozen=True, slots=True)
class CaptureMetadata:
    """Optional metadata for a capture entry."""

    session_id: str | None = None
    a_session_id: str | None = None
    b_session_id: str | None = None
    b_seq: int | None = None
    backend: str | None = None
    model: str | None = None
    key_name: str | None = None
    client_host: str | None = None
    user_agent: str | None = None
    request_id: str | None = None
    chunk_index: int | None = None  # For streaming chunks
    is_stream_start: bool = False
    is_stream_end: bool = False
    total_chunks: int | None = None  # Set on stream_end
    total_bytes: int | None = None  # Set on stream_end
    canonical_usage: dict[str, Any] | None = None  # Canonical usage record
    status_code: int | None = None  # HTTP status code from backend or proxy
    retry_after_seconds: float | None = None  # Retry-After hint in seconds
    retry_attempt: int | None = None  # Retry attempt index (0-based)
    is_retry: bool = False  # True if this entry is from a retry attempt
    account_id: str | None = None  # Backend account identifier (redacted)
    request_timestamp: float | None = None  # Request start timestamp (epoch seconds)
    response_timestamp: float | None = None  # Response timestamp (epoch seconds)
    latency_ms: float | None = None  # End-to-end latency in milliseconds
    ttfb_ms: float | None = None  # Time-to-first-byte in milliseconds
    stream_duration_ms: float | None = None  # Streaming duration in milliseconds
    # End-of-Session (EoS) metadata
    eos: bool = False  # True if this entry represents an EoS event
    eos_signal: str | None = None  # EoS signal type (e.g., "done_sentinel")
    eos_reason: str | None = None  # EoS reason/description
    eos_termination_category: str | None = None  # "normal" or "error"
    eos_error_classification: str | None = (
        None  # Error classification if error termination
    )
    eos_error_status_code: int | None = None  # HTTP status code if error termination

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary, excluding None values for compact CBOR."""
        result: dict[str, Any] = {}
        if self.session_id is not None:
            result["sid"] = self.session_id
        if self.a_session_id is not None:
            result["asid"] = self.a_session_id
        if self.b_session_id is not None:
            result["bsid"] = self.b_session_id
        if self.b_seq is not None:
            result["bseq"] = self.b_seq
        if self.backend is not None:
            result["be"] = self.backend
        if self.model is not None:
            result["mod"] = self.model
        if self.key_name is not None:
            result["key"] = self.key_name
        if self.client_host is not None:
            result["host"] = self.client_host
        if self.user_agent is not None:
            result["ua"] = self.user_agent
        if self.request_id is not None:
            result["rid"] = self.request_id
        if self.chunk_index is not None:
            result["ci"] = self.chunk_index
        if self.is_stream_start:
            result["ss"] = True
        if self.is_stream_end:
            result["se"] = True
        if self.total_chunks is not None:
            result["tc"] = self.total_chunks
        if self.total_bytes is not None:
            result["tb"] = self.total_bytes
        if self.canonical_usage is not None:
            result["cu"] = self.canonical_usage
        if self.status_code is not None:
            result["sc"] = self.status_code
        if self.retry_after_seconds is not None:
            result["ra"] = self.retry_after_seconds
        if self.retry_attempt is not None:
            result["rat"] = self.retry_attempt
        if self.is_retry:
            result["rtry"] = True
        if self.account_id is not None:
            result["acct"] = self.account_id
        if self.request_timestamp is not None:
            result["rts"] = self.request_timestamp
        if self.response_timestamp is not None:
            result["pts"] = self.response_timestamp
        if self.latency_ms is not None:
            result["lat"] = self.latency_ms
        if self.ttfb_ms is not None:
            result["ttfb"] = self.ttfb_ms
        if self.stream_duration_ms is not None:
            result["sdur"] = self.stream_duration_ms
        if self.eos:
            result["eos"] = True
        if self.eos_signal is not None:
            result["eos_sig"] = self.eos_signal
        if self.eos_reason is not None:
            result["eos_reason"] = self.eos_reason
        if self.eos_termination_category is not None:
            result["eos_term"] = self.eos_termination_category
        if self.eos_error_classification is not None:
            result["eos_err_cls"] = self.eos_error_classification
        if self.eos_error_status_code is not None:
            result["eos_err_code"] = self.eos_error_status_code
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CaptureMetadata:
        """Create from CBOR dictionary."""
        return cls(
            session_id=data.get("sid"),
            a_session_id=data.get("asid"),
            b_session_id=data.get("bsid"),
            b_seq=data.get("bseq"),
            backend=data.get("be"),
            model=data.get("mod"),
            key_name=data.get("key"),
            client_host=data.get("host"),
            user_agent=data.get("ua"),
            request_id=data.get("rid"),
            chunk_index=data.get("ci"),
            is_stream_start=data.get("ss", False),
            is_stream_end=data.get("se", False),
            total_chunks=data.get("tc"),
            total_bytes=data.get("tb"),
            canonical_usage=data.get("cu"),
            status_code=data.get("sc"),
            retry_after_seconds=data.get("ra"),
            retry_attempt=data.get("rat"),
            is_retry=data.get("rtry", False),
            account_id=data.get("acct"),
            request_timestamp=data.get("rts"),
            response_timestamp=data.get("pts"),
            latency_ms=data.get("lat"),
            ttfb_ms=data.get("ttfb"),
            stream_duration_ms=data.get("sdur"),
            eos=data.get("eos", False),
            eos_signal=data.get("eos_sig"),
            eos_reason=data.get("eos_reason"),
            eos_termination_category=data.get("eos_term"),
            eos_error_classification=data.get("eos_err_cls"),
            eos_error_status_code=data.get("eos_err_code"),
        )


@dataclass(frozen=True, slots=True)
class CaptureEntry:
    """A single capture entry with timestamp, direction, and raw bytes.

    Attributes:
        timestamp: Unix timestamp with nanosecond precision (float)
        direction: Traffic direction (CaptureDirection enum)
        sequence: Sequence number within the session
        data: Raw bytes captured
        metadata: Optional metadata about the capture
    """

    timestamp: float
    direction: CaptureDirection
    sequence: int
    data: bytes
    metadata: CaptureMetadata = field(default_factory=CaptureMetadata)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for CBOR encoding."""
        result: dict[str, Any] = {
            "ts": self.timestamp,
            "dir": int(self.direction),
            "seq": self.sequence,
        }

        # Attempt compression for larger payloads
        if len(self.data) > 128:
            compressed = zlib.compress(self.data)
            if len(compressed) < len(self.data):
                result["data"] = compressed
                result["enc"] = "zlib"
            else:
                result["data"] = self.data
        else:
            result["data"] = self.data

        meta_dict = self.metadata.to_dict()
        if meta_dict:
            result["meta"] = meta_dict
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CaptureEntry:
        """Create from CBOR dictionary."""
        meta_dict = data.get("meta", {})
        raw_data = data["data"]

        # Handle compression
        if data.get("enc") == "zlib":
            raw_data = zlib.decompress(raw_data)

        return cls(
            timestamp=data["ts"],
            direction=CaptureDirection(data["dir"]),
            sequence=data["seq"],
            data=raw_data,
            metadata=(
                CaptureMetadata.from_dict(meta_dict) if meta_dict else CaptureMetadata()
            ),
        )


@dataclass
class CaptureFileHeader:
    """Header for a CBOR capture file.

    Contains metadata about the capture session.
    """

    MAGIC = "LLMPROXY-CAPTURE-V1"
    VERSION = 1

    magic: str = MAGIC
    version: int = VERSION
    created_at: float = field(default_factory=time.time)
    session_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for CBOR encoding."""
        return {
            "magic": self.magic,
            "version": self.version,
            "created_at": self.created_at,
            "session_id": self.session_id,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CaptureFileHeader:
        """Create from CBOR dictionary."""
        header = cls(
            magic=data.get("magic", cls.MAGIC),
            version=data.get("version", cls.VERSION),
            created_at=data.get("created_at", time.time()),
            session_id=data.get("session_id", ""),
            metadata=data.get("metadata", {}),
        )
        return header

    def validate(self) -> bool:
        """Validate header magic and version."""
        return self.magic == self.MAGIC and self.version == self.VERSION


@dataclass
class CaptureSession:
    """Complete capture session with header and entries.

    Used for loading and processing capture files.
    """

    header: CaptureFileHeader
    entries: list[CaptureEntry] = field(default_factory=list)

    def get_client_entries(self) -> list[CaptureEntry]:
        """Get entries for client-side traffic (directions 0 and 1)."""
        return [
            e
            for e in self.entries
            if e.direction
            in (CaptureDirection.CLIENT_TO_PROXY, CaptureDirection.PROXY_TO_CLIENT)
        ]

    def get_backend_entries(self) -> list[CaptureEntry]:
        """Get entries for backend-side traffic (directions 2 and 3)."""
        return [
            e
            for e in self.entries
            if e.direction
            in (CaptureDirection.PROXY_TO_BACKEND, CaptureDirection.BACKEND_TO_PROXY)
        ]

    def get_timing_deltas(self) -> list[float]:
        """Get time deltas between consecutive entries."""
        if len(self.entries) < 2:
            return []
        deltas = []
        for i in range(1, len(self.entries)):
            deltas.append(self.entries[i].timestamp - self.entries[i - 1].timestamp)
        return deltas

    def get_inbound_request_entries(self) -> list[CaptureEntry]:
        """Get inbound request entries from client."""
        return [
            e for e in self.entries if e.direction == CaptureDirection.CLIENT_TO_PROXY
        ]

    def get_outbound_response_entries(self) -> list[CaptureEntry]:
        """Get outbound response entries to client."""
        return [
            e for e in self.entries if e.direction == CaptureDirection.PROXY_TO_CLIENT
        ]

    def get_outbound_request_entries(self) -> list[CaptureEntry]:
        """Get outbound request entries to backend."""
        return [
            e for e in self.entries if e.direction == CaptureDirection.PROXY_TO_BACKEND
        ]

    def get_inbound_response_entries(self) -> list[CaptureEntry]:
        """Get inbound response entries from backend."""
        return [
            e for e in self.entries if e.direction == CaptureDirection.BACKEND_TO_PROXY
        ]
