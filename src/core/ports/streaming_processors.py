"""
Streaming processors that implement IStreamProcessor interface.

This module contains middleware processors that observe or transform
streaming content as it flows through the pipeline.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from src.core.common.exceptions import ToolCallLoopError
from src.core.domain.configuration.loop_detection_config import (
    LoopDetectionConfiguration,
)
from src.core.ports.streaming_contracts import IStreamProcessor, StreamingContent
from src.core.ports.streaming_metrics import get_metrics_instance
from src.loop_detection.token_window_loop_detector import TokenWindowLoopDetector
from src.tool_call_loop.tracker import ToolCallTracker

logger = logging.getLogger(__name__)

_THINK_OPENING_PATTERN = re.compile(r"^(\s*)<think>", re.IGNORECASE)
_THINK_CLOSING_PATTERN = re.compile(r"</think>", re.IGNORECASE)
# Full <think>...</think> pattern for reasoning extraction.
_THINK_TAG_PATTERN = re.compile(
    r"^(\s*)<think>(.*?)</think>(\s*)(.*?)$", re.DOTALL | re.IGNORECASE
)
# Keep a small window of trailing content to detect think tags that span chunks.
_THINK_TAG_LOOKBACK = 128

# Maximum number of session states to keep in memory to prevent unbounded growth
# 10,000 sessions provides a large window for active sessions without unbounded growth
_MAX_SESSION_STATES = 10_000

# TTL for session states: remove if not accessed for 1 hour
# This prevents accumulation of stale sessions that were never completed
_SESSION_STATE_TTL_SECONDS = 3600


@dataclass(frozen=True, slots=True)
class ThinkTagFixResult:
    """Result of fixing think tags in content.

    Attributes:
        response_content: The content outside the think tags (or original content if no tags found).
        reasoning_content: The extracted reasoning content inside the tags, or None if no tags found.
    """

    response_content: str
    reasoning_content: str | None


class LoopDetectionProcessor(IStreamProcessor):
    """Processor for detecting content loops in streaming responses.

    This processor uses a sliding window approach to detect repetitive
    patterns in streaming content, preventing models from getting stuck
    in loops.
    """

    def __init__(
        self,
        content_loop_threshold: int = 8,
        content_chunk_size: int = 128,
        max_history_length: int = 2000,
    ) -> None:
        """Initialize the loop detection processor.

        Args:
            content_loop_threshold: Number of repetitions to trigger detection
            content_chunk_size: Size of chunks for comparison
            max_history_length: Maximum content history to maintain
        """
        self._detector = TokenWindowLoopDetector(
            content_loop_threshold=content_loop_threshold,
            content_chunk_size=content_chunk_size,
            max_history_length=max_history_length,
        )
        self._logger = logging.getLogger(__name__)

    async def process(self, content: StreamingContent) -> StreamingContent:
        """Process streaming content and check for loops.

        Args:
            content: The streaming content to process

        Returns:
            The processed content (unchanged if no loop detected)

        Raises:
            ToolCallLoopError: If a content loop is detected
        """
        # Pass through [DONE] markers unchanged
        if content.is_done:
            return content

        metadata = content.metadata or {}
        if (
            (isinstance(metadata.get("tool_calls"), list) and metadata["tool_calls"])
            or metadata.get("finish_reason") == "tool_calls"
            or metadata.get("role") == "tool"
        ):
            return content

        # Skip empty chunks
        if content.is_empty or not content.content:
            return content

        # Extract text content for loop detection
        text_content = self._extract_text_content(content.content)
        if not text_content:
            return content

        # Check for loops
        loop_event = self._detector.process_chunk(text_content)
        if loop_event:
            if self._logger.isEnabledFor(logging.WARNING):
                self._logger.warning(
                    "Content loop detected in stream",
                    extra={
                        "stream_id": content.stream_id,
                        "pattern_length": loop_event.pattern_length,
                        "repetitions": loop_event.repetition_count,
                    },
                )
            # Add loop detection metadata to the chunk
            content.metadata["loop_detected"] = True
            content.metadata["loop_pattern_length"] = loop_event.pattern_length
            content.metadata["loop_repetitions"] = loop_event.repetition_count

            # Track middleware mutation
            metrics = get_metrics_instance()
            metrics.increment_middleware_mutations(content.stream_id)

        return content

    def reset(self) -> None:
        """Reset loop detection state for new stream."""
        self._detector.reset()
        if self._logger.isEnabledFor(logging.DEBUG):
            self._logger.debug("Loop detection processor state reset")

    def _extract_text_content(self, content: Any) -> str:
        """Extract text content for loop detection.

        Args:
            content: The content to extract text from

        Returns:
            Text content suitable for loop detection
        """
        return _extract_text_from_chunk_content(content, fallback_to_json=True)


class ToolCallRepairProcessor(IStreamProcessor):
    """Processor for detecting and preventing tool call loops.

    This processor tracks tool calls in streaming responses and detects
    repetitive patterns that may indicate a model is stuck in a loop.
    """

    def __init__(self, max_cached_sessions: int = 256) -> None:
        """Initialize the tool call repair processor.

        Args:
            max_cached_sessions: Maximum number of session trackers to cache
        """
        if max_cached_sessions <= 0:
            raise ValueError("max_cached_sessions must be positive")

        self._session_trackers: dict[str, ToolCallTracker] = {}
        self._max_cached_sessions = max_cached_sessions
        self._session_order: list[str] = []  # Track LRU order
        self._logger = logging.getLogger(__name__)
        self._lock = threading.RLock()

    async def process(self, content: StreamingContent) -> StreamingContent:
        """Process streaming content and check for tool call loops.

        Args:
            content: The streaming content to process

        Returns:
            The processed content

        Raises:
            ToolCallLoopError: If a tool call loop is detected
        """
        # Pass through [DONE] markers unchanged
        if content.is_done:
            return content

        # Skip if no tool calls in metadata
        tool_calls = content.metadata.get("tool_calls")
        if not tool_calls or not isinstance(tool_calls, list):
            return content

        # Get or create session ID
        session_id = content.stream_id or content.metadata.get("stream_id")
        if not session_id:
            # Generate a session ID if not present
            session_id = str(uuid4())
            content.metadata["stream_id"] = session_id
            content.stream_id = session_id

        # Get configuration from metadata
        config = self._get_config_from_metadata(content.metadata)
        if not config or not config.tool_loop_detection_enabled:
            return content

        # Filter out already-processed tool calls
        new_tool_calls = self._filter_new_tool_calls(tool_calls)
        if not new_tool_calls:
            self._logger.log(
                5,  # TRACE level
                f"Skipping loop detection - all {len(tool_calls)} tool calls already processed",
            )
            return content

        # Get or create tracker for this session
        tracker = self._get_or_create_tracker(session_id, config)

        # Track that we're processing tool calls (middleware mutation)
        metrics = get_metrics_instance()
        if new_tool_calls:
            metrics.increment_middleware_mutations(session_id)

        # Process each new tool call
        for tool_call in new_tool_calls:
            tool_name = tool_call.get("function", {}).get("name", "unknown")
            arguments = tool_call.get("function", {}).get("arguments", "{}")

            # Track the tool call
            tracking_result = await tracker.track_tool_call(tool_name, arguments)  # type: ignore[assignment]

            if tracking_result.should_block:  # type: ignore[attr-defined]
                if self._logger.isEnabledFor(logging.WARNING):
                    self._logger.warning(
                        f"Tool call loop detected in session {session_id}: "
                        f"tool={tool_name}, repeats={tracking_result.repeat_count}/{tracker.config.max_repeats}, "  # type: ignore[attr-defined]
                        f"window={tracker.config.ttl_seconds}s, "
                        f"mode={tracker.config.mode.value}"
                    )

                # Raise an error to stop the response
                raise ToolCallLoopError(
                    message=f"Tool call loop detected: {tracking_result.reason}",  # type: ignore[attr-defined]
                    details={
                        "tool_name": tool_name,
                        "repetitions": tracking_result.repeat_count,  # type: ignore[attr-defined]
                        "mode": tracker.config.mode.value,
                    },
                )

        # Mark tool calls as processed
        self._mark_tool_calls_processed(tool_calls)

        return content

    def reset(self) -> None:
        """Reset tool call tracking state for new stream."""
        with self._lock:
            self._session_trackers.clear()
            self._session_order.clear()
        if self._logger.isEnabledFor(logging.DEBUG):
            self._logger.debug("Tool call repair processor state reset")

    def _get_config_from_metadata(
        self, metadata: dict[str, Any]
    ) -> LoopDetectionConfiguration | None:
        """Extract loop detection configuration from metadata.

        Args:
            metadata: The metadata dictionary

        Returns:
            LoopDetectionConfiguration if present, None otherwise
        """
        config_data = metadata.get("loop_detection_config")
        if not config_data:
            return None

        if isinstance(config_data, LoopDetectionConfiguration):
            return config_data

        # Try to construct from dict
        if isinstance(config_data, dict):
            try:
                return LoopDetectionConfiguration(**config_data)
            except ValidationError as e:
                if self._logger.isEnabledFor(logging.WARNING):
                    self._logger.warning(
                        f"Failed to construct LoopDetectionConfiguration: {e}",
                        exc_info=True,
                    )
                return None

        return None

    def _get_or_create_tracker(
        self, session_id: str, config: LoopDetectionConfiguration
    ) -> ToolCallTracker:
        """Get or create a tracker for a session.

        Args:
            session_id: The session identifier
            config: The loop detection configuration

        Returns:
            ToolCallTracker for the session
        """
        with self._lock:
            tracker = self._session_trackers.get(session_id)
            if tracker is None:
                # Create new tracker
                from src.tool_call_loop.config import ToolCallLoopConfig

                tracker_config = ToolCallLoopConfig(
                    enabled=config.tool_loop_detection_enabled,
                    max_repeats=config.tool_loop_max_repeats or 4,
                    ttl_seconds=config.tool_loop_ttl_seconds or 120,
                    mode=self._resolve_tool_loop_mode(config.tool_loop_mode),
                )
                tracker = ToolCallTracker(config=tracker_config)
                self._session_trackers[session_id] = tracker
                self._session_order.append(session_id)
                self._enforce_cache_limit()
            else:
                # Move to end (LRU)
                if session_id in self._session_order:
                    self._session_order.remove(session_id)
                self._session_order.append(session_id)

        return tracker

    def _resolve_tool_loop_mode(self, mode_value: Any) -> Any:
        """Resolve tool loop mode from configuration value.

        Args:
            mode_value: The mode value from configuration

        Returns:
            Resolved ToolLoopMode
        """
        from src.tool_call_loop.config import ToolLoopMode

        if isinstance(mode_value, ToolLoopMode):
            return mode_value

        if isinstance(mode_value, str):
            normalized = mode_value.strip().lower()
            if normalized == "chance":
                normalized = "chance_then_break"
            try:
                return ToolLoopMode(normalized)
            except ValueError:
                if self._logger.isEnabledFor(logging.WARNING):
                    self._logger.warning(
                        "Invalid tool loop mode '%s' provided; falling back to break mode.",
                        mode_value,
                        exc_info=True,
                    )

        return ToolLoopMode.BREAK

    def _filter_new_tool_calls(
        self, tool_calls: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Filter tool calls to only include new ones.

        Args:
            tool_calls: List of tool call dictionaries

        Returns:
            List of new (unprocessed) tool calls
        """
        return [tc for tc in tool_calls if not tc.get("_already_processed", False)]

    def _mark_tool_calls_processed(self, tool_calls: list[dict[str, Any]]) -> None:
        """Mark tool calls as processed.

        Args:
            tool_calls: List of tool call dictionaries to mark
        """
        for tool_call in tool_calls:
            tool_call["_already_processed"] = True

    def _enforce_cache_limit(self) -> None:
        """Ensure the session tracker cache does not grow without bound."""
        with self._lock:
            while len(self._session_trackers) > self._max_cached_sessions:
                # Remove oldest session (first in order list)
                if self._session_order:
                    evicted_session_id = self._session_order.pop(0)
                    self._session_trackers.pop(evicted_session_id, None)
                    if self._logger.isEnabledFor(logging.DEBUG):
                        self._logger.debug(
                            "Evicted tool call tracker for session %s due to cache limit",
                            evicted_session_id,
                        )


