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
import base64
import contextlib
import json
import logging
import os
import time
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NamedTuple, cast
from uuid import uuid4

from src.core.common.logging_utils import discover_api_keys_from_config_and_env
from src.core.config.app_config import AppConfig
from src.core.domain.request_context import RequestContext
from src.core.interfaces.wire_capture_interface import IWireCapture
from src.core.services.redaction_middleware import APIKeyRedactor

logger = logging.getLogger(__name__)


def _is_mock(value: Any) -> bool:
    """Return True when value appears to be a unittest.mock object."""
    module_name = getattr(type(value), "__module__", "")
    return isinstance(module_name, str) and module_name.startswith("unittest.mock")


def _coerce_int(value: Any, default: int, *, minimum: int = 0) -> int:
    """Safely coerce arbitrary value to int with sane defaults."""
    if value is None or _is_mock(value):
        return default
    try:
        if isinstance(value, bool | int | float):
            numeric = int(value)
        elif isinstance(value, str):
            numeric = int(float(value))
        else:
            return default
    except (TypeError, ValueError):
        return default
    return max(minimum, numeric)


def _coerce_optional_int(value: Any, *, minimum: int = 1) -> int | None:
    """Safely coerce value to optional int."""
    if value is None or _is_mock(value):
        return None
    try:
        if isinstance(value, bool | int | float):
            numeric = int(value)
        elif isinstance(value, str):
            numeric = int(float(value))
        else:
            return None
    except (TypeError, ValueError):
        return None
    return numeric if numeric >= minimum else None


def _coerce_float(value: Any, default: float, *, minimum: float = 0.0) -> float:
    """Safely coerce arbitrary value to float with lower bound."""
    if value is None or _is_mock(value):
        return default
    try:
        if isinstance(value, bool):
            numeric = float(int(value))
        elif isinstance(value, int | float | str):
            numeric = float(value)
        else:
            return default
    except (TypeError, ValueError):
        return default
    return max(minimum, numeric)


def _coerce_path(value: Any) -> str | None:
    """Return filesystem path string when value is path-like."""
    if value is None or _is_mock(value):
        return None
    if isinstance(value, str | os.PathLike):
        try:
            return os.fspath(value)
        except (TypeError, ValueError):
            return None
    return None


