from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import time
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic.types import JsonValue

from src.core.config.app_config import AppConfig
from src.core.domain.request_context import RequestContext
from src.core.domain.usage_canonical_record import CanonicalUsageRecord
from src.core.interfaces.wire_capture_interface import IWireCapture

logger = logging.getLogger(__name__)


class WireCapture(IWireCapture):
    """File-based wire-level capture implementation.

    Writes human-readable separators and raw payloads to a configured file.
    No-ops when the capture file is not configured.
    """

    def __new__(cls, *args, **kwargs):
        """Create instance and initialize locks."""
        instance = super().__new__(cls)
        # Initialize locks at instance creation time so they exist even if __init__ is not called
        import threading

        instance._thread_lock = threading.Lock()
        instance._cache_lock = threading.Lock()
        return instance

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._lock = asyncio.Lock()
        # Thread lock for synchronous operations
        import threading

        self._thread_lock = threading.Lock()
        self._cache_lock = threading.Lock()  # Lock for cache operations
        self._file_path: str | None = getattr(config.logging, "capture_file", None)
        # Rotation/truncation options
        self._max_bytes: int | None = getattr(config.logging, "capture_max_bytes", None)
        self._truncate_bytes: int | None = getattr(
            config.logging, "capture_truncate_bytes", None
        )
        self._max_files: int = max(
            0, int(getattr(config.logging, "capture_max_files", 0) or 0)
        )
        self._rotate_interval: int = int(
            getattr(config.logging, "capture_rotate_interval_seconds", 0) or 0
        )
        self._total_cap: int = int(
            getattr(config.logging, "capture_total_max_bytes", 0) or 0
        )
        self._last_rotation_ts: float = time.time()
        # PERFORMANCE OPTIMIZATION: Cache total size to avoid expensive file scanning on every write
        self._cached_total_size: int = 0
        self._size_cache_valid: bool = False

        # Ensure directory exists if configured
        if self._file_path:
            try:
                Path(os.path.dirname(self._file_path) or ".").mkdir(
                    parents=True, exist_ok=True
                )
            except OSError as e:
                # Best-effort; if we cannot create the directory, leave disabled
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Failed to create wire capture directory for %s: %s",
                        self._file_path,
                        e,
                        exc_info=True,
                    )
                self._file_path = None

    def enabled(self) -> bool:
        return bool(self._file_path)

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
        # Extract model from payload
        model = "N/A"
        if hasattr(request_payload, "model"):
            model = str(request_payload.model)

        payload_to_dump: Any
        if raw_body:
            preview_len = min(len(raw_body), 4096)
            preview_bytes = raw_body[:preview_len]
            payload_to_dump = {
                "raw": {
                    "length": len(raw_body),
                    "preview": preview_bytes.decode("utf-8", errors="replace"),
                    "truncated": len(raw_body) > preview_len,
                },
                "parsed": request_payload,
            }
        else:
            payload_to_dump = request_payload

        header = self._format_header(
            direction="INBOUND_REQUEST",
            context=context,
            session_id=session_id,
            backend="client",
            model=model,
            key_name=None,
        )
        body = _safe_json_dump(payload_to_dump)
        await self._append(f"{header}\n{body}\n")

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
        if not self.enabled():
            return
        header = self._format_header(
            direction="REQUEST",
            context=context,
            session_id=session_id,
            backend=backend,
            model=model,
            key_name=key_name,
        )
        body = _safe_json_dump(request_payload)
        await self._append(f"{header}\n{body}\n")

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
        if not self.enabled():
            return
        header = self._format_header(
            direction="REPLY",
            context=context,
            session_id=session_id,
            backend=backend,
            model=model,
            key_name=key_name,
        )
        body = _safe_json_dump(response_content)
        await self._append(f"{header}\n{body}\n")

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
        """Capture the response leaving the proxy toward the client."""
        if not self.enabled():
            return
        header = self._format_header(
            direction="REPLY-TO-CLIENT",
            context=context,
            session_id=session_id,
            backend=backend or "proxy",
            model=model or "unknown",
            key_name=key_name,
        )
        body = _safe_json_dump(response_content)
        await self._append(f"{header}\n{body}\n")

    async def capture_stream_completion(
        self,
        *,
        context: RequestContext | None,
        session_id: str | None,
        backend: str,
        model: str,
        key_name: str | None,
        canonical_usage: CanonicalUsageRecord | None = None,
        eos_metadata: dict[str, JsonValue] | None = None,
        capture_metadata: dict[str, JsonValue] | None = None,
    ) -> None:
        """Capture canonical usage for completed streaming response."""
        # Allow EoS metadata even without canonical_usage
        if not self.enabled() or (canonical_usage is None and eos_metadata is None):
            return

        # Convert CanonicalUsageRecord to dict for JSON serialization
        canonical_usage_dict = canonical_usage.model_dump() if canonical_usage else None

        # For legacy wire capture, append canonical_usage and/or EoS metadata as a separate entry
        header = self._format_header(
            direction="STREAM_COMPLETION",
            context=context,
            session_id=session_id,
            backend=backend,
            model=model,
            key_name=key_name,
        )
        body_dict: dict[str, JsonValue] = {}
        if canonical_usage_dict:
            body_dict["canonical_usage"] = canonical_usage_dict
        if eos_metadata:
            body_dict["eos_metadata"] = eos_metadata
        body = _safe_json_dump(body_dict)
        await self._append(f"{header}\n{body}\n")

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
        if not self.enabled():
            return stream

        async def _gen() -> AsyncIterator[bytes]:
            # Write a header once, then tee all bytes
            header = self._format_header(
                direction="REPLY-STREAM",
                context=context,
                session_id=session_id,
                backend=backend,
                model=model,
                key_name=key_name,
            )
            await self._append(f"{header}\n")
            async for chunk in stream:
                # Append chunk as-is (bytes) with a small prefix for readability
                text = chunk.decode("utf-8", errors="replace")
                # Optional truncation for capture file only (stream to client is not modified)
                if self._truncate_bytes and self._truncate_bytes > 0:
                    enc = text.encode("utf-8")
                    if len(enc) > self._truncate_bytes:
                        enc = enc[: self._truncate_bytes]
                        text = enc.decode("utf-8", errors="ignore") + " [[truncated]]"
                try:
                    await self._append(text)
                except OSError as e:
                    # Log I/O failures but do not impact the stream to client
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning(
                            "Wire capture append failed: %s", e, exc_info=True
                        )
                yield chunk
            await self._append("\n")

        return _gen()

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
        if not self.enabled():
            return stream

        async def _gen() -> AsyncIterator[bytes]:
            header = self._format_header(
                direction="REPLY-STREAM-TO-CLIENT",
                context=context,
                session_id=session_id,
                backend=backend or "proxy",
                model=model or "unknown",
                key_name=key_name,
            )
            await self._append(f"{header}\n")
            async for chunk in stream:
                text = chunk.decode("utf-8", errors="replace")
                try:
                    await self._append(text)
                except OSError as e:
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning(
                            "Wire capture outbound append failed: %s", e, exc_info=True
                        )
                yield chunk
            await self._append("\n")

        return _gen()

    def _format_header(
        self,
        *,
        direction: str,
        context: RequestContext | None,
        session_id: str | None,
        backend: str,
        model: str,
        key_name: str | None,
    ) -> str:
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds") + "Z"
        client = getattr(context, "client_host", None) if context else None
        agent = getattr(context, "agent", None) if context else None
        who = f"client={client or 'unknown'}" + (f" agent={agent}" if agent else "")
        sid = f" session={session_id}" if session_id else ""
        key = f" key={key_name}" if key_name else ""
        return (
            f"----- {direction} {ts} -----\n"
            f"{who}{sid} -> backend={backend} model={model}{key}"
        )

    async def _append(self, text: str) -> None:
        # Best-effort append with a lock to serialize writes
        if not self._file_path:
            return

        # PERFORMANCE OPTIMIZATION: Calculate incoming size once for both size checking and cap enforcement
        incoming_size = len(text.encode("utf-8"))

        # Perform I/O operations outside async lock to avoid blocking event loop
        # and potential deadlocks. The lock protects the critical section:
        # - actual file write
        # - total cap enforcement (which mutates shared cached state)
        # All other async I/O (to_thread) is done before acquiring the lock

        # Rotation: if size exceeds max, perform multi-level rotation
        # Also rotate based on elapsed time if configured
        if await self._should_rotate_time_async():
            await self._perform_rotation_async()
        if self._max_bytes and self._max_bytes > 0:
            try:
                current_size = (
                    await asyncio.to_thread(os.path.getsize, self._file_path)
                    if await asyncio.to_thread(os.path.exists, self._file_path)
                    else 0
                )
                if current_size + incoming_size > self._max_bytes:
                    await self._perform_rotation_async()
            except OSError as e:
                # Log rotation errors but do not propagate
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Error during wire capture rotation: %s", e, exc_info=True
                    )

        # Now acquire lock only for the write and total cap enforcement
        async with self._lock:
            try:
                await asyncio.to_thread(self._write_to_file, self._file_path, text)
            except OSError as e:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning("Wire capture write failed: %s", e, exc_info=True)
                return
            # Enforce total cap best-effort
            await self._enforce_total_cap_async(incoming_size)

    async def _should_rotate_time_async(self) -> bool:
        """Async version of _should_rotate_time using asyncio.to_thread for I/O operations."""
        return await asyncio.to_thread(self._should_rotate_time)

    def _should_rotate_time(self) -> bool:
        if not self._file_path or self._rotate_interval < 0:
            return False
        # If rotate_interval is 0, always rotate (immediate rotation)
        if self._rotate_interval == 0:
            return True
        try:
            if not os.path.exists(self._file_path):
                return False
            now = time.time()
            return (now - self._last_rotation_ts) >= self._rotate_interval
        except OSError:
            return False

    async def _perform_rotation_async(self) -> None:
        """Async version of _perform_rotation using asyncio.to_thread for I/O operations."""
        await asyncio.to_thread(self._perform_rotation)

    def _perform_rotation(self) -> None:
        """Synchronous version of rotation (kept for backward compatibility)."""
        if not self._file_path:
            return
        try:
            # Multi-level rotation if configured
            if self._max_files and self._max_files > 0:
                for i in range(self._max_files, 0, -1):
                    src = f"{self._file_path}.{i}"
                    dst = f"{self._file_path}.{i+1}"
                    if os.path.exists(src):
                        with contextlib.suppress(OSError):
                            if i == self._max_files:
                                os.remove(src)
                            else:
                                os.replace(src, dst)
            with contextlib.suppress(OSError):
                if os.path.exists(self._file_path):
                    os.replace(self._file_path, f"{self._file_path}.1")
            self._last_rotation_ts = time.time()
            # PERFORMANCE OPTIMIZATION: Invalidate size cache after rotation
            self._size_cache_valid = False
        except OSError as e:
            # Ignore rotation failures
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Error during wire capture rotation: %s", e, exc_info=True
                )

    async def _enforce_total_cap_async(self, incoming_size: int = 0) -> None:
        """Optimized version that uses cached size to avoid expensive file scanning."""
        if not self._file_path or not self._total_cap or self._total_cap <= 0:
            return

        # PERFORMANCE OPTIMIZATION: Use cached size and update incrementally
        # Only recalculate from disk when cache is invalid
        if not self._size_cache_valid:
            await asyncio.to_thread(self._recalculate_total_size)

        # Update cached size with incoming data
        self._cached_total_size += incoming_size

        # Only enforce if we're over the cap
        if self._cached_total_size <= self._total_cap:
            return

        # We need to clean up files - use the slow path
        await asyncio.to_thread(self._enforce_total_cap)

    def _recalculate_total_size(self) -> None:
        """Recalculate total size from disk and update cache."""
        if not self._file_path:
            self._cached_total_size = 0
            self._size_cache_valid = True
            return

        try:
            total = 0
            base = self._file_path
            if os.path.exists(base):
                with contextlib.suppress(OSError):
                    total += os.path.getsize(base)

            # Include rotated files up to some reasonable bound
            max_scan = max(self._max_files or 0, 10)
            for i in range(1, max_scan + 1):
                p = f"{base}.{i}"
                if os.path.exists(p):
                    with contextlib.suppress(OSError):
                        total += os.path.getsize(p)

            self._cached_total_size = total
            self._size_cache_valid = True
        except OSError as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Error recalculating wire capture total size: %s", e, exc_info=True
                )
            self._cached_total_size = 0
            self._size_cache_valid = False

    def _enforce_total_cap(self) -> None:
        if not self._file_path or not self._total_cap or self._total_cap <= 0:
            return
        try:
            files: list[tuple[str, int]] = []
            base = self._file_path
            if os.path.exists(base):
                with contextlib.suppress(OSError):
                    files.append((base, os.path.getsize(base)))
            # Include rotated files up to some reasonable bound (max_files + 10 as safety)
            max_scan = max(self._max_files or 0, 10)
            for i in range(1, max_scan + 1):
                p = f"{base}.{i}"
                if os.path.exists(p):
                    with contextlib.suppress(OSError):
                        files.append((p, os.path.getsize(p)))
            total = sum(sz for _, sz in files)
            if total <= self._total_cap:
                # PERFORMANCE OPTIMIZATION: Update cache with actual total
                self._cached_total_size = total
                self._size_cache_valid = True
                return
            # Remove oldest rotated files first (highest index), then proceed downward
            for i in range(max_scan, 0, -1):
                p = f"{base}.{i}"
                if os.path.exists(p):
                    with contextlib.suppress(OSError):
                        sz = os.path.getsize(p)
                        os.remove(p)
                        total -= sz
                    if total <= self._total_cap:
                        # PERFORMANCE OPTIMIZATION: Update cache after cleanup
                        self._cached_total_size = total
                        self._size_cache_valid = True
                        return
            # If still exceeding with only base file left, remove it entirely
            if os.path.exists(base):
                with contextlib.suppress(OSError):
                    os.remove(base)
                    self._cached_total_size = 0
                    self._size_cache_valid = True
        except OSError as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Error enforcing total cap on wire capture logs: %s",
                    e,
                    exc_info=True,
                )
            # Invalidate cache on error
            self._size_cache_valid = False

    @staticmethod
    def _write_to_file(file_path: str, text: str) -> None:
        """Helper method to write text to file synchronously."""
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(text)

    async def shutdown(self) -> None:
        """No background tasks; nothing to do for classic capture."""
        return None


