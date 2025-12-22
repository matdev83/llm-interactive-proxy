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
import json
import logging
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import cbor2

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


def _get_timestamp() -> float:
    """Get current timestamp with nanosecond precision."""
    return time.time_ns() / 1_000_000_000


def _is_mock(value: Any) -> bool:
    """Return True when value appears to be a unittest.mock object."""
    module_name = getattr(type(value), "__module__", "")
    return isinstance(module_name, str) and module_name.startswith("unittest.mock")


def _extract_bytes(payload: Any) -> bytes:
    """Extract raw bytes from various payload types."""
    if isinstance(payload, bytes):
        return payload
    if isinstance(payload, bytearray):
        return bytes(payload)
    if isinstance(payload, str):
        return payload.encode("utf-8")
    if isinstance(payload, dict | list):
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
    if hasattr(payload, "model_dump") and callable(payload.model_dump):
        try:
            return json.dumps(
                payload.model_dump(), ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")
        except Exception:
            pass
    if hasattr(payload, "__dict__"):
        try:
            return json.dumps(
                dict(payload.__dict__), ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")
        except Exception:
            pass
    return str(payload).encode("utf-8")


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

        # File handle for current session
        self._file_path: Path | None = None
        self._header_written = False

        # Background flush task
        self._flush_task: asyncio.Task[None] | None = None
        self._flush_interval = 0.5  # seconds

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
                # Extract base name without extension
                log_path = Path(log_file)
                base_name = log_path.stem  # e.g., "proxy-1819" from "proxy-1819.log"
                return base_name
        except Exception:
            pass

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
            try:
                loop = asyncio.get_running_loop()
                self._flush_task = loop.create_task(self._background_flush_loop())
            except RuntimeError:
                # No running loop at init time
                self._flush_task = None

            logger.info(f"CBOR wire capture initialized: {self._file_path}")

        except Exception as e:
            logger.error(f"Failed to initialize CBOR wire capture: {e}")
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
        except Exception as e:
            logger.error(f"Failed to write capture header: {e}")

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
        if not self._enabled or self._flush_task is not None:
            return
        try:
            loop = asyncio.get_running_loop()
            self._flush_task = loop.create_task(self._background_flush_loop())
        except RuntimeError:
            pass

    def _extract_context_metadata(
        self,
        context: RequestContext | None,
        session_id: str | None,
        backend: str | None = None,
        model: str | None = None,
        key_name: str | None = None,
        canonical_usage: dict[str, Any] | None = None,
        eos_metadata: dict[str, Any] | None = None,
    ) -> CaptureMetadata:
        """Extract metadata from context and parameters."""
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

        # Extract EoS metadata if provided
        eos_fields = {}
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

        return CaptureMetadata(
            session_id=resolved_session,
            backend=backend,
            model=model,
            key_name=key_name,
            client_host=client_host,
            user_agent=user_agent,
            request_id=request_id,
            canonical_usage=canonical_usage,
            **eos_fields,
        )

    async def capture_inbound_request(
        self,
        *,
        context: RequestContext | None,
        session_id: str | None,
        request_payload: Any,
        raw_body: bytes | None = None,
    ) -> None:
        """Capture inbound request from client to proxy."""
        if not self.enabled():
            return

        self._maybe_start_flush_task()

        # Prefer raw_body if provided, otherwise extract from payload
        data = raw_body if raw_body is not None else _extract_bytes(request_payload)

        # Extract model from payload if available
        model: str | None = None
        if hasattr(request_payload, "model"):
            model = str(request_payload.model)
        elif isinstance(request_payload, dict):
            model = str(request_payload.get("model", ""))

        metadata = self._extract_context_metadata(
            context, session_id, backend="client", model=model
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
    ) -> None:
        """Capture outbound request to backend."""
        if not self.enabled():
            return

        self._maybe_start_flush_task()

        data = _extract_bytes(request_payload)
        metadata = self._extract_context_metadata(
            context, session_id, backend=backend, model=model, key_name=key_name
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
        response_content: Any,
        canonical_usage: dict[str, Any] | None = None,
    ) -> None:
        """Capture inbound response from backend."""
        if not self.enabled():
            return

        self._maybe_start_flush_task()

        data = _extract_bytes(response_content)
        metadata = self._extract_context_metadata(
            context,
            session_id,
            backend=backend,
            model=model,
            key_name=key_name,
            canonical_usage=canonical_usage,
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
    ) -> None:
        """Capture outbound response to client."""
        if not self.enabled():
            return

        self._maybe_start_flush_task()

        data = _extract_bytes(response_content)
        metadata = self._extract_context_metadata(
            context, session_id, backend=backend, model=model, key_name=key_name
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
    ) -> AsyncIterator[bytes]:
        """Wrap streaming response from backend for capture."""
        if not self.enabled():
            return _StreamPassthroughWrapper(stream)

        self._maybe_start_flush_task()

        base_metadata = self._extract_context_metadata(
            context, session_id, backend=backend, model=model, key_name=key_name
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
            )
            start_entry = CaptureEntry(
                timestamp=_get_timestamp(),
                direction=CaptureDirection.BACKEND_TO_PROXY,
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
            end_metadata = CaptureMetadata(
                session_id=stream_session_id,
                backend=backend,
                model=model,
                key_name=key_name,
                is_stream_end=True,
                total_chunks=chunk_count,
                total_bytes=total_bytes,
            )
            end_entry = CaptureEntry(
                timestamp=_get_timestamp(),
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
    ) -> AsyncIterator[bytes]:
        """Wrap streaming response to client for capture."""
        if not self.enabled():
            return _StreamPassthroughWrapper(stream)

        self._maybe_start_flush_task()

        base_metadata = self._extract_context_metadata(
            context, session_id, backend=backend, model=model, key_name=key_name
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
                is_stream_end=True,
                total_chunks=chunk_count,
                total_bytes=total_bytes,
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
        """Add entry to buffer for eventual flushing."""
        async with self._buffer_lock:
            self._buffer.append(entry)

            # Flush if buffer is full
            if len(self._buffer) >= self._max_buffer_entries:
                await self._flush_buffer()

    async def _flush_buffer(self) -> None:
        """Flush buffered entries to file."""
        if not self._buffer or not self._file_path:
            return

        # Take snapshot and clear buffer
        entries_to_write = self._buffer.copy()
        self._buffer.clear()

        # Write entries outside lock
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._write_entries_sync, entries_to_write)
        except Exception as e:
            logger.error(f"Failed to flush capture buffer: {e}")

    def _write_entries_sync(self, entries: list[CaptureEntry]) -> None:
        """Synchronously write entries to file."""
        if not self._file_path:
            return

        try:
            with open(self._file_path, "ab") as f:
                for entry in entries:
                    cbor2.dump(entry.to_dict(), f)
        except Exception as e:
            logger.error(f"Failed to write capture entries: {e}")

    async def _background_flush_loop(self) -> None:
        """Background task to periodically flush buffer."""
        try:
            while self._enabled:
                try:
                    await asyncio.sleep(self._flush_interval)
                    if not self._enabled:
                        break
                    async with self._buffer_lock:
                        if self._buffer:
                            await self._flush_buffer()
                except asyncio.CancelledError:
                    break
                except Exception:
                    continue
        except asyncio.CancelledError:
            pass
        finally:
            # Final flush on exit
            if self._enabled and self._buffer:
                try:
                    async with self._buffer_lock:
                        if self._buffer:
                            await self._flush_buffer()
                except Exception:
                    pass

    async def shutdown(self) -> None:
        """Gracefully stop capture and flush remaining data."""
        self._enabled = False

        # Cancel background task
        if self._flush_task and not self._flush_task.done():
            self._flush_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, asyncio.TimeoutError):
                await asyncio.wait_for(self._flush_task, timeout=2.0)
            self._flush_task = None

        # Final flush
        async with self._buffer_lock:
            if self._buffer:
                await self._flush_buffer()

        if self._file_path:
            logger.info(f"CBOR wire capture shutdown: {self._file_path}")

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
