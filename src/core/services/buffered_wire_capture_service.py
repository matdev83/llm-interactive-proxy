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
import logging
import os
import time
from collections import defaultdict
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NamedTuple, cast

from pydantic.types import JsonValue

from src.core.common.contract_serialization import serialize_dict_for_capture
from src.core.common.logging_utils import discover_api_keys_from_config_and_env
from src.core.config.app_config import AppConfig
from src.core.domain.request_context import RequestContext
from src.core.domain.usage_canonical_record import CanonicalUsageRecord
from src.core.interfaces.stream_session_id_resolver_interface import (
    IStreamSessionIdResolver,
)
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
    # Preserve dicts and lists for canonical_usage and other structured data
    if isinstance(value, dict | list):
        return value
    try:
        return str(value)
    except (TypeError, ValueError, AttributeError) as e:
        logger.debug(
            "Failed to convert payload to string, using repr: %s, type: %s",
            e,
            type(value).__name__,
            exc_info=True,
        )
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
    sequence: int  # Sequence number to ensure stable ordering
    direction: str  # "outbound_request", "inbound_response", "outbound_response", "stream_start", "stream_chunk", "stream_end", "outbound_stream_*"
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

    def __init__(
        self,
        config: AppConfig,
        stream_session_id_resolver: IStreamSessionIdResolver | None = None,
    ) -> None:
        self._config = config
        logging_cfg = getattr(config, "logging", None)
        raw_file_path = (
            getattr(logging_cfg, "capture_file", None) if logging_cfg else None
        )
        self._file_path: str | None = _coerce_path(raw_file_path)

        # Stream session ID resolver - create default if not provided
        if stream_session_id_resolver is None:
            from src.core.services.stream_session_id_resolver import (
                StreamSessionIdResolver,
            )

            self._stream_session_id_resolver: IStreamSessionIdResolver = (
                StreamSessionIdResolver()
            )
        else:
            self._stream_session_id_resolver = stream_session_id_resolver

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
        self._buffers: dict[str, list[WireCaptureEntry]] = defaultdict(list)
        self._buffer_lock = asyncio.Lock()
        self._flush_task: asyncio.Task[None] | None = None
        self._last_flush_time: float = time.time()
        self._total_bytes_written: int = 0
        self._enabled: bool = False
        self._sequence_counter: int = 0  # Monotonic sequence for stable ordering

        # Memory leak prevention: limit number of buffer keys to prevent unbounded growth
        # when many unique session_ids are created but flushes don't occur frequently
        self._max_buffer_keys: int = 1000  # Maximum number of unique session buffers

        # PERFORMANCE OPTIMIZATION: Cache content length to avoid repeated JSON serialization
        self._content_length_cache: dict[int, int] = {}
        self._cache_max_size: int = 1000  # Limit cache size to prevent memory leaks

        # Initialize redaction for wire capture data
        api_keys = discover_api_keys_from_config_and_env(config)
        self._redactor = APIKeyRedactor(api_keys)
        self._raw_preview_limit: int = 4096

        # Initialize if configured
        if self._file_path:
            self._initialize()

    def _initialize(self) -> None:
        """Initialize the wire capture system."""
        if not self._file_path:
            return

        try:
            # Ensure directory exists
            Path(self._file_path).parent.mkdir(parents=True, exist_ok=True)

            # Test write access and write format header
            self._sequence_counter += 1
            test_entry = WireCaptureEntry(
                timestamp_iso=datetime.now(timezone.utc).isoformat(),
                timestamp_unix=time.time(),
                sequence=self._sequence_counter,
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
                self._flush_task = None

        except OSError as e:
            logger.warning(
                "Wire capture initialization failed due to OS error, disabling: %s",
                e,
                exc_info=True,
            )
            self._enabled = False
            if self._flush_task:
                self._flush_task.cancel()
        except Exception as e:
            logger.error(
                "Wire capture initialization failed unexpectedly, disabling: %s",
                e,
                exc_info=True,
            )
            self._enabled = False
            if self._flush_task:
                self._flush_task.cancel()

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
            try:
                # Use deterministic serialization for consistent byte count (Requirement 7.3)
                from src.core.common.contract_serialization import (
                    serialize_dict_for_capture,
                )

                if isinstance(payload, dict):
                    content_length = len(serialize_dict_for_capture(payload))
                else:
                    # For lists, use serialize_for_capture which handles lists deterministically
                    from src.core.common.contract_serialization import (
                        serialize_for_capture,
                    )

                    content_length = len(serialize_for_capture(payload))
            except (TypeError, ValueError):
                content_length = len(str(payload).encode("utf-8"))
        elif isinstance(payload, str):
            content_length = len(payload.encode("utf-8"))
        elif isinstance(payload, bytes):
            content_length = len(payload)
        else:
            content_length = len(str(payload).encode("utf-8"))

        # Maintain cache size limit - evict BEFORE adding to prevent temporary overflow
        # Remove oldest entries if at capacity (evict enough to make room for new entry)
        while len(self._content_length_cache) >= self._cache_max_size:
            oldest_key = next(iter(self._content_length_cache))
            del self._content_length_cache[oldest_key]

        self._content_length_cache[payload_id] = content_length
        return content_length

    def _serialize_entry_cached(self, entry: WireCaptureEntry) -> str:
        """Serialize entry to JSON with deterministic key ordering."""
        # Use deterministic serialization with sorted keys
        entry_dict = entry._asdict()
        json_bytes = serialize_dict_for_capture(entry_dict)
        return json_bytes.decode("utf-8")

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

        entry = await self._create_entry(
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

        entry = await self._create_entry(
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
        response_content: dict[str, JsonValue] | bytes | None,
        canonical_usage: CanonicalUsageRecord | None = None,
    ) -> None:
        """Capture inbound response from backend."""
        if not self.enabled():
            return
        # Ensure background task runs in async contexts
        self._maybe_start_flush_task()

        # Convert CanonicalUsageRecord to dict for metadata
        metadata: dict[str, JsonValue] = {}
        if canonical_usage is not None:
            metadata["canonical_usage"] = canonical_usage.model_dump()

        entry = await self._create_entry(
            direction="inbound_response",
            source=backend,
            destination=self._get_client_info(context),
            context=context,
            session_id=session_id,
            backend=backend,
            model=model,
            key_name=key_name,
            payload=response_content,
            metadata=metadata if metadata else None,
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
        """Capture outbound response as it is sent to the client."""
        if not self.enabled():
            return
        self._maybe_start_flush_task()

        entry = await self._create_entry(
            direction="outbound_response",
            source="proxy",
            destination=self._get_client_info(context),
            context=context,
            session_id=session_id,
            backend=backend or "proxy",
            model=model or "unknown",
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
        stream_session_id = self._resolve_stream_session_id(session_id, context)

        async def _capture_stream() -> AsyncIterator[bytes]:
            # Stream start marker
            start_entry = await self._create_entry(
                direction="stream_start",
                source=backend,
                destination=self._get_client_info(context),
                context=context,
                session_id=stream_session_id,
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
                chunk_entry = await self._create_entry(
                    direction="stream_chunk",
                    source=backend,
                    destination=self._get_client_info(context),
                    context=context,
                    session_id=stream_session_id,
                    backend=backend,
                    model=model,
                    key_name=key_name,
                    payload=chunk_text,
                    metadata={"chunk_number": chunk_count, "chunk_bytes": len(chunk)},
                )
                await self._buffer_entry(chunk_entry)

                yield chunk

            # Stream end marker
            end_entry = await self._create_entry(
                direction="stream_end",
                source=backend,
                destination=self._get_client_info(context),
                context=context,
                session_id=stream_session_id,
                backend=backend,
                model=model,
                key_name=key_name,
                payload={"total_bytes": total_bytes, "total_chunks": chunk_count},
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
        eos_metadata: dict[str, JsonValue] | None = None,
    ) -> None:
        """Capture canonical usage for completed streaming response."""
        # Allow EoS metadata even without canonical_usage
        if not self.enabled() or (canonical_usage is None and eos_metadata is None):
            return

        self._maybe_start_flush_task()

        # Resolve session ID
        stream_session_id = self._resolve_stream_session_id(session_id, context)

        # Convert CanonicalUsageRecord to dict for metadata
        canonical_usage_dict = canonical_usage.model_dump() if canonical_usage else None

        # Create completion entry with canonical_usage and/or EoS metadata
        metadata: dict[str, JsonValue] = {}
        if canonical_usage_dict:
            metadata["canonical_usage"] = canonical_usage_dict
        if eos_metadata:
            metadata["eos_metadata"] = eos_metadata
        completion_entry = await self._create_entry(
            direction="stream_completion",
            source=backend,
            destination=self._get_client_info(context),
            context=context,
            session_id=stream_session_id,
            backend=backend,
            model=model,
            key_name=key_name,
            payload={},
            metadata=metadata,
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
        """Wrap streaming bytes flowing from proxy to client."""
        if not self.enabled():
            return _StreamPassthroughWrapper(stream)
        self._maybe_start_flush_task()
        stream_session_id = self._resolve_stream_session_id(session_id, context)

        async def _capture_stream() -> AsyncIterator[bytes]:
            start_entry = await self._create_entry(
                direction="outbound_stream_start",
                source="proxy",
                destination=self._get_client_info(context),
                context=context,
                session_id=stream_session_id,
                backend=backend or "proxy",
                model=model or "unknown",
                key_name=key_name,
                payload={"stream_type": "outbound_response"},
            )
            await self._buffer_entry(start_entry)

            total_bytes = 0
            chunk_count = 0

            async for chunk in stream:
                chunk_count += 1
                total_bytes += len(chunk)
                chunk_text = chunk.decode("utf-8", errors="replace")
                chunk_entry = await self._create_entry(
                    direction="outbound_stream_chunk",
                    source="proxy",
                    destination=self._get_client_info(context),
                    context=context,
                    session_id=stream_session_id,
                    backend=backend or "proxy",
                    model=model or "unknown",
                    key_name=key_name,
                    payload=chunk_text,
                    metadata={
                        "chunk_number": chunk_count,
                        "chunk_bytes": len(chunk),
                        "stream_type": "outbound_response",
                    },
                )
                await self._buffer_entry(chunk_entry)
                yield chunk

            end_entry = await self._create_entry(
                direction="outbound_stream_end",
                source="proxy",
                destination=self._get_client_info(context),
                context=context,
                session_id=stream_session_id,
                backend=backend or "proxy",
                model=model or "unknown",
                key_name=key_name,
                payload={
                    "total_bytes": total_bytes,
                    "total_chunks": chunk_count,
                    "stream_type": "outbound_response",
                },
            )
            await self._buffer_entry(end_entry)

        return _capture_stream()

    async def _create_entry(
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

        # Determine content type based on ORIGINAL payload type before redaction
        # This preserves the semantic type even if redaction changes the structure
        content_type = "unknown"

        if isinstance(payload, bytes):
            content_type = "bytes"
        elif isinstance(payload, dict | list):
            content_type = "json"
        elif isinstance(payload, str):
            content_type = "text"
        else:
            content_type = "object"

        # PERFORMANCE OPTIMIZATION: Calculate content length from ORIGINAL payload
        # This allows caching to work when the same payload object is reused
        content_length = self._get_content_length_cached(payload)

        # Redact payload after determining type and calculating length
        redacted_payload = self._redact_payload(payload)

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

        # Use centralized session ID resolver for consistency
        resolved_session_id = (
            self._stream_session_id_resolver.resolve_stream_session_id(
                session_id=session_id,
                context=context,
                request=None,
            )
        )

        # Get next sequence number for stable ordering
        self._sequence_counter += 1
        sequence = self._sequence_counter

        return WireCaptureEntry(
            timestamp_iso=now.isoformat(),
            timestamp_unix=now.timestamp(),
            sequence=sequence,
            direction=direction,
            source=source,
            destination=destination,
            session_id=str(resolved_session_id),
            backend=backend,
            model=model,
            key_name=key_name,
            content_type=content_type,
            content_length=content_length,
            payload=redacted_payload,
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
            # Use session_id or 'default' as key
            key = entry.session_id or "default"

            # Memory leak prevention: if we're at capacity and this is a new key,
            # clean up empty buffers first
            if key not in self._buffers and len(self._buffers) >= self._max_buffer_keys:
                self._cleanup_empty_buffers_locked()

            # Enforce limit: if still at capacity with a new key, force flush to free space
            # This preserves all entries by flushing them to disk before evicting
            if len(self._buffers) >= self._max_buffer_keys and key not in self._buffers:
                # At capacity with new key - flush to free up space
                # This ensures we don't lose entries by evicting non-empty buffers
                await self._flush_buffer()
                # After flush, buffers are cleared, so we can add the new key

            self._buffers[key].append(entry)

            # Check if we should flush immediately (check total size across all buffers)
            total_entries = sum(len(b) for b in self._buffers.values())
            should_flush = (
                total_entries >= self._max_entries_per_flush
                or (time.time() - self._last_flush_time) >= self._flush_interval
            )

            if should_flush:
                await self._flush_buffer()

    def _cleanup_empty_buffers_locked(self) -> None:
        """Remove empty buffers to free up space. Must be called with lock held."""
        empty_keys = [
            key for key, buffer_list in self._buffers.items() if not buffer_list
        ]
        for key in empty_keys:
            del self._buffers[key]
        if empty_keys and logger.isEnabledFor(logging.DEBUG):
            logger.debug("Cleaned up %d empty buffer keys", len(empty_keys))

    async def _flush_buffer(self) -> None:
        """Flush buffered entries to file."""
        if not self._buffers or not self._file_path:
            return

        # Take snapshot of buffers and clear them
        entries_to_write: list[WireCaptureEntry] = []

        for key in list(self._buffers.keys()):
            entries_to_write.extend(self._buffers[key])
            self._buffers[key].clear()

        # Remove empty keys to prevent dict from growing indefinitely
        self._buffers.clear()

        self._last_flush_time = time.time()

        # Write entries (do this outside the lock? No, we are inside the lock here)
        # The writing happens in run_in_executor, which is fine.

        if not entries_to_write:
            return

        # Sort by timestamp and sequence to maintain stable order in file
        entries_to_write.sort(key=lambda x: (x.timestamp_unix, x.sequence))

        import contextlib

        with contextlib.suppress(Exception):
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._write_entries_sync, entries_to_write)

        # Check for rotation after writing
        await self._check_rotation()

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

            # Rotation check happens in the async caller method

        except OSError as e:
            logger.warning(
                "Wire capture write failed due to OS error (continuing): %s",
                e,
                exc_info=True,
            )
        except Exception as e:
            logger.error(
                "Wire capture write failed unexpectedly (continuing): %s",
                e,
                exc_info=True,
            )

    def _write_entry_sync(self, entry: WireCaptureEntry) -> None:
        """Write a single entry synchronously (used during initialization)."""
        if not self._file_path:
            return

        try:
            with open(self._file_path, "a", encoding="utf-8") as f:
                json_line = self._serialize_entry_cached(entry)
                f.write(json_line + "\n")
        except OSError as e:
            logger.warning(
                "Wire capture entry write failed during init (continuing): %s",
                e,
                exc_info=True,
            )
        except Exception as e:
            logger.error(
                "Wire capture entry write failed unexpectedly during init (continuing): %s",
                e,
                exc_info=True,
            )

    async def _check_rotation(self) -> None:
        """Check if file rotation is needed."""
        if not self._file_path or not self._max_bytes:
            return

        try:
            if os.path.exists(self._file_path):
                current_size = os.path.getsize(self._file_path)
                if current_size > self._max_bytes:
                    await self._perform_rotation()
        except OSError as e:
            logger.warning(
                "Wire capture rotation check failed (continuing): %s",
                e,
                exc_info=True,
            )
        except Exception as e:
            logger.error(
                "Wire capture rotation check failed unexpectedly (continuing): %s",
                e,
                exc_info=True,
            )

    async def _robust_replace(
        self, src: str, dst: str, retries: int = 5, delay: float = 0.1
    ) -> None:
        """Attempt to replace a file with retries to handle Windows file locking."""
        for i in range(retries):
            try:
                os.replace(src, dst)
                return
            except PermissionError:
                if i < retries - 1:
                    await asyncio.sleep(delay)
                else:
                    raise

    async def _perform_rotation(self) -> None:
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
                    await self._robust_replace(src, dst)

            # 3. Rotate the current log to .1
            if os.path.exists(self._file_path):
                await self._robust_replace(self._file_path, f"{self._file_path}.1")

            # 4. Ensure a fresh file exists for subsequent writes
            with open(self._file_path, "a", encoding="utf-8"):
                pass
        except OSError as e:
            logger.warning(
                "Wire capture rotation failed due to OS error (continuing): %s",
                e,
                exc_info=True,
            )
        except Exception as e:
            logger.error(
                "Wire capture rotation failed unexpectedly (continuing): %s",
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
                    # Check again after sleep in case we were disabled during sleep
                    if not self._enabled:
                        break
                    async with self._buffer_lock:
                        if any(self._buffers.values()):
                            await self._flush_buffer()
                except asyncio.CancelledError:
                    break
                except OSError as e:
                    logger.warning(
                        "Background wire capture flush failed due to OS error (continuing): %s",
                        e,
                        exc_info=True,
                    )
                    continue
                except Exception as e:
                    logger.error(
                        "Background wire capture flush failed unexpectedly (continuing): %s",
                        e,
                        exc_info=True,
                    )
                    continue
        except asyncio.CancelledError:
            # Task cancelled during shutdown (intentionally silent control flow)
            with contextlib.suppress(asyncio.CancelledError):
                pass
        finally:
            if self._enabled:
                try:
                    async with self._buffer_lock:
                        if any(self._buffers.values()):
                            await self._flush_buffer()
                except OSError as e:
                    logger.warning(
                        "Final wire capture flush failed due to OS error (continuing): %s",
                        e,
                        exc_info=True,
                    )
                except Exception as e:
                    logger.error(
                        "Final wire capture flush failed unexpectedly (continuing): %s",
                        e,
                        exc_info=True,
                    )

    async def shutdown(self) -> None:
        """Shutdown wire capture and flush remaining data."""
        # Disable first to signal the background task to stop
        self._enabled = False

        # Cancel and wait for the background task to complete
        if self._flush_task and not self._flush_task.done():
            self._flush_task.cancel()

            # Wait for the task to complete, suppressing CancelledError
            try:
                await self._flush_task
            except asyncio.CancelledError:
                # Expected during task cancellation (intentionally silent control flow)
                import contextlib

                with contextlib.suppress(asyncio.CancelledError):
                    pass
            except Exception as e:
                logger.warning(
                    "Unexpected exception during wire capture shutdown: %s",
                    e,
                    exc_info=True,
                )

        # Ensure task reference is cleared
        self._flush_task = None

        # Final flush
        async with self._buffer_lock:
            if any(self._buffers.values()):
                await self._flush_buffer()

        # PERFORMANCE OPTIMIZATION: Clean up cache to prevent memory leaks
        self._content_length_cache.clear()

    def force_shutdown_sync(self) -> None:
        """Synchronous best-effort shutdown. Deprecated and unsafe from __del__."""
        # This method is problematic when called from __del__ during interpreter shutdown.
        # The async shutdown() method should be used for proper cleanup.
        if not getattr(self, "_enabled", False):
            return

        self._enabled = False

        # Best-effort cancellation of the background task without awaiting.
        if self._flush_task and not self._flush_task.done():
            with contextlib.suppress(Exception):
                task = self._flush_task
                # Suppress the 'task was destroyed but it is pending!' message
                # This is a hack but necessary when we can't await the task
                if hasattr(task, "_log_destroy_pending"):
                    cast(Any, task)._log_destroy_pending = False

                loop = task.get_loop()
                if loop.is_running() and not loop.is_closed():
                    loop.call_soon_threadsafe(task.cancel)

                # We cannot await here, so we just clear the reference

        self._flush_task = None

    def __del__(self) -> None:
        """Ensure cleanup is attempted on garbage collection."""
        # Use safe attribute access during interpreter shutdown
        if getattr(self, "_enabled", False):
            self.force_shutdown_sync()

    def _resolve_stream_session_id(
        self, session_id: str | None, context: RequestContext | None
    ) -> str:
        """Return a stable session identifier for streaming capture.

        This is a thin wrapper method that delegates to the injected
        IStreamSessionIdResolver. Preserved for backward compatibility.

        Note: This method does not have access to the ChatRequest, so it
        cannot check request.session_id or request.extra_body.session_id.
        """
        return self._stream_session_id_resolver.resolve_stream_session_id(
            session_id=session_id,
            context=context,
            request=None,  # BufferedWireCapture doesn't have request access
        )
