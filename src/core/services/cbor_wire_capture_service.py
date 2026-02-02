"""
Byte-precise wire capture service using CBOR format.

This module provides a wire capture service that:
- Uses CBOR binary format for byte-level precision
- Stores nanosecond-precision timestamps using CBOR tag 1
- Captures raw bytes without JSON serialization overhead
- Supports session-based capture files
- Provides async buffered I/O for performance
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import cbor2
from pydantic.types import JsonValue

from src.core.common.contract_serialization import serialize_for_capture
from src.core.config.app_config import AppConfig
from src.core.domain.cbor_capture import (
    CaptureDirection,
    CaptureEntry,
    CaptureFileHeader,
    CaptureMetadata,
)
from src.core.domain.request_context import RequestContext
from src.core.domain.usage_canonical_record import CanonicalUsageRecord
from src.core.interfaces.wire_capture_interface import IWireCapture

logger = logging.getLogger(__name__)


class _RequestTimingState:
    """Tracks request/response timing for a single request."""

    __slots__ = ("request_ts", "first_byte_ts", "stream_start_ts")

    def __init__(self, request_ts: float) -> None:
        self.request_ts = request_ts
        self.first_byte_ts: float | None = None
        self.stream_start_ts: float | None = None


def _get_timestamp() -> float:
    """Get current timestamp with nanosecond precision."""
    return time.time_ns() / 1_000_000_000


def _is_mock(value: Any) -> bool:
    """Return True when value appears to be a unittest.mock object."""
    module_name = getattr(type(value), "__module__", "")
    return isinstance(module_name, str) and module_name.startswith("unittest.mock")


def _extract_bytes(payload: Any) -> bytes:  # pyright: ignore[reportUnusedFunction]
    """Extract raw bytes from various payload types using deterministic serialization.

    DEPRECATED: Use serialize_for_capture() directly for new code.
    This function is kept for backward compatibility and now delegates to serialize_for_capture().
    """
    return serialize_for_capture(payload)


class _StreamPassthroughWrapper:
    """Wrapper to preserve original stream semantics when capture disabled."""

    def __init__(self, stream: AsyncIterator[bytes]):
        self._stream = stream

    def __aiter__(self) -> _StreamPassthroughWrapper:
        return self

    async def __anext__(self) -> bytes:
        return await self._stream.__anext__()

    def __eq__(self, other: object) -> bool:
        if other is self._stream:
            return True
        stream_code = getattr(self._stream, "ag_code", None)
        other_code = getattr(other, "ag_code", None)
        return stream_code is not None and stream_code is other_code

    def __getattr__(self, item: str) -> Any:
        return getattr(self._stream, item)


class CborWireCaptureService(IWireCapture):
    """Byte-precise wire capture service using CBOR format.

    Features:
    - CBOR binary format for byte-level precision
    - Nanosecond timestamps using CBOR tag 1
    - Session-based capture files
    - Buffered async I/O
    - Captures raw bytes before/after processing
    """

    def __init__(
        self,
        config: AppConfig,
        capture_dir: str | Path | None = None,
        session_id: str | None = None,
    ) -> None:
        """Initialize CBOR wire capture service.

        Args:
            config: Application configuration
            capture_dir: Directory for capture files (enables capture if set)
            session_id: Optional fixed session ID (auto-generated if not provided)
        """
        self._config = config
        self._capture_dir: Path | None = Path(capture_dir) if capture_dir else None
        self._session_id = session_id or self._generate_session_id_from_log_file(config)
        self._enabled = False

        # Buffer for entries to write
        self._buffer: list[CaptureEntry] = []
        self._buffer_lock = asyncio.Lock()
        self._sequence_counter = 0
        self._sequence_lock = asyncio.Lock()
        self._timing_lock = asyncio.Lock()
        self._request_timings: dict[str, _RequestTimingState] = {}

        # File handle for current session
        self._file_path: Path | None = None
        self._header_written = False

        # Background flush task
        self._flush_task: asyncio.Task[None] | None = None
        self._flush_start_lock = threading.Lock()
        logging_cfg = getattr(config, "logging", None)
        raw_flush_interval = (
            getattr(logging_cfg, "cbor_capture_flush_interval", None)
            if logging_cfg
            else None
        )
        self._flush_interval = 1.0
        if raw_flush_interval is not None:
            try:
                candidate = float(raw_flush_interval)
            except (TypeError, ValueError):
                candidate = 1.0
            if candidate > 0:
                self._flush_interval = candidate

        # Buffer configuration
        self._max_buffer_entries = 50

        # Initialize if capture_dir is configured
        if self._capture_dir:
            self._initialize()

    def _generate_session_id_from_log_file(self, config: AppConfig) -> str:
        """Generate session ID based on log file name for unified naming.

        This creates a meaningful session ID that matches the log file name,
        making it easy to correlate CBOR captures with log files.

        Args:
            config: Application configuration

        Returns:
            Session ID derived from log file name, or UUID if no log file configured
        """
        try:
            log_file = getattr(getattr(config, "logging", None), "log_file", None)
            if log_file:
                log_path = Path(log_file)
                base_name = log_path.stem
                return base_name
        except (AttributeError, TypeError, ValueError) as e:
            logger.debug(
                "Failed to derive session ID from log file config: %s",
                e,
                exc_info=True,
            )

        # Fallback to UUID if log file not configured or error occurs
        return uuid4().hex

    def _initialize(self) -> None:
        """Initialize the capture system."""
        if not self._capture_dir:
            return

        try:
            # Create capture directory
            self._capture_dir.mkdir(parents=True, exist_ok=True)

            # Set up file path for this session
            self._file_path = self._capture_dir / f"{self._session_id}.cbor"

            # Write header
            self._write_header()
            self._enabled = True

            # Start background flush task if event loop is running
            self._maybe_start_flush_task()

            if logger.isEnabledFor(logging.INFO):
                logger.info("CBOR wire capture initialized: %s", self._file_path)

        except OSError:
            # OSError covers file I/O errors (PermissionError, FileNotFoundError, etc.)
            logger.error("Failed to initialize CBOR wire capture", exc_info=True)
            self._enabled = False
        except RuntimeError:
            # RuntimeError may occur from _maybe_start_flush_task() if event loop issues
            logger.error(
                "Failed to initialize CBOR wire capture (runtime error)", exc_info=True
            )
            self._enabled = False

    def _write_header(self) -> None:
        """Write capture file header."""
        if not self._file_path:
            return

        header = CaptureFileHeader(
            session_id=self._session_id,
            metadata={
                "config_file": getattr(
                    getattr(self._config, "config_file", None), "name", None
                ),
            },
        )

        try:
            with open(self._file_path, "wb") as f:
                cbor2.dump(header.to_dict(), f)
            self._header_written = True
        except OSError:
            # OSError covers file I/O errors (PermissionError, FileNotFoundError, etc.)
            logger.error("Failed to write capture header", exc_info=True)

    def enabled(self) -> bool:
        """Return True if capture is enabled."""
        return self._enabled

    async def _get_next_sequence(self) -> int:
        """Get next sequence number, thread-safe."""
        async with self._sequence_lock:
            seq = self._sequence_counter
            self._sequence_counter += 1
            return seq

    def _maybe_start_flush_task(self) -> None:
        """Start background flush task if not running."""
        if not self._enabled:
            return
        with self._flush_start_lock:
            if not self._enabled or self._flush_task is not None:
                return
            try:
                loop = asyncio.get_running_loop()
                self._flush_task = loop.create_task(self._background_flush_loop())
            except RuntimeError:
                # Expected when called from non-async context - log for debugging
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Cannot start background flush task: no running event loop",
                        exc_info=True,
                    )

    def _extract_context_metadata(
        self,
        context: RequestContext | None,
        session_id: str | None,
        backend: str | None = None,
        model: str | None = None,
        key_name: str | None = None,
        canonical_usage: dict[str, Any] | None = None,
        eos_metadata: dict[str, JsonValue] | None = None,
        capture_metadata: dict[str, JsonValue] | None = None,
    ) -> CaptureMetadata:
        """Extract metadata from context and parameters.

        Note: canonical_usage is expected to be a dict (converted from CanonicalUsageRecord
        at call site). eos_metadata is expected to be dict[str, JsonValue] (JSON-safe).
        """
        client_host: str | None = None
        user_agent: str | None = None
        request_id: str | None = None

        if context:
            ch = getattr(context, "client_host", None)
            if ch and not _is_mock(ch):
                client_host = str(ch)
            ua = getattr(context, "agent", None)
            if ua and not _is_mock(ua):
                user_agent = str(ua)
            rid = getattr(context, "request_id", None)
            if rid and not _is_mock(rid):
                request_id = str(rid)

        resolved_session = session_id
        if not resolved_session or not str(resolved_session).strip():
            resolved_session = request_id or self._session_id

        # Extract capture metadata if provided (already JSON-safe)
        capture_fields: dict[str, JsonValue] = {}
        if capture_metadata:
            capture_fields = {
                "status_code": capture_metadata.get("status_code"),
                "retry_after_seconds": capture_metadata.get("retry_after_seconds"),
                "retry_attempt": capture_metadata.get("retry_attempt"),
                "is_retry": capture_metadata.get("is_retry"),
                "account_id": capture_metadata.get("account_id"),
                "request_timestamp": capture_metadata.get("request_timestamp"),
                "response_timestamp": capture_metadata.get("response_timestamp"),
                "latency_ms": capture_metadata.get("latency_ms"),
                "ttfb_ms": capture_metadata.get("ttfb_ms"),
                "stream_duration_ms": capture_metadata.get("stream_duration_ms"),
            }

        # Extract EoS metadata if provided (already JSON-safe)
        eos_fields: dict[str, JsonValue] = {}
        if eos_metadata:
            eos_fields = {
                "eos": eos_metadata.get("eos", False),
                "eos_signal": eos_metadata.get("eos_signal"),
                "eos_reason": eos_metadata.get("eos_reason"),
                "eos_termination_category": eos_metadata.get(
                    "eos_termination_category"
                ),
                "eos_error_classification": eos_metadata.get(
                    "eos_error_classification"
                ),
                "eos_error_status_code": eos_metadata.get("eos_error_status_code"),
            }

        # Extract EoS fields with proper type conversion
        eos: bool = False
        eos_signal: str | None = None
        eos_reason: str | None = None
        eos_termination_category: str | None = None
        eos_error_classification: str | None = None
        eos_error_status_code: int | None = None

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

        if eos_fields:
            eos_val = eos_fields.get("eos", False)
            eos = bool(eos_val) if eos_val is not None else False

            eos_signal_val = eos_fields.get("eos_signal")
            eos_signal = (
                str(eos_signal_val)
                if eos_signal_val is not None and isinstance(eos_signal_val, str)
                else None
            )

            eos_reason_val = eos_fields.get("eos_reason")
            eos_reason = (
                str(eos_reason_val)
                if eos_reason_val is not None and isinstance(eos_reason_val, str)
                else None
            )

            eos_termination_category_val = eos_fields.get("eos_termination_category")
            eos_termination_category = (
                str(eos_termination_category_val)
                if eos_termination_category_val is not None
                and isinstance(eos_termination_category_val, str)
                else None
            )

            eos_error_classification_val = eos_fields.get("eos_error_classification")
            eos_error_classification = (
                str(eos_error_classification_val)
                if eos_error_classification_val is not None
                and isinstance(eos_error_classification_val, str)
                else None
            )

            eos_error_status_code_val = eos_fields.get("eos_error_status_code")
            if eos_error_status_code_val is not None:
                if isinstance(eos_error_status_code_val, int):
                    eos_error_status_code = eos_error_status_code_val
                elif (
                    isinstance(eos_error_status_code_val, float)
                    and eos_error_status_code_val.is_integer()
                ):
                    eos_error_status_code = int(eos_error_status_code_val)
                else:
                    eos_error_status_code = None

        if capture_fields:
            status_val = capture_fields.get("status_code")
            if isinstance(status_val, int):
                status_code = status_val
            elif isinstance(status_val, float) and status_val.is_integer():
                status_code = int(status_val)

            retry_after_val = capture_fields.get("retry_after_seconds")
            if isinstance(retry_after_val, int | float):
                retry_after_seconds = float(retry_after_val)

            retry_attempt_val = capture_fields.get("retry_attempt")
            if isinstance(retry_attempt_val, int):
                retry_attempt = retry_attempt_val
            elif (
                isinstance(retry_attempt_val, float) and retry_attempt_val.is_integer()
            ):
                retry_attempt = int(retry_attempt_val)

            is_retry_val = capture_fields.get("is_retry")
            if isinstance(is_retry_val, bool):
                is_retry = is_retry_val

            account_val = capture_fields.get("account_id")
            if isinstance(account_val, str) and account_val:
                account_id = account_val

            request_ts_val = capture_fields.get("request_timestamp")
            if isinstance(request_ts_val, int | float):
                request_timestamp = float(request_ts_val)

            response_ts_val = capture_fields.get("response_timestamp")
            if isinstance(response_ts_val, int | float):
                response_timestamp = float(response_ts_val)

            latency_val = capture_fields.get("latency_ms")
            if isinstance(latency_val, int | float):
                latency_ms = float(latency_val)

            ttfb_val = capture_fields.get("ttfb_ms")
            if isinstance(ttfb_val, int | float):
                ttfb_ms = float(ttfb_val)

            stream_dur_val = capture_fields.get("stream_duration_ms")
            if isinstance(stream_dur_val, int | float):
                stream_duration_ms = float(stream_dur_val)

        metadata = CaptureMetadata(
            session_id=resolved_session,
            backend=backend,
            model=model,
            key_name=key_name,
            client_host=client_host,
            user_agent=user_agent,
            request_id=request_id,
            canonical_usage=canonical_usage,
            status_code=status_code,
            retry_after_seconds=retry_after_seconds,
            retry_attempt=retry_attempt,
            is_retry=is_retry,
            account_id=account_id,
            request_timestamp=request_timestamp,
            response_timestamp=response_timestamp,
            latency_ms=latency_ms,
            ttfb_ms=ttfb_ms,
            stream_duration_ms=stream_duration_ms,
            eos=eos,
            eos_signal=eos_signal,
            eos_reason=eos_reason,
            eos_termination_category=eos_termination_category,
            eos_error_classification=eos_error_classification,
            eos_error_status_code=eos_error_status_code,
        )

        return metadata

    async def capture_inbound_request(
        self,
        *,
        context: RequestContext | None,
        session_id: str | None,
        request_payload: Any,
        raw_body: bytes | None = None,
        capture_metadata: dict[str, JsonValue] | None = None,
    ) -> None:
        """Capture inbound request from client to proxy."""
        if not self.enabled():
            return

        self._maybe_start_flush_task()

        # Prefer raw_body if provided, otherwise extract from payload using deterministic serialization
        data = (
            raw_body if raw_body is not None else serialize_for_capture(request_payload)
        )

        # Extract model from payload if available
        model: str | None = None
        if hasattr(request_payload, "model"):
            model = str(request_payload.model)
        elif isinstance(request_payload, dict):
            model = str(request_payload.get("model", ""))

        metadata = self._extract_context_metadata(
            context,
            session_id,
            backend="client",
            model=model,
            capture_metadata=capture_metadata,
        )

        entry = CaptureEntry(
            timestamp=_get_timestamp(),
            direction=CaptureDirection.CLIENT_TO_PROXY,
            sequence=await self._get_next_sequence(),
            data=data,
            metadata=metadata,
        )

        await self._buffer_entry(entry)

    async def capture_outbound_request(
        self,
        *,
        context: RequestContext | None,
        session_id: str | None,
        backend: str,
        model: str,
        key_name: str | None,
        request_payload: Any,
        capture_metadata: dict[str, JsonValue] | None = None,
    ) -> None:
        """Capture outbound request to backend."""
        if not self.enabled():
            return

        self._maybe_start_flush_task()

        data = serialize_for_capture(request_payload)
        metadata = self._extract_context_metadata(
            context,
            session_id,
            backend=backend,
            model=model,
            key_name=key_name,
            capture_metadata=capture_metadata,
        )

        if metadata.request_id:
            async with self._timing_lock:
                self._request_timings[metadata.request_id] = _RequestTimingState(
                    _get_timestamp()
                )

        entry = CaptureEntry(
            timestamp=_get_timestamp(),
            direction=CaptureDirection.PROXY_TO_BACKEND,
            sequence=await self._get_next_sequence(),
            data=data,
            metadata=metadata,
        )

        await self._buffer_entry(entry)

    async def capture_inbound_response(
        self,
        *,
        context: RequestContext | None,
        session_id: str | None,
        backend: str,
        model: str,
        key_name: str | None,
        response_content: dict[str, JsonValue] | bytes | None,
        canonical_usage: CanonicalUsageRecord | None = None,
        capture_metadata: dict[str, JsonValue] | None = None,
    ) -> None:
        """Capture inbound response from backend."""
        if not self.enabled():
            return

        self._maybe_start_flush_task()

        # Convert CanonicalUsageRecord to dict for internal storage
        canonical_usage_dict = canonical_usage.model_dump() if canonical_usage else None

        data = serialize_for_capture(response_content)
        metadata_fields = capture_metadata.copy() if capture_metadata else {}
        response_ts = _get_timestamp()

        request_id: str | None = None
        if context:
            rid = getattr(context, "request_id", None)
            if isinstance(rid, str) and rid:
                request_id = rid

        if request_id:
            async with self._timing_lock:
                timing = self._request_timings.pop(request_id, None)
            if timing:
                metadata_fields["request_timestamp"] = timing.request_ts
                metadata_fields["response_timestamp"] = response_ts
                metadata_fields["latency_ms"] = (
                    response_ts - timing.request_ts
                ) * 1000.0

        metadata = self._extract_context_metadata(
            context,
            session_id,
            backend=backend,
            model=model,
            key_name=key_name,
            canonical_usage=canonical_usage_dict,
            capture_metadata=metadata_fields or None,
        )

        entry = CaptureEntry(
            timestamp=_get_timestamp(),
            direction=CaptureDirection.BACKEND_TO_PROXY,
            sequence=await self._get_next_sequence(),
            data=data,
            metadata=metadata,
        )

        await self._buffer_entry(entry)

    async def capture_outbound_response(
        self,
        *,
        context: RequestContext | None,
        session_id: str | None,
        backend: str | None,
        model: str | None,
        key_name: str | None,
        response_content: Any,
        capture_metadata: dict[str, JsonValue] | None = None,
    ) -> None:
        """Capture outbound response to client."""
        if not self.enabled():
            return

        self._maybe_start_flush_task()

        data = serialize_for_capture(response_content)
        metadata = self._extract_context_metadata(
            context,
            session_id,
            backend=backend,
            model=model,
            key_name=key_name,
            capture_metadata=capture_metadata,
        )

        entry = CaptureEntry(
            timestamp=_get_timestamp(),
            direction=CaptureDirection.PROXY_TO_CLIENT,
            sequence=await self._get_next_sequence(),
            data=data,
            metadata=metadata,
        )

        await self._buffer_entry(entry)

    def wrap_inbound_stream(
        self,
        *,
        context: RequestContext | None,
        session_id: str | None,
        backend: str,
        model: str,
        key_name: str | None,
        stream: AsyncIterator[bytes],
        capture_metadata: dict[str, JsonValue] | None = None,
    ) -> AsyncIterator[bytes]:
        """Wrap streaming response from backend for capture."""
        if not self.enabled():
            return _StreamPassthroughWrapper(stream)

        self._maybe_start_flush_task()

        base_metadata = self._extract_context_metadata(
            context,
            session_id,
            backend=backend,
            model=model,
            key_name=key_name,
            capture_metadata=capture_metadata,
        )

        async def _capture_stream() -> AsyncIterator[bytes]:
            chunk_count = 0
            total_bytes = 0
            stream_session_id = base_metadata.session_id or self._session_id
            request_id = base_metadata.request_id
            metadata_fields = capture_metadata.copy() if capture_metadata else {}
            stream_start_ts = _get_timestamp()

            if request_id:
                async with self._timing_lock:
                    timing = self._request_timings.get(request_id)
                    if timing:
                        timing.stream_start_ts = stream_start_ts
                        metadata_fields["request_timestamp"] = timing.request_ts

            request_ts_val = metadata_fields.get("request_timestamp")
            request_ts = (
                float(request_ts_val)
                if isinstance(request_ts_val, int | float)
                else None
            )

            # Stream start marker
            start_metadata = CaptureMetadata(
                session_id=stream_session_id,
                backend=backend,
                model=model,
                key_name=key_name,
                client_host=base_metadata.client_host,
                user_agent=base_metadata.user_agent,
                request_id=base_metadata.request_id,
                is_stream_start=True,
                status_code=base_metadata.status_code,
                retry_after_seconds=base_metadata.retry_after_seconds,
                retry_attempt=base_metadata.retry_attempt,
                is_retry=base_metadata.is_retry,
                account_id=base_metadata.account_id,
                request_timestamp=request_ts,
            )
            start_entry = CaptureEntry(
                timestamp=stream_start_ts,
                direction=CaptureDirection.BACKEND_TO_PROXY,
                sequence=await self._get_next_sequence(),
                data=b"",
                metadata=start_metadata,
            )
            await self._buffer_entry(start_entry)

            async for chunk in stream:
                chunk_count += 1
                total_bytes += len(chunk)
                chunk_capture_metadata: dict[str, JsonValue] = {}

                if request_id:
                    async with self._timing_lock:
                        timing = self._request_timings.get(request_id)
                        if timing and timing.first_byte_ts is None:
                            timing.first_byte_ts = _get_timestamp()
                            computed_ttfb_ms = (
                                timing.first_byte_ts - timing.request_ts
                            ) * 1000.0
                            chunk_capture_metadata["ttfb_ms"] = computed_ttfb_ms

                ttfb_val = chunk_capture_metadata.get("ttfb_ms")
                ttfb_ms = float(ttfb_val) if isinstance(ttfb_val, int | float) else None

                chunk_metadata = CaptureMetadata(
                    session_id=stream_session_id,
                    chunk_index=chunk_count,
                    request_id=base_metadata.request_id,
                    ttfb_ms=ttfb_ms,
                )
                chunk_entry = CaptureEntry(
                    timestamp=_get_timestamp(),
                    direction=CaptureDirection.BACKEND_TO_PROXY,
                    sequence=await self._get_next_sequence(),
                    data=chunk,
                    metadata=chunk_metadata,
                )
                await self._buffer_entry(chunk_entry)

                yield chunk

            # Stream end marker
            end_ts = _get_timestamp()
            end_capture_metadata: dict[str, JsonValue] = {}
            timing_snapshot: _RequestTimingState | None = None
            if request_id:
                async with self._timing_lock:
                    timing_snapshot = self._request_timings.pop(request_id, None)

            if timing_snapshot:
                end_capture_metadata["request_timestamp"] = timing_snapshot.request_ts
                end_capture_metadata["response_timestamp"] = end_ts
                end_capture_metadata["latency_ms"] = (
                    end_ts - timing_snapshot.request_ts
                ) * 1000.0
                if timing_snapshot.stream_start_ts is not None:
                    end_capture_metadata["stream_duration_ms"] = (
                        end_ts - timing_snapshot.stream_start_ts
                    ) * 1000.0

            end_request_ts_val = end_capture_metadata.get("request_timestamp")
            end_request_ts = (
                float(end_request_ts_val)
                if isinstance(end_request_ts_val, int | float)
                else None
            )
            end_response_ts_val = end_capture_metadata.get("response_timestamp")
            end_response_ts = (
                float(end_response_ts_val)
                if isinstance(end_response_ts_val, int | float)
                else None
            )
            end_latency_val = end_capture_metadata.get("latency_ms")
            end_latency_ms = (
                float(end_latency_val)
                if isinstance(end_latency_val, int | float)
                else None
            )
            end_stream_dur_val = end_capture_metadata.get("stream_duration_ms")
            end_stream_duration_ms = (
                float(end_stream_dur_val)
                if isinstance(end_stream_dur_val, int | float)
                else None
            )

            end_metadata = CaptureMetadata(
                session_id=stream_session_id,
                backend=backend,
                model=model,
                key_name=key_name,
                request_id=base_metadata.request_id,
                is_stream_end=True,
                total_chunks=chunk_count,
                total_bytes=total_bytes,
                status_code=base_metadata.status_code,
                retry_after_seconds=base_metadata.retry_after_seconds,
                retry_attempt=base_metadata.retry_attempt,
                is_retry=base_metadata.is_retry,
                account_id=base_metadata.account_id,
                request_timestamp=end_request_ts,
                response_timestamp=end_response_ts,
                latency_ms=end_latency_ms,
                stream_duration_ms=end_stream_duration_ms,
            )
            end_entry = CaptureEntry(
                timestamp=end_ts,
                direction=CaptureDirection.BACKEND_TO_PROXY,
                sequence=await self._get_next_sequence(),
                data=b"",
                metadata=end_metadata,
            )
            await self._buffer_entry(end_entry)

        return _capture_stream()

    async def capture_stream_completion(
        self,
        *,
        context: RequestContext | None,
        session_id: str | None,
        backend: str,
        model: str,
        key_name: str | None,
        canonical_usage: CanonicalUsageRecord | None = None,
        eos_metadata: dict[str, Any] | None = None,
        capture_metadata: dict[str, JsonValue] | None = None,
    ) -> None:
        """Capture canonical usage for completed streaming response."""
        # Allow EoS metadata even without canonical_usage
        if not self.enabled() or (canonical_usage is None and eos_metadata is None):
            return

        self._maybe_start_flush_task()

        # Resolve session ID
        resolved_session = session_id
        if not resolved_session or not str(resolved_session).strip():
            if context:
                rid = getattr(context, "request_id", None)
                if rid and not _is_mock(rid):
                    resolved_session = str(rid)
            if not resolved_session:
                resolved_session = self._session_id

        # Convert CanonicalUsageRecord to dict for metadata
        canonical_usage_dict = canonical_usage.model_dump() if canonical_usage else None

        # Create completion entry with canonical_usage and/or EoS metadata
        # This entry follows the stream_end entry and includes canonical_usage
        completion_metadata = self._extract_context_metadata(
            context,
            resolved_session,
            backend=backend,
            model=model,
            key_name=key_name,
            canonical_usage=canonical_usage_dict,
            eos_metadata=eos_metadata,
            capture_metadata=capture_metadata,
        )
        completion_entry = CaptureEntry(
            timestamp=_get_timestamp(),
            direction=CaptureDirection.BACKEND_TO_PROXY,
            sequence=await self._get_next_sequence(),
            data=b"",
            metadata=completion_metadata,
        )
        await self._buffer_entry(completion_entry)

    def wrap_outbound_stream(
        self,
        *,
        context: RequestContext | None,
        session_id: str | None,
        backend: str | None,
        model: str | None,
        key_name: str | None,
        stream: AsyncIterator[bytes],
        capture_metadata: dict[str, JsonValue] | None = None,
    ) -> AsyncIterator[bytes]:
        """Wrap streaming response to client for capture."""
        if not self.enabled():
            return _StreamPassthroughWrapper(stream)

        self._maybe_start_flush_task()

        base_metadata = self._extract_context_metadata(
            context,
            session_id,
            backend=backend,
            model=model,
            key_name=key_name,
            capture_metadata=capture_metadata,
        )

        async def _capture_stream() -> AsyncIterator[bytes]:
            chunk_count = 0
            total_bytes = 0
            stream_session_id = base_metadata.session_id or self._session_id

            # Stream start marker
            start_metadata = CaptureMetadata(
                session_id=stream_session_id,
                backend=backend,
                model=model,
                key_name=key_name,
                client_host=base_metadata.client_host,
                user_agent=base_metadata.user_agent,
                request_id=base_metadata.request_id,
                is_stream_start=True,
                status_code=base_metadata.status_code,
                retry_after_seconds=base_metadata.retry_after_seconds,
                retry_attempt=base_metadata.retry_attempt,
                is_retry=base_metadata.is_retry,
                account_id=base_metadata.account_id,
            )
            start_entry = CaptureEntry(
                timestamp=_get_timestamp(),
                direction=CaptureDirection.PROXY_TO_CLIENT,
                sequence=await self._get_next_sequence(),
                data=b"",
                metadata=start_metadata,
            )
            await self._buffer_entry(start_entry)

            async for chunk in stream:
                chunk_count += 1
                total_bytes += len(chunk)

                chunk_metadata = CaptureMetadata(
                    session_id=stream_session_id,
                    chunk_index=chunk_count,
                    request_id=base_metadata.request_id,
                )
                chunk_entry = CaptureEntry(
                    timestamp=_get_timestamp(),
                    direction=CaptureDirection.PROXY_TO_CLIENT,
                    sequence=await self._get_next_sequence(),
                    data=chunk,
                    metadata=chunk_metadata,
                )
                await self._buffer_entry(chunk_entry)

                yield chunk

            # Stream end marker
            end_metadata = CaptureMetadata(
                session_id=stream_session_id,
                backend=backend,
                model=model,
                key_name=key_name,
                request_id=base_metadata.request_id,
                is_stream_end=True,
                total_chunks=chunk_count,
                total_bytes=total_bytes,
                status_code=base_metadata.status_code,
                retry_after_seconds=base_metadata.retry_after_seconds,
                retry_attempt=base_metadata.retry_attempt,
                is_retry=base_metadata.is_retry,
                account_id=base_metadata.account_id,
            )
            end_entry = CaptureEntry(
                timestamp=_get_timestamp(),
                direction=CaptureDirection.PROXY_TO_CLIENT,
                sequence=await self._get_next_sequence(),
                data=b"",
                metadata=end_metadata,
            )
            await self._buffer_entry(end_entry)

        return _capture_stream()

    async def _buffer_entry(self, entry: CaptureEntry) -> None:
        """Add entry to buffer for eventual flushing.

        Does not block the caller for flushing unless explicitly requested
        via force_flush_sync().
        """
        async with self._buffer_lock:
            self._buffer.append(entry)

            # Flush if buffer is full
            if len(self._buffer) >= self._max_buffer_entries:
                # Snapshot and flush in background thread to avoid blocking the stream task
                # for disk I/O (Requirement 7.1, 7.2 - performance and responsiveness)
                entries_to_write = self._buffer.copy()
                self._buffer.clear()

                try:
                    loop = asyncio.get_running_loop()
                    # Schedule write in executor without awaiting it
                    loop.run_in_executor(
                        None, self._write_entries_sync, entries_to_write
                    )
                except RuntimeError:
                    # No event loop; fallback to sync write
                    self._write_entries_sync(entries_to_write)

    async def _flush_buffer(self) -> None:
        """Flush buffered entries to file."""
        if not self._file_path:
            return

        entries_to_write: list[CaptureEntry] = []
        async with self._buffer_lock:
            if not self._buffer:
                return
            # Take snapshot and clear buffer
            entries_to_write = self._buffer.copy()
            self._buffer.clear()

        # Write entries outside lock
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._write_entries_sync, entries_to_write)
        except (OSError, RuntimeError) as e:
            # OSError: file I/O errors from executor
            # RuntimeError: executor or event loop errors
            logger.error(
                "Failed to flush capture buffer: %s",
                e,
                exc_info=True,
            )

    def _write_entries_sync(self, entries: list[CaptureEntry]) -> None:
        """Synchronously write entries to file."""
        if not self._file_path:
            return

        try:
            with open(self._file_path, "ab") as f:
                for entry in entries:
                    cbor2.dump(entry.to_dict(), f)
        except (OSError, ValueError, TypeError) as e:
            # OSError: file I/O errors (FileNotFoundError, PermissionError, etc.)
            # ValueError: CBOR encoding errors
            # TypeError: type errors during serialization
            logger.error(
                "Failed to write capture entries: %s",
                e,
                exc_info=True,
            )

    async def _background_flush_loop(self) -> None:
        """Background task to periodically flush buffer."""
        import contextlib

        try:
            while self._enabled:
                try:
                    await asyncio.sleep(self._flush_interval)
                    if not self._enabled:
                        break
                    if self._buffer:
                        await self._flush_buffer()
                except asyncio.CancelledError:
                    break
                except OSError as e:
                    logger.error(
                        "Background flush failed due to OS error: %s",
                        e,
                        exc_info=True,
                    )
                    continue
                except Exception as e:
                    logger.error(
                        "Background flush failed unexpectedly: %s",
                        e,
                        exc_info=True,
                    )
                    continue
        except asyncio.CancelledError:
            # Task cancelled during shutdown (intentionally silent control flow)
            with contextlib.suppress(asyncio.CancelledError):
                pass
        finally:
            # Final flush on exit
            if self._enabled and self._buffer:
                try:
                    await self._flush_buffer()
                except OSError as e:
                    logger.error(
                        "Final flush failed due to OS error: %s",
                        e,
                        exc_info=True,
                    )
                except Exception as e:
                    logger.error(
                        "Final flush failed unexpectedly: %s",
                        e,
                        exc_info=True,
                    )

    async def shutdown(self) -> None:
        """Gracefully stop capture and flush remaining data."""
        self._enabled = False

        # Cancel background task
        with self._flush_start_lock:
            if self._flush_task and not self._flush_task.done():
                self._flush_task.cancel()
                with contextlib.suppress(asyncio.CancelledError, asyncio.TimeoutError):
                    await asyncio.wait_for(self._flush_task, timeout=2.0)
                self._flush_task = None

        # Final flush
        if self._buffer:
            await self._flush_buffer()

        if self._file_path and logger.isEnabledFor(logging.INFO):
            logger.info("CBOR wire capture shutdown: %s", self._file_path)

    def get_capture_file_path(self) -> Path | None:
        """Return the path to the current capture file."""
        return self._file_path

    def get_session_id(self) -> str:
        """Return the current session ID."""
        return self._session_id

    def force_flush_sync(self) -> None:
        """Synchronous flush for testing or cleanup."""
        if not self._buffer or not self._file_path:
            return
        entries = self._buffer.copy()
        self._buffer.clear()
        self._write_entries_sync(entries)
