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
    wire_schema: str | None = None  # Capture schema marker (e.g. "v2")
    transport: str | None = None  # "http" | "websocket"
    protocol_event: str | None = None  # "request" | "response" | "frame"
    http_method: str | None = None
    url: str | None = None
    http_status_code: int | None = None
    http_reason_phrase: str | None = None
    http_version: str | None = None
    websocket_message_type: str | None = None  # "text" | "binary"
    compression_correlation_id: str | None = None
    compression_records_count: int | None = None

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
        if self.wire_schema is not None:
            result["wire_schema"] = self.wire_schema
        if self.transport is not None:
            result["transport"] = self.transport
        if self.protocol_event is not None:
            result["event"] = self.protocol_event
        if self.http_method is not None:
            result["http_method"] = self.http_method
        if self.url is not None:
            result["url"] = self.url
        if self.http_status_code is not None:
            result["http_status"] = self.http_status_code
        if self.http_reason_phrase is not None:
            result["http_reason"] = self.http_reason_phrase
        if self.http_version is not None:
            result["http_version"] = self.http_version
        if self.websocket_message_type is not None:
            result["ws_message_type"] = self.websocket_message_type
        if self.compression_correlation_id is not None:
            result["ccid"] = self.compression_correlation_id
        if self.compression_records_count is not None:
            result["crc"] = self.compression_records_count
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
            wire_schema=data.get("wire_schema"),
            transport=data.get("transport"),
            protocol_event=data.get("event"),
            http_method=data.get("http_method"),
            url=data.get("url"),
            http_status_code=data.get("http_status"),
            http_reason_phrase=data.get("http_reason"),
            http_version=data.get("http_version"),
            websocket_message_type=data.get("ws_message_type"),
            compression_correlation_id=data.get("ccid"),
            compression_records_count=data.get("crc"),
        )