class ToolCallDeltaStabilizerProcessor(IStreamProcessor):
    """Stabilize streamed `tool_calls` deltas for OpenAI-compatible clients.

    Some upstream providers omit `tool_calls[].id` and/or `tool_calls[].function.name`
    on continuation chunks and only stream `function.arguments` fragments.

    Many OpenAI-compatible SDKs expect `id` and `name` to be present on every
    `tool_calls` delta. This processor fills missing fields using the most
    recently observed values per (stream_id, tool_call.index).

    It only mutates `content.metadata["tool_calls"]` (structured/native tool calls)
    and does not parse or interpret textual pseudo-tool-calls.
    """

    def __init__(
        self,
        *,
        max_session_states: int = _MAX_SESSION_STATES,
        session_ttl_seconds: int = _SESSION_STATE_TTL_SECONDS,
    ) -> None:
        self._logger = logging.getLogger(__name__)
        self._max_session_states = max_session_states
        self._session_ttl_seconds = session_ttl_seconds

        # stream_id -> {index -> {"id": str, "name": str, "type": str}}
        self._tool_call_state: dict[str, dict[int, dict[str, str]]] = {}
        self._last_access: dict[str, float] = {}

    async def process(self, content: StreamingContent) -> StreamingContent:
        # Clear per-stream state on terminal chunks.
        if content.is_done or content.is_cancellation:
            stream_id = content.stream_id or content.metadata.get("stream_id")
            if isinstance(stream_id, str) and stream_id:
                self._cleanup_stream(stream_id)
            return content

        tool_calls_raw = content.metadata.get("tool_calls")
        if not isinstance(tool_calls_raw, list) or not tool_calls_raw:
            return content

        stream_id = content.stream_id or content.metadata.get("stream_id")
        if not isinstance(stream_id, str) or not stream_id:
            return content

        self._maybe_cleanup_stale_streams()
        self._last_access[stream_id] = time.time()

        state_for_stream = self._tool_call_state.setdefault(stream_id, {})
        changed = False
        stabilized: list[Any] = []

        for position, raw_tool_call in enumerate(tool_calls_raw):
            if not isinstance(raw_tool_call, dict):
                stabilized.append(raw_tool_call)
                continue

            # Prefer explicit index; fall back to position in list.
            idx_val = raw_tool_call.get("index")
            index = idx_val if isinstance(idx_val, int) else position

            signature = state_for_stream.setdefault(index, {})

            # Learn from this chunk.
            call_id = raw_tool_call.get("id")
            if isinstance(call_id, str) and call_id:
                signature["id"] = call_id
            call_type = raw_tool_call.get("type")
            if isinstance(call_type, str) and call_type:
                signature["type"] = call_type

            fn = raw_tool_call.get("function")
            if isinstance(fn, dict):
                name = fn.get("name")
                if isinstance(name, str) and name:
                    signature["name"] = name

            # Apply stabilization.
            repaired: dict[str, Any] = dict(raw_tool_call)
            if "id" not in repaired and "id" in signature:
                repaired["id"] = signature["id"]
                changed = True
            if "type" not in repaired and "type" in signature:
                repaired["type"] = signature["type"]
                changed = True

            repaired_fn = repaired.get("function")
            if not isinstance(repaired_fn, dict):
                repaired_fn = {}
                if "name" in signature:
                    repaired_fn["name"] = signature["name"]
                    repaired["function"] = repaired_fn
                    changed = True
            else:
                if "name" not in repaired_fn and "name" in signature:
                    repaired_fn = dict(repaired_fn)
                    repaired_fn["name"] = signature["name"]
                    repaired["function"] = repaired_fn
                    changed = True

            stabilized.append(repaired)

        if changed:
            content.metadata["tool_calls"] = stabilized
            # Track middleware mutation
            metrics = get_metrics_instance()
            metrics.increment_middleware_mutations(stream_id)

        return content

    def reset(self) -> None:
        self._tool_call_state.clear()
        self._last_access.clear()
        if self._logger.isEnabledFor(logging.DEBUG):
            self._logger.debug("Tool call delta stabilizer state reset")

    def _cleanup_stream(self, stream_id: str) -> None:
        self._tool_call_state.pop(stream_id, None)
        self._last_access.pop(stream_id, None)

    def _maybe_cleanup_stale_streams(self) -> None:
        now = time.time()
        stale_ids = [
            sid
            for sid, last in self._last_access.items()
            if (now - last) > self._session_ttl_seconds
        ]
        for sid in stale_ids:
            self._cleanup_stream(sid)

        # If still above cap, evict least recently accessed.
        if len(self._tool_call_state) > self._max_session_states:
            ordered = sorted(self._last_access.items(), key=lambda kv: kv[1])
            to_evict = len(self._tool_call_state) - self._max_session_states
            for sid, _ in ordered[: max(0, to_evict)]:
                self._cleanup_stream(sid)


