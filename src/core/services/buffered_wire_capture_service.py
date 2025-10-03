"""
High-performance buffered wire capture implementation.

This module provides a wire capture service that:
- Uses buffered I/O for performance
- Avoids logging infrastructure contamination
- Provides proper metadata without verbose logging
- Uses async I/O where possible
- Batches writes for efficiency
"""

from __future__ import annotations

import asyncio
import atexit
import json
import os
import time
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NamedTuple

from src.core.common.logging_utils import discover_api_keys_from_config_and_env
from src.core.config.app_config import AppConfig
from src.core.domain.request_context import RequestContext
from src.core.interfaces.wire_capture_interface import IWireCapture
from src.core.services.redaction_middleware import APIKeyRedactor


class WireCaptureEntry(NamedTuple):
    """Structured entry for wire capture data."""

    timestamp_iso: str
    timestamp_unix: float
    direction: str  # "outbound_request", "inbound_response", "stream_start", "stream_chunk", "stream_end"
    source: str
    destination: str
    session_id: str | None
    backend: str
    model: str
    key_name: str | None
    content_type: str  # "json", "text", "bytes"
    content_length: int
    payload: Any
    metadata: dict[str, Any]


class BufferedWireCapture(IWireCapture):
    """High-performance buffered wire capture implementation.

    Features:
    - Buffered writes for performance
    - Pure wire capture data (no logging contamination)
    - Structured JSON entries with rich metadata
    - Async I/O with background flushing
    - Configurable buffer size and flush intervals
    """

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._file_path: str | None = getattr(config.logging, "capture_file", None)

        # Buffer configuration
        self._buffer_size: int = getattr(
            config.logging, "capture_buffer_size", 64 * 1024
        )  # 64KB default
        self._flush_interval: float = getattr(
            config.logging, "capture_flush_interval", 1.0
        )  # 1 second default
        self._max_entries_per_flush: int = getattr(
            config.logging, "capture_max_entries_per_flush", 100
        )

        # Rotation configuration
        self._max_bytes: int | None = getattr(config.logging, "capture_max_bytes", None)
        self._max_files: int = max(
            0, int(getattr(config.logging, "capture_max_files", 0) or 0)
        )
        self._total_cap: int = int(
            getattr(config.logging, "capture_total_max_bytes", 0) or 0
        )

        # Internal state
        self._buffer: list[WireCaptureEntry] = []
        self._buffer_lock = asyncio.Lock()
        self._flush_task: asyncio.Task[None] | None = None
        self._last_flush_time: float = time.time()
        self._total_bytes_written: int = 0
        self._enabled: bool = False

        # Initialize redaction for wire capture data
        api_keys = discover_api_keys_from_config_and_env(config)
        self._redactor = APIKeyRedactor(api_keys)

        # Initialize if configured
        if self._file_path:
            self._initialize()
            # Ensure cleanup at interpreter exit to avoid pending tasks warnings
            atexit.register(self._atexit_cleanup)

    def _atexit_cleanup(self) -> None:
        """Best-effort cleanup for background task and buffered entries at process exit."""
        try:
            self._enabled = False
            if self._flush_task:
                self._flush_task.cancel()
        except Exception:
            pass
        # Attempt to write any remaining buffered entries synchronously
        try:
            if self._buffer and self._file_path:
                entries = list(self._buffer)
                self._buffer.clear()
                self._write_entries_sync(entries)
        except Exception:
            pass

    def _initialize(self) -> None:
        """Initialize the wire capture system."""
        if not self._file_path:
            return

        try:
            # Ensure directory exists
            Path(self._file_path).parent.mkdir(parents=True, exist_ok=True)

            # Test write access and write format header
            test_entry = WireCaptureEntry(
                timestamp_iso=datetime.now(timezone.utc).isoformat(),
                timestamp_unix=time.time(),
                direction="system_init",
                source="wire_capture_service",
                destination="file_system",
                session_id=None,
                backend="system",
                model="system",
                key_name=None,
                content_type="json",
                content_length=0,
                payload=self._redact_payload(
                    {
                        "message": "Wire capture initialized",
                        "format_version": "buffered_v1",
                        "format_description": "Buffered JSON Lines format with high-performance async I/O",
                    }
                ),
                metadata={
                    "buffer_size": self._buffer_size,
                    "flush_interval": self._flush_interval,
                    "implementation": "BufferedWireCapture",
                },
            )

            # Write test entry synchronously during init
            self._write_entry_sync(test_entry)
            self._enabled = True

            # Start background flush task if an event loop is running
            try:
                # Avoid starting background task during pytest to prevent stray pending tasks
                if os.getenv("PYTEST_CURRENT_TEST"):
                    self._flush_task = None
                else:
                    loop = asyncio.get_running_loop()
                    self._flush_task = loop.create_task(self._background_flush_loop())
            except RuntimeError:
                # No running loop at init time (common in sync contexts/tests).
                # Keep capture enabled; we'll start the task on first use.
                self._flush_task = None

        except Exception:
            # Don't use logger here - this is wire capture, not application logging
            # Store error in a way that doesn't contaminate wire capture
            self._enabled = False
            # Cancel background task if it was started
            if self._flush_task:
                self._flush_task.cancel()
            # Could write to a separate error file or stderr, but not to wire capture file

    def enabled(self) -> bool:
        """Return True if wire capture is enabled and functional."""
        return self._enabled

    def _maybe_start_flush_task(self) -> None:
        """Start background flush task if not running and loop is available."""
        if not self._enabled or self._flush_task is not None:
            return
        try:
            # Avoid starting background task during pytest to prevent stray pending tasks
            if os.getenv("PYTEST_CURRENT_TEST"):
                return
            loop = asyncio.get_running_loop()
            self._flush_task = loop.create_task(self._background_flush_loop())
        except RuntimeError:
            # Still no running loop; skip silently.
            return

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
        # Ensure background task runs in async contexts
        self._maybe_start_flush_task()

        entry = self._create_entry(
            direction="outbound_request",
            source=self._get_client_info(context),
            destination=backend,
            context=context,
            session_id=session_id,
            backend=backend,
            model=model,
            key_name=key_name,
            payload=request_payload,
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
    ) -> None:
        """Capture inbound response from backend."""
        if not self.enabled():
            return
        # Ensure background task runs in async contexts
        self._maybe_start_flush_task()

        entry = self._create_entry(
            direction="inbound_response",
            source=backend,
            destination=self._get_client_info(context),
            context=context,
            session_id=session_id,
            backend=backend,
            model=model,
            key_name=key_name,
            payload=response_content,
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
        """Wrap streaming response for capture."""
        if not self.enabled():
            return stream
        # Ensure background task runs in async contexts
        self._maybe_start_flush_task()

        async def _capture_stream() -> AsyncIterator[bytes]:
            # Stream start marker
            start_entry = self._create_entry(
                direction="stream_start",
                source=backend,
                destination=self._get_client_info(context),
                context=context,
                session_id=session_id,
                backend=backend,
                model=model,
                key_name=key_name,
                payload={"stream_type": "inbound_response"},
            )
            await self._buffer_entry(start_entry)

            total_bytes = 0
            chunk_count = 0

            async for chunk in stream:
                chunk_count += 1
                total_bytes += len(chunk)

                # Capture chunk (with optional size limits for performance)
                chunk_text = chunk.decode("utf-8", errors="replace")
                chunk_entry = self._create_entry(
                    direction="stream_chunk",
                    source=backend,
                    destination=self._get_client_info(context),
                    context=context,
                    session_id=session_id,
                    backend=backend,
                    model=model,
                    key_name=key_name,
                    payload=chunk_text,
                    metadata={"chunk_number": chunk_count, "chunk_bytes": len(chunk)},
                )
                await self._buffer_entry(chunk_entry)

                yield chunk

            # Stream end marker
            end_entry = self._create_entry(
                direction="stream_end",
                source=backend,
                destination=self._get_client_info(context),
                context=context,
                session_id=session_id,
                backend=backend,
                model=model,
                key_name=key_name,
                payload={"total_bytes": total_bytes, "total_chunks": chunk_count},
            )
            await self._buffer_entry(end_entry)

        return _capture_stream()

    def _create_entry(
        self,
        *,
        direction: str,
        source: str,
        destination: str,
        context: RequestContext | None,
        session_id: str | None,
        backend: str,
        model: str,
        key_name: str | None,
        payload: Any,
        metadata: dict[str, Any] | None = None,
    ) -> WireCaptureEntry:
        """Create a structured wire capture entry."""
        now = datetime.now(timezone.utc)

        # Determine content type and length
        content_type = "unknown"
        content_length = 0

        if isinstance(payload, dict | list):
            content_type = "json"
            try:
                content_length = len(
                    json.dumps(payload, ensure_ascii=False).encode("utf-8")
                )
            except Exception:
                content_length = len(str(payload).encode("utf-8"))
        elif isinstance(payload, str):
            content_type = "text"
            content_length = len(payload.encode("utf-8"))
        elif isinstance(payload, bytes):
            content_type = "bytes"
            content_length = len(payload)
        else:
            content_type = "object"
            content_length = len(str(payload).encode("utf-8"))

        # Build metadata
        entry_metadata = {
            "client_host": getattr(context, "client_host", None) if context else None,
            "user_agent": getattr(context, "agent", None) if context else None,
            "request_id": getattr(context, "request_id", None) if context else None,
        }
        if metadata:
            entry_metadata.update(metadata)

        return WireCaptureEntry(
            timestamp_iso=now.isoformat(),
            timestamp_unix=now.timestamp(),
            direction=direction,
            source=source,
            destination=destination,
            session_id=session_id,
            backend=backend,
            model=model,
            key_name=key_name,
            content_type=content_type,
            content_length=content_length,
            payload=self._redact_payload(payload),
            metadata=entry_metadata,
        )

    def _get_client_info(self, context: RequestContext | None) -> str:
        """Extract client information from context."""
        if not context:
            return "unknown_client"

        client_host = getattr(context, "client_host", None)
        agent = getattr(context, "agent", None)

        if client_host and agent:
            return f"{client_host!s}({agent!s})"
        elif client_host:
            return str(client_host)
        elif agent:
            return f"unknown_host({agent!s})"
        else:
            return "unknown_client"

    def _redact_payload(self, payload: Any) -> Any:
        """Recursively redact sensitive information from payload."""
        if isinstance(payload, dict):
            return {k: self._redact_payload(v) for k, v in payload.items()}
        elif isinstance(payload, list):
            return [self._redact_payload(item) for item in payload]
        elif isinstance(payload, str):
            return self._redactor.redact(payload)
        else:
            return payload

    async def _buffer_entry(self, entry: WireCaptureEntry) -> None:
        """Add entry to buffer for eventual flushing."""
        async with self._buffer_lock:
            self._buffer.append(entry)

            # Check if we should flush immediately
            should_flush = (
                len(self._buffer) >= self._max_entries_per_flush
                or (time.time() - self._last_flush_time) >= self._flush_interval
            )

            if should_flush:
                await self._flush_buffer()

    async def _flush_buffer(self) -> None:
        """Flush buffered entries to file."""
        if not self._buffer or not self._file_path:
            return

        # Take snapshot of buffer and clear it
        entries_to_write = self._buffer.copy()
        self._buffer.clear()
        self._last_flush_time = time.time()

        # Write entries (do this outside the lock to avoid blocking)
        import contextlib

        with contextlib.suppress(Exception):
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._write_entries_sync, entries_to_write)

    def _write_entries_sync(self, entries: list[WireCaptureEntry]) -> None:
        """Synchronously write entries to file."""
        if not self._file_path:
            return

        try:
            with open(self._file_path, "a", encoding="utf-8") as f:
                for entry in entries:
                    json_line = json.dumps(
                        entry._asdict(), ensure_ascii=False, separators=(",", ":")
                    )
                    f.write(json_line + "\n")
                    self._total_bytes_written += len(json_line.encode("utf-8")) + 1

            # Check for rotation after writing
            self._check_rotation()

        except Exception:
            # Don't use logger here
            pass

    def _write_entry_sync(self, entry: WireCaptureEntry) -> None:
        """Write a single entry synchronously (used during initialization)."""
        if not self._file_path:
            return

        try:
            with open(self._file_path, "a", encoding="utf-8") as f:
                json_line = json.dumps(
                    entry._asdict(), ensure_ascii=False, separators=(",", ":")
                )
                f.write(json_line + "\n")
        except Exception:
            pass

    def _check_rotation(self) -> None:
        """Check if file rotation is needed."""
        if not self._file_path or not self._max_bytes:
            return

        try:
            if os.path.exists(self._file_path):
                current_size = os.path.getsize(self._file_path)
                if current_size > self._max_bytes:
                    self._perform_rotation()
        except Exception:
            pass

    def _perform_rotation(self) -> None:
        """Perform file rotation."""
        if not self._file_path:
            return

        try:
            # Simple rotation: move current to .1, .1 to .2, etc.
            if self._max_files > 0:
                for i in range(self._max_files, 0, -1):
                    src = f"{self._file_path}.{i}"
                    dst = f"{self._file_path}.{i+1}"
                    if os.path.exists(src):
                        if i == self._max_files:
                            os.remove(src)  # Remove oldest
                        else:
                            os.replace(src, dst)

                # Move current to .1
                if os.path.exists(self._file_path):
                    os.replace(self._file_path, f"{self._file_path}.1")
        except Exception:
            pass

    async def _background_flush_loop(self) -> None:
        """Background task to periodically flush buffer."""
        while self._enabled:
            try:
                await asyncio.sleep(self._flush_interval)
                async with self._buffer_lock:
                    if self._buffer:
                        await self._flush_buffer()
            except asyncio.CancelledError:
                break
            except Exception:
                # Don't use logger
                continue

    async def shutdown(self) -> None:
        """Shutdown wire capture and flush remaining data."""
        if self._flush_task:
            self._flush_task.cancel()
            import contextlib

            with contextlib.suppress(asyncio.CancelledError):
                await self._flush_task

        # Final flush
        async with self._buffer_lock:
            if self._buffer:
                await self._flush_buffer()

        self._enabled = False