@dataclass(frozen=True, slots=True, init=False)
class CapturedWireEvent:
    """Low-level canonical CBOR V2 wire capture event."""

    timestamp: float
    direction: CaptureDirection
    sequence: int
    data: bytes
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
    chunk_index: int | None = None
    is_stream_start: bool = False
    is_stream_end: bool = False
    total_chunks: int | None = None
    total_bytes: int | None = None
    canonical_usage: dict[str, Any] | None = None
    status_code: int | None = None
    retry_after_seconds: float | None = None
    retry_attempt: int | None = None
    is_retry: bool = False
    account_id: str | None = None
    request_timestamp: float | None = None
    response_timestamp: float | None = None
    latency_ms: float | None = None
    ttfb_ms: float | None = None
    stream_duration_ms: float | None = None
    eos: bool = False
    eos_signal: str | None = None
    eos_reason: str | None = None
    eos_termination_category: str | None = None
    eos_error_classification: str | None = None
    eos_error_status_code: int | None = None
    wire_schema: str | None = None
    transport: str | None = None
    protocol_event: str | None = None
    http_method: str | None = None
    url: str | None = None
    http_status_code: int | None = None
    http_reason_phrase: str | None = None
    http_version: str | None = None
    websocket_message_type: str | None = None
    compression_correlation_id: str | None = None
    compression_records_count: int | None = None

    def __init__(
        self,
        timestamp: float,
        direction: CaptureDirection,
        sequence: int,
        data: bytes,
        metadata: CaptureMetadata | None = None,
        *,
        session_id: str | None = None,
        a_session_id: str | None = None,
        b_session_id: str | None = None,
        b_seq: int | None = None,
        backend: str | None = None,
        model: str | None = None,
        key_name: str | None = None,
        client_host: str | None = None,
        user_agent: str | None = None,
        request_id: str | None = None,
        chunk_index: int | None = None,
        is_stream_start: bool | None = None,
        is_stream_end: bool | None = None,
        total_chunks: int | None = None,
        total_bytes: int | None = None,
        canonical_usage: dict[str, Any] | None = None,
        status_code: int | None = None,
        retry_after_seconds: float | None = None,
        retry_attempt: int | None = None,
        is_retry: bool | None = None,
        account_id: str | None = None,
        request_timestamp: float | None = None,
        response_timestamp: float | None = None,
        latency_ms: float | None = None,
        ttfb_ms: float | None = None,
        stream_duration_ms: float | None = None,
        eos: bool | None = None,
        eos_signal: str | None = None,
        eos_reason: str | None = None,
        eos_termination_category: str | None = None,
        eos_error_classification: str | None = None,
        eos_error_status_code: int | None = None,
        wire_schema: str | None = None,
        transport: str | None = None,
        protocol_event: str | None = None,
        http_method: str | None = None,
        url: str | None = None,
        http_status_code: int | None = None,
        http_reason_phrase: str | None = None,
        http_version: str | None = None,
        websocket_message_type: str | None = None,
        compression_correlation_id: str | None = None,
        compression_records_count: int | None = None,
    ) -> None:
        if metadata is not None:
            if session_id is None:
                session_id = metadata.session_id
            if a_session_id is None:
                a_session_id = metadata.a_session_id
            if b_session_id is None:
                b_session_id = metadata.b_session_id
            if b_seq is None:
                b_seq = metadata.b_seq
            if backend is None:
                backend = metadata.backend
            if model is None:
                model = metadata.model
            if key_name is None:
                key_name = metadata.key_name
            if client_host is None:
                client_host = metadata.client_host
            if user_agent is None:
                user_agent = metadata.user_agent
            if request_id is None:
                request_id = metadata.request_id
            if chunk_index is None:
                chunk_index = metadata.chunk_index
            if is_stream_start is None:
                is_stream_start = metadata.is_stream_start
            if is_stream_end is None:
                is_stream_end = metadata.is_stream_end
            if total_chunks is None:
                total_chunks = metadata.total_chunks
            if total_bytes is None:
                total_bytes = metadata.total_bytes
            if canonical_usage is None:
                canonical_usage = metadata.canonical_usage
            if status_code is None:
                status_code = metadata.status_code
            if retry_after_seconds is None:
                retry_after_seconds = metadata.retry_after_seconds
            if retry_attempt is None:
                retry_attempt = metadata.retry_attempt
            if is_retry is None:
                is_retry = metadata.is_retry
            if account_id is None:
                account_id = metadata.account_id
            if request_timestamp is None:
                request_timestamp = metadata.request_timestamp
            if response_timestamp is None:
                response_timestamp = metadata.response_timestamp
            if latency_ms is None:
                latency_ms = metadata.latency_ms
            if ttfb_ms is None:
                ttfb_ms = metadata.ttfb_ms
            if stream_duration_ms is None:
                stream_duration_ms = metadata.stream_duration_ms
            if eos is None:
                eos = metadata.eos
            if eos_signal is None:
                eos_signal = metadata.eos_signal
            if eos_reason is None:
                eos_reason = metadata.eos_reason
            if eos_termination_category is None:
                eos_termination_category = metadata.eos_termination_category
            if eos_error_classification is None:
                eos_error_classification = metadata.eos_error_classification
            if eos_error_status_code is None:
                eos_error_status_code = metadata.eos_error_status_code
            if wire_schema is None:
                wire_schema = metadata.wire_schema
            if transport is None:
                transport = metadata.transport
            if protocol_event is None:
                protocol_event = metadata.protocol_event
            if http_method is None:
                http_method = metadata.http_method
            if url is None:
                url = metadata.url
            if http_status_code is None:
                http_status_code = metadata.http_status_code
            if http_reason_phrase is None:
                http_reason_phrase = metadata.http_reason_phrase
            if http_version is None:
                http_version = metadata.http_version
            if websocket_message_type is None:
                websocket_message_type = metadata.websocket_message_type
            if compression_correlation_id is None:
                compression_correlation_id = metadata.compression_correlation_id
            if compression_records_count is None:
                compression_records_count = metadata.compression_records_count

        object.__setattr__(self, "timestamp", timestamp)
        object.__setattr__(self, "direction", direction)
        object.__setattr__(self, "sequence", sequence)
        object.__setattr__(self, "data", data)
        object.__setattr__(self, "session_id", session_id)
        object.__setattr__(self, "a_session_id", a_session_id)
        object.__setattr__(self, "b_session_id", b_session_id)
        object.__setattr__(self, "b_seq", b_seq)
        object.__setattr__(self, "backend", backend)
        object.__setattr__(self, "model", model)
        object.__setattr__(self, "key_name", key_name)
        object.__setattr__(self, "client_host", client_host)
        object.__setattr__(self, "user_agent", user_agent)
        object.__setattr__(self, "request_id", request_id)
        object.__setattr__(self, "chunk_index", chunk_index)
        object.__setattr__(self, "is_stream_start", bool(is_stream_start))
        object.__setattr__(self, "is_stream_end", bool(is_stream_end))
        object.__setattr__(self, "total_chunks", total_chunks)
        object.__setattr__(self, "total_bytes", total_bytes)
        object.__setattr__(self, "canonical_usage", canonical_usage)
        object.__setattr__(self, "status_code", status_code)
        object.__setattr__(self, "retry_after_seconds", retry_after_seconds)
        object.__setattr__(self, "retry_attempt", retry_attempt)
        object.__setattr__(self, "is_retry", bool(is_retry))
        object.__setattr__(self, "account_id", account_id)
        object.__setattr__(self, "request_timestamp", request_timestamp)
        object.__setattr__(self, "response_timestamp", response_timestamp)
        object.__setattr__(self, "latency_ms", latency_ms)
        object.__setattr__(self, "ttfb_ms", ttfb_ms)
        object.__setattr__(self, "stream_duration_ms", stream_duration_ms)
        object.__setattr__(self, "eos", bool(eos))
        object.__setattr__(self, "eos_signal", eos_signal)
        object.__setattr__(self, "eos_reason", eos_reason)
        object.__setattr__(self, "eos_termination_category", eos_termination_category)
        object.__setattr__(self, "eos_error_classification", eos_error_classification)
        object.__setattr__(self, "eos_error_status_code", eos_error_status_code)
        object.__setattr__(self, "wire_schema", wire_schema)
        object.__setattr__(self, "transport", transport)
        object.__setattr__(self, "protocol_event", protocol_event)
        object.__setattr__(self, "http_method", http_method)
        object.__setattr__(self, "url", url)
        object.__setattr__(self, "http_status_code", http_status_code)
        object.__setattr__(self, "http_reason_phrase", http_reason_phrase)
        object.__setattr__(self, "http_version", http_version)
        object.__setattr__(self, "websocket_message_type", websocket_message_type)
        object.__setattr__(
            self,
            "compression_correlation_id",
            compression_correlation_id,
        )
        object.__setattr__(
            self,
            "compression_records_count",
            compression_records_count,
        )

    @classmethod
    def from_metadata(
        cls,
        *,
        timestamp: float,
        direction: CaptureDirection,
        sequence: int,
        data: bytes,
        metadata: CaptureMetadata,
    ) -> CapturedWireEvent:
        """Create an event from a legacy metadata object."""
        return cls(
            timestamp=timestamp,
            direction=direction,
            sequence=sequence,
            data=data,
            metadata=metadata,
        )

    @property
    def metadata(self) -> CaptureMetadata:
        """Return the legacy metadata view for compatibility."""
        return CaptureMetadata(
            session_id=self.session_id,
            a_session_id=self.a_session_id,
            b_session_id=self.b_session_id,
            b_seq=self.b_seq,
            backend=self.backend,
            model=self.model,
            key_name=self.key_name,
            client_host=self.client_host,
            user_agent=self.user_agent,
            request_id=self.request_id,
            chunk_index=self.chunk_index,
            is_stream_start=self.is_stream_start,
            is_stream_end=self.is_stream_end,
            total_chunks=self.total_chunks,
            total_bytes=self.total_bytes,
            canonical_usage=self.canonical_usage,
            status_code=self.status_code,
            retry_after_seconds=self.retry_after_seconds,
            retry_attempt=self.retry_attempt,
            is_retry=self.is_retry,
            account_id=self.account_id,
            request_timestamp=self.request_timestamp,
            response_timestamp=self.response_timestamp,
            latency_ms=self.latency_ms,
            ttfb_ms=self.ttfb_ms,
            stream_duration_ms=self.stream_duration_ms,
            eos=self.eos,
            eos_signal=self.eos_signal,
            eos_reason=self.eos_reason,
            eos_termination_category=self.eos_termination_category,
            eos_error_classification=self.eos_error_classification,
            eos_error_status_code=self.eos_error_status_code,
            wire_schema=self.wire_schema,
            transport=self.transport,
            protocol_event=self.protocol_event,
            http_method=self.http_method,
            url=self.url,
            http_status_code=self.http_status_code,
            http_reason_phrase=self.http_reason_phrase,
            http_version=self.http_version,
            websocket_message_type=self.websocket_message_type,
            compression_correlation_id=self.compression_correlation_id,
            compression_records_count=self.compression_records_count,
        )

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
    def from_dict(cls, data: dict[str, Any]) -> CapturedWireEvent:
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