class ThinkTagsProcessor(IStreamProcessor):
    """Processor for fixing improperly formatted <think> tags.

    This processor detects and corrects <think> tags that appear in the
    main content stream, extracting them to the reasoning_content metadata
    field.
    """

    def __init__(
        self,
        enabled: bool = True,
        streaming_buffer_size: int = 16384,  # Increased from 4096 to 16KB
        max_session_states: int = _MAX_SESSION_STATES,
        session_ttl_seconds: int = _SESSION_STATE_TTL_SECONDS,
    ) -> None:
        """Initialize the think tags processor.

        Args:
            enabled: Whether the processor is enabled
            streaming_buffer_size: Maximum buffer size for streaming chunks
            max_session_states: Maximum number of session states to keep in memory
            session_ttl_seconds: TTL in seconds for stale session states
        """
        self._enabled = enabled
        self._streaming_buffer_size = streaming_buffer_size
        self._logger = logging.getLogger(__name__)

        # Streaming state management
        self._streaming_buffers: dict[str, str] = {}
        self._reasoning_extracted: dict[str, dict[str, Any]] = {}
        self._stream_states: dict[str, str] = {}  # waiting, in_think, post_think
        self._last_access: dict[str, float] = (
            {}
        )  # Track last access time for TTL cleanup
        self._think_tag_lookback = _THINK_TAG_LOOKBACK
        self._max_session_states = max_session_states
        self._session_ttl_seconds = session_ttl_seconds

    async def process(self, content: StreamingContent) -> StreamingContent:
        """Process streaming content and fix think tags.

        Args:
            content: The streaming content to process

        Returns:
            The processed content with think tags fixed
        """
        if not self._enabled:
            return content

        # Pass through [DONE] markers unchanged
        if content.is_done:
            if content.stream_id or content.metadata.get("stream_id"):
                # Clear any per-stream state to avoid stale buffers between streams
                session_id = (
                    content.stream_id
                    if content.stream_id
                    else content.metadata.get("stream_id")
                )
                if session_id:
                    self._cleanup_session_state(session_id)
            return content

        # Skip empty chunks
        if content.is_empty or not content.content:
            return content

        session_id = self._get_or_set_session_id(content)

        # Clean up stale sessions periodically to prevent unbounded growth
        self._maybe_cleanup_stale_sessions()

        # Extract text content
        text_content = self._extract_text_content(content.content)
        if not text_content:
            return content

        # Process the chunk
        fixed_content, reasoning_content = self._process_streaming_chunk(
            text_content, session_id
        )

        # Update content if changed
        if fixed_content != text_content:
            content.content = fixed_content
            # Track middleware mutation
            metrics = get_metrics_instance()
            metrics.increment_middleware_mutations(session_id)

        # Add reasoning to metadata if extracted
        if reasoning_content:
            content.metadata["reasoning_content"] = reasoning_content
            content.metadata["reasoning"] = reasoning_content
            content.metadata["reasoning_format"] = "extracted_from_think_tags"
            content.metadata["think_tags_fixed"] = True

        return content

    def reset(self) -> None:
        """Reset think tags processing state for new stream."""
        self._streaming_buffers.clear()
        self._reasoning_extracted.clear()
        self._stream_states.clear()
        self._last_access.clear()
        if self._logger.isEnabledFor(logging.DEBUG):
            self._logger.debug("Think tags processor state reset")

    def _extract_text_content(self, content: Any) -> str:
        """Extract text content for processing.

        Args:
            content: The content to extract text from

        Returns:
            Text content suitable for processing
        """
        return _extract_text_from_chunk_content(content, fallback_to_json=False)

    def _process_streaming_chunk(
        self, chunk_content: str, session_id: str
    ) -> tuple[str, str | None]:
        """Process a streaming chunk and handle think tags.

        Args:
            chunk_content: The content of the current chunk
            session_id: The session identifier

        Returns:
            Tuple of (processed_chunk_content, reasoning_content)
        """
        self._ensure_session_state(session_id)

        current_state = self._stream_states[session_id]
        current_buffer = self._streaming_buffers.get(session_id, "")

        # Aggressively trim buffer when not in think tag to minimize memory usage
        if current_state == "waiting" and current_buffer:
            # Keep only lookback window for cross-chunk detection
            current_buffer = current_buffer[-self._think_tag_lookback :]

        new_buffer = current_buffer + chunk_content

        # Check for buffer overflow before processing
        if len(new_buffer) > self._streaming_buffer_size:
            if self._logger.isEnabledFor(logging.WARNING):
                self._logger.warning(
                    "Streaming buffer overflow for session %s, processing as-is",
                    session_id,
                )
            result = self._fix_think_tags(new_buffer)
            self._cleanup_session_state(session_id)
            return result.response_content, result.reasoning_content

        if current_state == "waiting":
            # Check for think tags in the combined buffer
            if _THINK_OPENING_PATTERN.search(new_buffer):
                self._stream_states[session_id] = "in_think"
                self._streaming_buffers[session_id] = new_buffer
                if self._logger.isEnabledFor(logging.DEBUG):
                    self._logger.debug(
                        "Started think tag detection for session %s", session_id
                    )
                if _THINK_CLOSING_PATTERN.search(new_buffer):
                    result = self._fix_think_tags(new_buffer)
                    self._stream_states[session_id] = "post_think"
                    self._streaming_buffers[session_id] = ""
                    return result.response_content, result.reasoning_content

                # Keep the buffered reasoning content until we see a closing tag
                return "", None

            # No think tags detected - trim buffer immediately to minimize memory
            # Only keep lookback window for potential cross-chunk detection
            trimmed_buffer = new_buffer[-self._think_tag_lookback :]
            self._streaming_buffers[session_id] = trimmed_buffer
            return chunk_content, None

        if current_state == "in_think":
            # Store buffer while inside think tag
            self._streaming_buffers[session_id] = new_buffer
            if _THINK_CLOSING_PATTERN.search(new_buffer):
                result = self._fix_think_tags(new_buffer)
                self._stream_states[session_id] = "post_think"
                self._streaming_buffers[session_id] = ""
                return result.response_content, result.reasoning_content

            # Still inside <think>...</think>, keep buffering until we can close it
            return "", None

        if current_state == "post_think":
            # We've already extracted reasoning, reset buffer to avoid growth
            self._streaming_buffers[session_id] = ""
            return chunk_content, None

        return chunk_content, None

    def _fix_think_tags(self, content: str) -> ThinkTagFixResult:
        """Fix improperly formatted <think> tags in content.

        Args:
            content: The original content that may contain improper think tags

        Returns:
            ThinkTagFixResult containing response_content and reasoning_content
        """
        if not content:
            return ThinkTagFixResult(response_content=content, reasoning_content=None)

        # Check if content starts with <think> tag
        if not _THINK_OPENING_PATTERN.match(content):
            return ThinkTagFixResult(response_content=content, reasoning_content=None)

        # Try to match full <think>...</think> pattern
        match = _THINK_TAG_PATTERN.match(content)
        if not match:
            # If we have opening <think> but no proper closing, treat entire content as reasoning
            if content.strip().startswith("<think>"):
                # Remove opening tag and treat rest as reasoning
                reasoning_content = content.replace("<think>", "", 1).strip()
                if reasoning_content.endswith("</think>"):
                    reasoning_content = reasoning_content[:-8].strip()

                if self._logger.isEnabledFor(logging.INFO):
                    self._logger.info(
                        "Fixed incomplete think tags - treating as pure reasoning"
                    )
                # Return empty content since this was all reasoning
                return ThinkTagFixResult(
                    response_content="", reasoning_content=reasoning_content
                )
            return ThinkTagFixResult(response_content=content, reasoning_content=None)

        leading_space, reasoning_content, middle_space, remaining_content = (
            match.groups()
        )

        # Strip outer whitespace to normalize reasoning blocks
        reasoning_content = reasoning_content.strip() if reasoning_content else ""
        response_content = (
            f"{leading_space}{middle_space}{remaining_content}"
            if remaining_content is not None
            else f"{leading_space}{middle_space}"
        )

        if self._logger.isEnabledFor(logging.INFO):
            self._logger.info(
                "Fixed improperly formatted think tags - extracted %d chars of reasoning, %d chars of content",
                len(reasoning_content),
                len(response_content),
            )

        return ThinkTagFixResult(
            response_content=response_content, reasoning_content=reasoning_content
        )

    def _cleanup_session_state(self, session_id: str) -> None:
        """Clean up streaming state for a session.

        Args:
            session_id: The session identifier to clean up
        """
        self._streaming_buffers.pop(session_id, None)
        self._stream_states.pop(session_id, None)
        # Clean up reasoning_extracted to prevent memory leaks
        self._reasoning_extracted.pop(session_id, None)
        self._last_access.pop(session_id, None)

    def _ensure_session_state(self, session_id: str) -> None:
        """Initialize state containers for a session if missing."""
        now = time.time()

        # Check if we need to evict old sessions before adding new one
        if session_id not in self._streaming_buffers:
            self._maybe_cleanup_stale_sessions()
            # Enforce max limit by evicting oldest sessions if needed
            while len(self._streaming_buffers) >= self._max_session_states:
                self._evict_oldest_session()

        if session_id not in self._streaming_buffers:
            self._streaming_buffers[session_id] = ""
        if session_id not in self._stream_states:
            self._stream_states[session_id] = "waiting"
        if session_id not in self._reasoning_extracted:
            self._reasoning_extracted[session_id] = {}

        # Update last access time
        self._last_access[session_id] = now

    def _get_or_set_session_id(self, content: StreamingContent) -> str:
        """Ensure the streaming chunk carries a session identifier."""
        session_id = content.stream_id or content.metadata.get("stream_id")
        if not session_id:
            session_id = str(uuid4())
            content.metadata["stream_id"] = session_id
            content.stream_id = session_id
        else:
            content.stream_id = session_id
        return session_id

    def _maybe_cleanup_stale_sessions(self) -> None:
        """Clean up stale session states based on TTL.

        This prevents unbounded growth when streams never complete or fail.
        """
        if len(self._streaming_buffers) < self._max_session_states:
            return

        now = time.time()
        expired_sessions = [
            (sid, last_access)
            for sid, last_access in self._last_access.items()
            if now - last_access > self._session_ttl_seconds
        ]

        for sid, last_access in expired_sessions:
            self._cleanup_session_state(sid)
            if self._logger.isEnabledFor(logging.DEBUG):
                self._logger.debug(
                    "Removed stale think tags session state: %s (last access: %.1fs ago)",
                    sid,
                    now - last_access,
                )

    def _evict_oldest_session(self) -> None:
        """Evict the oldest session state when max limit is reached (LRU eviction).

        This prevents unbounded growth by removing least recently used sessions.
        """
        if not self._last_access:
            return

        # Find oldest session by last access time
        oldest_session_id = min(self._last_access.items(), key=lambda x: x[1])[0]
        self._cleanup_session_state(oldest_session_id)

        if self._logger.isEnabledFor(logging.DEBUG):
            self._logger.debug(
                "Evicted oldest think tags session state: %s (max_sessions=%d reached)",
                oldest_session_id,
                self._max_session_states,
            )


def _extract_text_from_chunk_content(content: Any, *, fallback_to_json: bool) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, bytes):
        try:
            return content.decode("utf-8")
        except UnicodeDecodeError:
            return content.decode("latin-1")
    if isinstance(content, dict):
        if "content" in content:
            return str(content["content"])
        if fallback_to_json:
            from src.core.ports.streaming_contracts import StopChunkWithUsage

            return StopChunkWithUsage.safe_json_dumps(content)
        return ""
    return str(content)