def _sanitize_metadata_value(value: Any) -> Any:
    """Convert metadata values to JSON-serializable representations."""
    if value is None or isinstance(value, str | int | float | bool):
        return value
    try:
        return str(value)
    except Exception:
        return repr(value)


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
        logging_cfg = getattr(config, "logging", None)
        raw_file_path = (
            getattr(logging_cfg, "capture_file", None) if logging_cfg else None
        )
        self._file_path: str | None = _coerce_path(raw_file_path)

        # Buffer configuration
        capture_buffer_size = (
            getattr(logging_cfg, "capture_buffer_size", None) if logging_cfg else None
        )
        self._buffer_size: int = _coerce_int(capture_buffer_size, 64 * 1024, minimum=1)

        flush_interval = (
            getattr(logging_cfg, "capture_flush_interval", None)
            if logging_cfg
            else None
        )
        self._flush_interval: float = _coerce_float(flush_interval, 1.0, minimum=0.05)

        max_entries = (
            getattr(logging_cfg, "capture_max_entries_per_flush", None)
            if logging_cfg
            else None
        )
        self._max_entries_per_flush: int = _coerce_int(max_entries, 100, minimum=1)

        # Rotation configuration
        max_bytes = (
            getattr(logging_cfg, "capture_max_bytes", None) if logging_cfg else None
        )
        self._max_bytes: int | None = _coerce_optional_int(max_bytes, minimum=1)

        max_files = (
            getattr(logging_cfg, "capture_max_files", None) if logging_cfg else None
        )
        self._max_files: int = _coerce_int(max_files, 0, minimum=0)

        total_cap = (
            getattr(logging_cfg, "capture_total_max_bytes", None)
            if logging_cfg
            else None
        )
        self._total_cap: int = _coerce_int(total_cap, 0, minimum=0)

        # Internal state
        self._buffer: list[WireCaptureEntry] = []
        self._buffer_lock = asyncio.Lock()
        self._flush_task: asyncio.Task[None] | None = None
        self._last_flush_time: float = time.time()
        self._total_bytes_written: int = 0
        self._enabled: bool = False

        # PERFORMANCE OPTIMIZATION: Cache JSON serialization to avoid repeated encoding
        self._content_length_cache: dict[int, int] = {}
        self._json_cache: dict[int, str] = {}
        self._cache_max_size: int = 1000  # Limit cache size to prevent memory leaks

        # Initialize redaction for wire capture data
        api_keys = discover_api_keys_from_config_and_env(config)
        self._redactor = APIKeyRedactor(api_keys)
        self._raw_preview_limit: int = 4096

        # Initialize if configured
        if self._file_path:
            self._initialize()

    def __del__(self) -> None:
        """Cleanup resources when the instance is destroyed."""
        if (
            hasattr(self, "_flush_task")
            and self._flush_task
            and not self._flush_task.done()
        ):
            import logging

            def _can_write(handler: logging.Handler) -> bool:
                stream = getattr(handler, "stream", None)
                return stream is None or not getattr(stream, "closed", False)

            def _safe_to_log() -> bool:
                try:
                    handlers = set(logger.handlers)
                    root = logging.getLogger()
                    handlers.update(root.handlers)
                    return all(_can_write(h) for h in handlers)
                except Exception:
                    return False

            if _safe_to_log():
                with contextlib.suppress(Exception):
                    logger.warning(
                        "BufferedWireCapture was garbage collected without being shut down. "
                        "Call shutdown() to ensure data is flushed and tasks are cleaned up."
                    )
        self.force_shutdown_sync()

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

    def _get_content_length_cached(self, payload: Any) -> int:
        """Get content length with caching to avoid repeated JSON serialization."""
        # Use object id as cache key for identity-based caching
        payload_id = id(payload)

        # Check cache first
        if payload_id in self._content_length_cache:
            return self._content_length_cache[payload_id]

        # Calculate and cache the result
        if isinstance(payload, dict | list):
            content_length = len(
                json.dumps(payload, ensure_ascii=False).encode("utf-8")
            )
        elif isinstance(payload, str):
            content_length = len(payload.encode("utf-8"))
        elif isinstance(payload, bytes):
            content_length = len(payload)
        else:
            content_length = len(str(payload).encode("utf-8"))

        # Maintain cache size limit
        if len(self._content_length_cache) >= self._cache_max_size:
            # Remove oldest entries (simple FIFO)
            oldest_key = next(iter(self._content_length_cache))
            del self._content_length_cache[oldest_key]

        self._content_length_cache[payload_id] = content_length
        return content_length

    def _serialize_entry_cached(self, entry: WireCaptureEntry) -> str:
        """Serialize entry to JSON with caching to avoid repeated serialization."""
        # Serialize without object-identity caching to avoid stale reuse
        return json.dumps(entry._asdict(), ensure_ascii=False, separators=(",", ":"))

    def _maybe_start_flush_task(self) -> None:
        """Start background flush task if not running and loop is available."""
        if not self._enabled or self._flush_task is not None:
            return
        try:
            loop = asyncio.get_running_loop()
            self._flush_task = loop.create_task(self._background_flush_loop())
        except RuntimeError:
            # Still no running loop; skip silently.
            return

    async def capture_inbound_request(
        self,
        *,
        context: RequestContext | None,
        session_id: str | None,
        request_payload: Any,
        raw_body: bytes | None = None,
    ) -> None:
        """Capture inbound request from client to proxy.

        Args:
            context: Request context with client information
            session_id: Session ID if available
            request_payload: Request payload (usually ChatRequest)
            raw_body: Raw HTTP body bytes as received from the client
        """
        if not self.enabled():
            return
        # Ensure background task runs in async contexts
        self._maybe_start_flush_task()

        # Extract model from request payload if available
        model = "N/A"
        if hasattr(request_payload, "model"):
            model = str(request_payload.model)
        elif isinstance(request_payload, dict):
            model = str(request_payload.get("model", "N/A"))

        normalized_payload = self._normalize_payload(request_payload)
        payload: Any
        if raw_body:
            payload = {
                "raw": self._summarize_raw_body(raw_body),
                "parsed": normalized_payload,
            }
        else:
            payload = normalized_payload

        entry = self._create_entry(
            direction="inbound_request",
            source=self._get_client_info(context),
            destination="proxy",
            context=context,
            session_id=session_id,
            backend="client",
            model=model,
            key_name=None,
            payload=payload,
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
            return _StreamPassthroughWrapper(stream)
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

        if isinstance(payload, dict | list):
            content_type = "json"
        elif isinstance(payload, str):
            content_type = "text"
        elif isinstance(payload, bytes):
            content_type = "bytes"
        else:
            content_type = "object"

        # PERFORMANCE OPTIMIZATION: Use cached content length calculation
        content_length = self._get_content_length_cached(payload)

        # Build metadata
        entry_metadata = {
            "client_host": _sanitize_metadata_value(
                getattr(context, "client_host", None) if context else None
            ),
            "user_agent": _sanitize_metadata_value(
                getattr(context, "agent", None) if context else None
            ),
            "request_id": _sanitize_metadata_value(
                getattr(context, "request_id", None) if context else None
            ),
        }
        if metadata:
            for key, value in metadata.items():
                entry_metadata[key] = _sanitize_metadata_value(value)

        resolved_session_id = session_id
        if not resolved_session_id or not str(resolved_session_id).strip():
            resolved_session_id = None
            request_id = None
            if context is not None:
                request_id = getattr(context, "request_id", None)
                if _is_mock(request_id):
                    request_id = None
            resolved_session_id = request_id or uuid4().hex

        return WireCaptureEntry(
            timestamp_iso=now.isoformat(),
            timestamp_unix=now.timestamp(),
            direction=direction,
            source=source,
            destination=destination,
            session_id=str(resolved_session_id),
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

        if _is_mock(client_host):
            client_host = None
        if _is_mock(agent):
            agent = None

        if client_host and agent:
            return f"{client_host!s}({agent!s})"
        elif client_host:
            return str(client_host)
        elif agent:
            return f"unknown_host({agent!s})"
        else:
            return "unknown_client"

    def _summarize_raw_body(self, raw_body: bytes) -> dict[str, Any]:
        preview_len = min(len(raw_body), self._raw_preview_limit)
        preview_bytes = raw_body[:preview_len]
        return {
            "length": len(raw_body),
            "preview": preview_bytes.decode("utf-8", errors="replace"),
            "truncated": len(raw_body) > preview_len,
        }

    def _normalize_payload(self, payload: Any) -> Any:
        if payload is None or isinstance(
            payload, dict | list | str | int | float | bool
        ):
            return payload
        if isinstance(payload, bytes):
            return payload
        if hasattr(payload, "model_dump") and callable(payload.model_dump):
            with contextlib.suppress(Exception):
                return payload.model_dump()
        if hasattr(payload, "__dict__"):
            with contextlib.suppress(Exception):
                return dict(payload.__dict__)
        with contextlib.suppress(Exception):
            return str(payload)
        return None

    def _redact_payload(self, payload: Any) -> Any:
        """Recursively redact sensitive information from payload."""
        if isinstance(payload, dict):
            return {k: self._redact_payload(v) for k, v in payload.items()}
        elif isinstance(payload, list):
            return [self._redact_payload(item) for item in payload]
        elif isinstance(payload, bytes):
            encoded = base64.b64encode(payload).decode("ascii")
            return {"encoding": "base64", "data": encoded}
        elif isinstance(payload, str):
            redacted = self._redactor.redact(payload)
            return redacted.replace("(API_KEY_HAS_BEEN_REDACTED)", "[REDACTED]")
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
                    # PERFORMANCE OPTIMIZATION: Use cached JSON serialization
                    json_line = self._serialize_entry_cached(entry)
                    f.write(json_line + "\n")
                    # PERFORMANCE OPTIMIZATION: Avoid repeated encoding for length calculation
                    self._total_bytes_written += (
                        len(json_line) + 1
                    )  # json_line is already a string

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
                # PERFORMANCE OPTIMIZATION: Use cached JSON serialization
                json_line = self._serialize_entry_cached(entry)
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

    def _robust_replace(
        self, src: str, dst: str, retries: int = 5, delay: float = 0.1
    ) -> None:
        """Attempt to replace a file with retries to handle Windows file locking."""
        for i in range(retries):
            try:
                os.replace(src, dst)
                return
            except PermissionError:
                if i < retries - 1:
                    time.sleep(delay)
                else:
                    raise

    def _perform_rotation(self) -> None:
        """Perform file rotation."""
        if not self._file_path or self._max_files <= 0:
            return

        try:
            # Correct rotation: remove oldest, then shift files up.
            # e.g., for max_files=3: remove .3, .2->.3, .1->.2, .log->.1

            # 1. Remove the oldest log file if it exists
            oldest_log = f"{self._file_path}.{self._max_files}"
            if os.path.exists(oldest_log):
                os.remove(oldest_log)

            # 2. Shift intermediate logs up
            for i in range(self._max_files - 1, 0, -1):
                src = f"{self._file_path}.{i}"
                dst = f"{self._file_path}.{i + 1}"
                if os.path.exists(src):
                    self._robust_replace(src, dst)

            # 3. Rotate the current log to .1
            if os.path.exists(self._file_path):
                self._robust_replace(self._file_path, f"{self._file_path}.1")

            # 4. Ensure a fresh file exists for subsequent writes
            with open(self._file_path, "a", encoding="utf-8"):
                pass
        except Exception:
            # Suppress errors during rotation to avoid crashing the service
            pass

    async def _background_flush_loop(self) -> None:
        """Background task to periodically flush buffer."""
        try:
            while self._enabled:
                try:
                    await asyncio.sleep(self._flush_interval)
                    # Check again after sleep in case we were disabled during sleep
                    if not self._enabled:
                        break
                    async with self._buffer_lock:
                        if self._buffer:
                            await self._flush_buffer()
                except asyncio.CancelledError:
                    # Task was cancelled, exit cleanly
                    break
                except Exception:
                    # Don't use logger, but continue processing
                    continue
        finally:
            # Final flush attempt on exit if still enabled
            if self._enabled and self._buffer:
                try:
                    async with self._buffer_lock:
                        if self._buffer:
                            await self._flush_buffer()
                except Exception:
                    # Best effort flush on exit
                    pass

    async def shutdown(self) -> None:
        """Shutdown wire capture and flush remaining data."""
        # Disable first to signal the background task to stop
        self._enabled = False

        # Cancel and wait for the background task to complete
        if self._flush_task and not self._flush_task.done():
            self._flush_task.cancel()
            import contextlib

            # Wait for the task to complete with a timeout
            with contextlib.suppress(
                asyncio.CancelledError, asyncio.TimeoutError, RuntimeError
            ):
                await asyncio.wait_for(self._flush_task, timeout=2.0)

            # Ensure task reference is cleared
            self._flush_task = None

        # Final flush
        async with self._buffer_lock:
            if self._buffer:
                await self._flush_buffer()

        # PERFORMANCE OPTIMIZATION: Clean up caches to prevent memory leaks
        self._content_length_cache.clear()
        self._json_cache.clear()

    def force_shutdown_sync(self) -> None:
        """Synchronous best-effort shutdown. Deprecated and unsafe from __del__."""
        # This method is problematic when called from __del__ during interpreter shutdown.
        # The async shutdown() method should be used for proper cleanup.
        # This is now a no-op to prevent errors during garbage collection.
        # The real fix is to ensure the application lifecycle calls shutdown().
        if not getattr(self, "_enabled", False):
            return

        self._enabled = False

        # Best-effort cancellation of the background task without awaiting.
        if self._flush_task and not self._flush_task.done():
            with contextlib.suppress(Exception):
                task = self._flush_task
                if hasattr(task, "_log_destroy_pending"):
                    cast(Any, task)._log_destroy_pending = False
                loop = task.get_loop()
                if not loop.is_closed():
                    task.cancel()
        self._flush_task = None