class CaptureEntry(CapturedWireEvent):
    """Compatibility subclass for legacy ``CaptureEntry`` imports."""

    __slots__ = ()


@dataclass(frozen=True, slots=True)
class CaptureFileHeader:
    """Header for a CBOR capture file.

    Contains metadata about the capture session.
    """

    MAGIC = "LLMPROXY-CAPTURE-V2"
    VERSION = 2

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


@dataclass(frozen=True, slots=True)
class CaptureSession:
    """A single capture entry with timestamp, direction, and raw bytes.

    Attributes:
        header: File header
        entries: Capture events
    """

    header: CaptureFileHeader
    entries: list[CapturedWireEvent] = field(default_factory=list)

    def get_client_entries(self) -> list[CapturedWireEvent]:
        """Get entries for client-side traffic (directions 0 and 1)."""
        return [
            e
            for e in self.entries
            if e.direction
            in (CaptureDirection.CLIENT_TO_PROXY, CaptureDirection.PROXY_TO_CLIENT)
        ]

    def get_backend_entries(self) -> list[CapturedWireEvent]:
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

    def get_inbound_request_entries(self) -> list[CapturedWireEvent]:
        """Get inbound request entries from client."""
        return [
            e for e in self.entries if e.direction == CaptureDirection.CLIENT_TO_PROXY
        ]

    def get_outbound_response_entries(self) -> list[CapturedWireEvent]:
        """Get outbound response entries to client."""
        return [
            e for e in self.entries if e.direction == CaptureDirection.PROXY_TO_CLIENT
        ]

    def get_outbound_request_entries(self) -> list[CapturedWireEvent]:
        """Get outbound request entries to backend."""
        return [
            e for e in self.entries if e.direction == CaptureDirection.PROXY_TO_BACKEND
        ]

    def get_inbound_response_entries(self) -> list[CapturedWireEvent]:
        """Get inbound response entries from backend."""
        return [
            e for e in self.entries if e.direction == CaptureDirection.BACKEND_TO_PROXY
        ]
