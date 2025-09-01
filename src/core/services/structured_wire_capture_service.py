from __future__ import annotations

import asyncio
import contextlib
import json
import os
import time
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from typing import Any

from src.core.common.logging import get_logger
from src.core.config.app_config import AppConfig
from src.core.domain.request_context import RequestContext
from src.core.interfaces.wire_capture_interface import IWireCapture

logger = get_logger(__name__)


class StructuredWireCapture(IWireCapture):
    """JSON-based structured wire-level capture implementation.

    Writes structured JSON entries for all communications passing through the proxy.
    Each entry has clear identification of source, destination, timestamp, and payload.
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
                    "Failed to create structured capture directory for %s: %s",
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

        # Create structured JSON entry
        entry = self._create_json_entry(
            flow="frontend_to_backend",
            direction="request",
            context=context,
            session_id=session_id,
            backend=backend,
            model=model,
            key_name=key_name,
            payload=request_payload,
        )

        # Serialize and write to file
        await self._append_json(entry)

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

        # Create structured JSON entry
        entry = self._create_json_entry(
            flow="backend_to_frontend",
            direction="response",
            context=context,
            session_id=session_id,
            backend=backend,
            model=model,
            key_name=key_name,
            payload=response_content,
        )

        # Serialize and write to file
        await self._append_json(entry)

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
            # Write a header entry for the stream
            header_entry = self._create_json_entry(
                flow="backend_to_frontend",
                direction="response_stream_start",
                context=context,
                session_id=session_id,
                backend=backend,
                model=model,
                key_name=key_name,
                payload={},
            )
            await self._append_json(header_entry)

            # Track accumulated chunks for byte count
            all_chunks = []

            # Process stream chunks
            async for chunk in stream:
                all_chunks.append(chunk)

                # Capture each chunk
                text = chunk.decode("utf-8", errors="replace")
                chunk_entry = self._create_json_entry(
                    flow="backend_to_frontend",
                    direction="response_stream_chunk",
                    context=context,
                    session_id=session_id,
                    backend=backend,
                    model=model,
                    key_name=key_name,
                    payload=text,
                    byte_count=len(chunk),
                )
                try:
                    await self._append_json(chunk_entry)
                except Exception as e:
                    logger.debug("Error capturing stream chunk: %s", e, exc_info=True)

                yield chunk

            # End of stream marker
            total_bytes = sum(len(chunk) for chunk in all_chunks)
            end_entry = self._create_json_entry(
                flow="backend_to_frontend",
                direction="response_stream_end",
                context=context,
                session_id=session_id,
                backend=backend,
                model=model,
                key_name=key_name,
                payload={},
                byte_count=total_bytes,
            )
            await self._append_json(end_entry)

        return _gen()

    def _create_json_entry(
        self,
        *,
        flow: str,
        direction: str,
        context: RequestContext | None,
        session_id: str | None,
        backend: str,
        model: str,
        key_name: str | None,
        payload: Any,
        byte_count: int | None = None,
    ) -> dict[str, Any]:
        """Create a structured JSON entry with all required fields."""
        # Get timestamp in both ISO and human-readable formats
        utc_now = datetime.utcnow()
        iso_timestamp = utc_now.isoformat(timespec="milliseconds") + "Z"

        # Use local time for human-readable timestamp (based on system timezone)
        local_time = datetime.now()
        human_timestamp = local_time.strftime("%Y-%m-%d %H:%M:%S")

        # Extract source and destination info
        client_host = getattr(context, "client_host", None) if context else None
        agent = getattr(context, "agent", None) if context else None

        # Calculate byte count if not provided
        if byte_count is None:
            try:
                if isinstance(payload, str):
                    byte_count = len(payload.encode("utf-8"))
                elif isinstance(payload, bytes):
                    byte_count = len(payload)
                else:
                    payload_str = _safe_json_dump(payload)
                    byte_count = len(payload_str.encode("utf-8"))
            except Exception:
                byte_count = -1

        # Create the standard entry structure
        entry = {
            "timestamp": {
                "iso": iso_timestamp,
                "human_readable": human_timestamp,
            },
            "communication": {
                "flow": flow,
                "direction": direction,
                "source": (
                    client_host or "unknown"
                    if flow == "frontend_to_backend"
                    else backend
                ),
                "destination": (
                    backend
                    if flow == "frontend_to_backend"
                    else client_host or "unknown"
                ),
            },
            "metadata": {
                "session_id": session_id,
                "agent": agent,
                "backend": backend,
                "model": model,
                "key_name": key_name,
                "byte_count": byte_count,
            },
            "payload": payload,
        }

        # Extract and include system prompts if present
        system_prompt = self._extract_system_prompt(payload)
        if system_prompt:
            entry["metadata"]["system_prompt"] = system_prompt

        return entry

    def _extract_system_prompt(self, payload: Any) -> str | None:
        """Extract system prompt from payload if present."""
        try:
            # Handle OpenAI format
            if isinstance(payload, dict) and "messages" in payload:
                for message in payload["messages"]:
                    if isinstance(message, dict) and message.get("role") == "system":
                        return message.get("content")

            # Handle Anthropic format
            if isinstance(payload, dict) and "system" in payload:
                return str(payload["system"])

            # Handle Google/Gemini format
            if isinstance(payload, dict) and "contents" in payload:
                for content in payload["contents"]:
                    if isinstance(content, dict) and content.get("role") == "system":
                        return str(content.get("parts", [{}])[0].get("text", ""))
        except Exception as e:
            logger.debug("Failed to extract system prompt: %s", e, exc_info=True)

        return None

    async def _append_json(self, entry: dict[str, Any]) -> None:
        """Write a JSON entry to the capture file."""
        # Best-effort append with a lock to serialize writes
        if not self._file_path:
            return

        try:
            # Convert entry to JSON string
            json_str = json.dumps(entry, ensure_ascii=False) + "\n"
        except (TypeError, ValueError) as e:
            logger.debug(
                "JSON serialization failed for structured capture: %s", e, exc_info=True
            )
            try:
                json_str = (
                    json.dumps({"fallback_entry": str(entry)}, ensure_ascii=False)
                    + "\n"
                )
            except Exception:
                return

        async with self._lock:
            # Check if rotation needed
            if self._should_rotate_time():
                self._perform_rotation()

            if self._max_bytes and self._max_bytes > 0:
                try:
                    current_size = (
                        os.path.getsize(self._file_path)
                        if os.path.exists(self._file_path)
                        else 0
                    )
                    incoming_size = len(json_str.encode("utf-8"))
                    if current_size + incoming_size > self._max_bytes:
                        self._perform_rotation()
                except OSError as e:
                    logger.warning(
                        "Error during structured wire capture rotation: %s",
                        e,
                        exc_info=True,
                    )

            try:
                with open(self._file_path, "a", encoding="utf-8") as f:
                    f.write(json_str)
            except OSError as e:
                logger.warning(
                    "Structured wire capture write failed: %s", e, exc_info=True
                )
                return

            self._enforce_total_cap()

    def _should_rotate_time(self) -> bool:
        if not self._file_path:
            return False
        # Treat non-positive values (0 or negative) as: no time-based rotation
        if self._rotate_interval <= 0:
            return False
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
            logger.warning(
                "Error during structured wire capture rotation: %s", e, exc_info=True
            )

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
            logger.warning(
                "Error enforcing total cap on structured wire capture logs: %s",
                e,
                exc_info=True,
            )


def _safe_json_dump(obj: Any) -> str:
    """Safely convert object to JSON string."""
    try:
        return json.dumps(obj, ensure_ascii=False)
    except (TypeError, ValueError):
        try:
            if hasattr(obj, "model_dump"):
                return json.dumps(obj.model_dump(), ensure_ascii=False)  # type: ignore[attr-defined]
            return json.dumps(obj.__dict__, ensure_ascii=False)
        except Exception as e:
            logger.debug(
                "Falling back to str() during structured JSON dump: %s",
                e,
                exc_info=True,
            )
            return str(obj)
