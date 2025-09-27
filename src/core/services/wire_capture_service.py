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

from src.core.config.app_config import AppConfig
from src.core.domain.request_context import RequestContext
from src.core.interfaces.wire_capture_interface import IWireCapture

logger = logging.getLogger(__name__)


class WireCapture(IWireCapture):
    """File-based wire-level capture implementation.

    Writes human-readable separators and raw payloads to a configured file.
    No-ops when the capture file is not configured.
    """

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._lock = asyncio.Lock()
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

        # Ensure directory exists if configured
        if self._file_path:
            try:
                Path(os.path.dirname(self._file_path) or ".").mkdir(
                    parents=True, exist_ok=True
                )
            except OSError as e:
                # Best-effort; if we cannot create the directory, leave disabled
                logger.warning(
                    "Failed to create wire capture directory for %s: %s",
                    self._file_path,
                    e,
                    exc_info=True,
                )
                self._file_path = None

    def enabled(self) -> bool:
        return bool(self._file_path)

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
        response_content: Any,
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
                    logger.warning("Wire capture append failed: %s", e, exc_info=True)
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
        async with self._lock:
            # Rotation: if size exceeds max, perform multi-level rotation
            # Also rotate based on elapsed time if configured
            if self._should_rotate_time():
                self._perform_rotation()
            if self._max_bytes and self._max_bytes > 0:
                try:
                    current_size = (
                        os.path.getsize(self._file_path)
                        if os.path.exists(self._file_path)
                        else 0
                    )
                    incoming_size = len(text.encode("utf-8"))
                    if current_size + incoming_size > self._max_bytes:
                        self._perform_rotation()
                except OSError as e:
                    # Log rotation errors but do not propagate
                    logger.warning(
                        "Error during wire capture rotation: %s", e, exc_info=True
                    )
            try:
                with open(self._file_path, "a", encoding="utf-8") as f:
                    f.write(text)
            except OSError as e:
                logger.warning("Wire capture write failed: %s", e, exc_info=True)
                return
            # Enforce total cap best-effort
            self._enforce_total_cap()

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

    def _perform_rotation(self) -> None:
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
        except OSError as e:
            # Ignore rotation failures
            logger.warning("Error during wire capture rotation: %s", e)

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
                        return
            # If still exceeding with only base file left, remove it entirely
            if os.path.exists(base):
                with contextlib.suppress(OSError):
                    os.remove(base)
        except OSError as e:
            logger.warning("Error enforcing total cap on wire capture logs: %s", e)

    async def shutdown(self) -> None:
        """No background tasks; nothing to do for classic capture."""
        return None


def _safe_json_dump(obj: Any) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        try:
            if hasattr(obj, "model_dump"):
                return json.dumps(obj.model_dump(), ensure_ascii=False, indent=2)  # type: ignore[attr-defined]
            return json.dumps(obj.__dict__, ensure_ascii=False, indent=2)
        except (TypeError, ValueError, AttributeError) as e:
            logger.debug("Falling back to str() during JSON dump: %s", e, exc_info=True)
            return str(obj)
