from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import time
from collections.abc import AsyncIterator, Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.core.common.logging_utils import discover_api_keys_from_config_and_env
from src.core.common.structlog_config import get_logger
from src.core.config.app_config import AppConfig
from src.core.domain.request_context import RequestContext
from src.core.domain.usage_canonical_record import CanonicalUsageRecord
from src.core.domain.wire_capture import create_wire_capture_entry
from src.core.interfaces.wire_capture_interface import IWireCapture
from src.core.services.redaction_middleware import APIKeyRedactor

logger = get_logger(__name__)

MAX_REDACTION_DEPTH = 100
REDACTION_DEPTH_PLACEHOLDER = "(redaction-depth-exceeded)"


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

        # Initialize redaction for wire capture data
        api_keys = discover_api_keys_from_config_and_env(config)
        self._redactor = APIKeyRedactor(api_keys)
        self._raw_preview_limit: int = 4096

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

        # Extract model from payload
        model = "N/A"
        if hasattr(request_payload, "model"):
            model = str(request_payload.model)

        normalized_payload = self._normalize_payload(request_payload)
        payload: Any
        if raw_body:
            payload = {
                "raw": self._summarize_raw_body(raw_body),
                "parsed": normalized_payload,
            }
        else:
            payload = normalized_payload

        # Create structured JSON entry
        entry = self._create_json_entry(
            flow="client_to_proxy",
            direction="request",
            context=context,
            session_id=session_id,
            backend="client",
            model=model,
            key_name=None,
            payload=payload,
        )

        # Serialize and write to file
        await self._append_json(entry)

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
        canonical_usage: dict[str, Any] | None = None,
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

        # Add canonical usage to metadata if present
        if canonical_usage is not None and isinstance(entry, dict):
            if "metadata" not in entry:
                entry["metadata"] = {}
            entry["metadata"]["canonical_usage"] = canonical_usage

        # Serialize and write to file
        await self._append_json(entry)

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
        """Capture the response being sent to the client."""
        if not self.enabled():
            return

        entry = self._create_json_entry(
            flow="backend_to_frontend",
            direction="response",
            context=context,
            session_id=session_id,
            backend=backend or "proxy",
            model=model or "unknown",
            key_name=key_name,
            payload=response_content,
        )

        # Mark as outbound for clarity without changing schema
        if isinstance(entry, dict):
            entry.setdefault("metadata", {})["stage"] = "outbound"

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

            # Track total bytes without storing all chunks to avoid memory growth
            total_bytes = 0

            # Process stream chunks
            async for chunk in stream:
                chunk_length = len(chunk)
                total_bytes += chunk_length

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
                    byte_count=chunk_length,
                )
                try:
                    await self._append_json(chunk_entry)
                except Exception as e:
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Error capturing stream chunk: %s", e, exc_info=True
                        )

                yield chunk

            # End of stream marker
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

    async def capture_stream_completion(
        self,
        *,
        context: RequestContext | None,
        session_id: str | None,
        backend: str,
        model: str,
        key_name: str | None,
        canonical_usage: CanonicalUsageRecord | None = None,
    ) -> None:
        """Capture canonical usage for completed streaming response."""
        if not self.enabled() or canonical_usage is None:
            return

        # Convert CanonicalUsageRecord to dict for metadata
        canonical_usage_dict = canonical_usage.model_dump() if canonical_usage else None

        # Create completion entry with canonical_usage
        entry = self._create_json_entry(
            flow="backend_to_frontend",
            direction="response_stream_completion",
            context=context,
            session_id=session_id,
            backend=backend,
            model=model,
            key_name=key_name,
            payload={},
        )

        # Add canonical usage to metadata
        if isinstance(entry, dict):
            if "metadata" not in entry:
                entry["metadata"] = {}
            entry["metadata"]["canonical_usage"] = canonical_usage_dict

        await self._append_json(entry)

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
        if not self.enabled():
            return stream

        async def _gen() -> AsyncIterator[bytes]:
            header_entry = self._create_json_entry(
                flow="backend_to_frontend",
                direction="response_stream_start",
                context=context,
                session_id=session_id,
                backend=backend or "proxy",
                model=model or "unknown",
                key_name=key_name,
                payload={},
            )
            if isinstance(header_entry, dict):
                header_entry.setdefault("metadata", {})["stage"] = "outbound"
            await self._append_json(header_entry)

            total_bytes = 0
            chunk_index = 0

            async for chunk in stream:
                chunk_index += 1
                chunk_len = len(chunk)
                total_bytes += chunk_len
                text = chunk.decode("utf-8", errors="replace")
                chunk_entry = self._create_json_entry(
                    flow="backend_to_frontend",
                    direction="response_stream_chunk",
                    context=context,
                    session_id=session_id,
                    backend=backend or "proxy",
                    model=model or "unknown",
                    key_name=key_name,
                    payload=text,
                    byte_count=chunk_len,
                )
                if isinstance(chunk_entry, dict):
                    chunk_entry.setdefault("metadata", {}).update(
                        {"stage": "outbound", "chunk_number": chunk_index}
                    )
                try:
                    await self._append_json(chunk_entry)
                except Exception as e:
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Error capturing outbound stream chunk: %s",
                            e,
                            exc_info=True,
                        )
                yield chunk

            end_entry = self._create_json_entry(
                flow="backend_to_frontend",
                direction="response_stream_end",
                context=context,
                session_id=session_id,
                backend=backend or "proxy",
                model=model or "unknown",
                key_name=key_name,
                payload={},
                byte_count=total_bytes,
            )
            if isinstance(end_entry, dict):
                end_entry.setdefault("metadata", {}).update(
                    {"stage": "outbound", "total_chunks": chunk_index}
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
        utc_now = datetime.now(timezone.utc)
        utc_now.isoformat(timespec="milliseconds") + "Z"

        # Use local time for human-readable timestamp (based on system timezone)
        local_time = datetime.now()
        local_time.strftime("%Y-%m-%d %H:%M:%S")

        # Extract source and destination info
        getattr(context, "client_host", None) if context else None
        getattr(context, "agent", None) if context else None

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

        # Create entry using Pydantic models
        entry = create_wire_capture_entry(
            flow=flow,
            direction=direction,
            context=context,
            session_id=session_id,
            backend=backend,
            model=model,
            key_name=key_name,
            payload=self._redact_payload(payload),
            byte_count=byte_count,
        )

        # Extract and include system prompts if present
        system_prompt = self._extract_system_prompt(payload)
        if system_prompt:
            entry_dict = entry.model_dump()
            entry_dict["metadata"]["system_prompt"] = system_prompt
            return entry_dict

        return entry.model_dump()

    def _summarize_raw_body(self, raw_body: bytes) -> dict[str, Any]:
        preview_len = min(len(raw_body), self._raw_preview_limit)
        preview_bytes = raw_body[:preview_len]
        return {
            "length": len(raw_body),
            "preview": preview_bytes.decode("utf-8", errors="replace"),
            "truncated": len(raw_body) > preview_len,
        }

    @staticmethod
    def _normalize_payload(payload: Any) -> Any:
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
        """Redact sensitive information while guarding against malicious nesting."""

        return _redact_payload_with_depth_limit(
            payload, redact_str=self._redactor.redact
        )

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
            if logger.isEnabledFor(logging.DEBUG):
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
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "JSON serialization failed for structured capture: %s",
                    e,
                    exc_info=True,
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

    async def shutdown(self) -> None:
        """No background tasks; nothing to clean up for structured capture."""
        return None


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
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Falling back to str() during structured JSON dump: %s",
                    e,
                    exc_info=True,
                )
            return str(obj)


def _redact_payload_with_depth_limit(
    value: Any,
    *,
    redact_str: Callable[[str], str],
    depth: int = 0,
) -> Any:
    """Redact nested payloads without exceeding Python's recursion limit."""

    if depth >= MAX_REDACTION_DEPTH:
        logger.warning(
            "Maximum payload redaction depth (%d) exceeded; truncating nested structure",
            MAX_REDACTION_DEPTH,
        )
        return REDACTION_DEPTH_PLACEHOLDER

    if isinstance(value, dict):
        return {
            key: _redact_payload_with_depth_limit(
                item, redact_str=redact_str, depth=depth + 1
            )
            for key, item in value.items()
        }

    if isinstance(value, list):
        return [
            _redact_payload_with_depth_limit(
                item, redact_str=redact_str, depth=depth + 1
            )
            for item in value
        ]

    if isinstance(value, tuple):
        return tuple(
            _redact_payload_with_depth_limit(
                item, redact_str=redact_str, depth=depth + 1
            )
            for item in value
        )

    if isinstance(value, str):
        return redact_str(value)

    return value