def _safe_json_dump(obj: Any) -> str:
    """Safely convert object to JSON string with deterministic key ordering.

    Uses deterministic serialization (sorted keys) to ensure consistent output
    for diff-based debugging and replay workflows (Requirement 7.3).
    """
    try:
        # Use sort_keys=True for deterministic output (Requirement 7.3)
        return json.dumps(obj, sort_keys=True, ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        try:
            if hasattr(obj, "model_dump"):
                # Use model_dump_json() to avoid creating intermediate dict (performance optimization)
                if hasattr(obj, "model_dump_json"):
                    # model_dump_json() doesn't support sort_keys, so we need to parse and re-serialize
                    json_str = obj.model_dump_json(indent=2)  # type: ignore[attr-defined, no-any-return]
                    # Parse and re-serialize with sorted keys for determinism
                    parsed = json.loads(json_str)
                    return json.dumps(
                        parsed, sort_keys=True, ensure_ascii=False, indent=2
                    )
                # Use model_dump() and serialize with sorted keys
                data = obj.model_dump()  # type: ignore[attr-defined]
                return json.dumps(data, sort_keys=True, ensure_ascii=False, indent=2)
            # Use __dict__ and serialize with sorted keys
            return json.dumps(
                obj.__dict__, sort_keys=True, ensure_ascii=False, indent=2
            )
        except (TypeError, ValueError, AttributeError) as e:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Falling back to str() during JSON dump: %s", e, exc_info=True
                )
            return str(obj)
