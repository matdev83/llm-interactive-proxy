"""
Streaming processors that implement the IStreamProcessor interface.

This module contains middleware processors that observe or transform
streaming content as it flows through the pipeline.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any
from uuid import uuid4

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
        self._logger.debug("Loop detection processor state reset")

    def _extract_text_content(self, content: str | dict | bytes) -> str:
        """Extract text content for loop detection.

        Args:
            content: The content to extract text from

        Returns:
            Text content suitable for loop detection
        """
        if isinstance(content, str):
            return content
        elif isinstance(content, bytes):
            try:
                return content.decode("utf-8")
            except UnicodeDecodeError:
                return content.decode("latin-1")
        elif isinstance(content, dict):
            # Extract text from dict (e.g., delta content)
            if "content" in content:
                return str(content["content"])
            return json.dumps(content)
        return str(content)


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
            should_block, reason, repeat_count = tracker.track_tool_call(
                tool_name, arguments
            )

            if should_block:
                self._logger.warning(
                    f"Tool call loop detected in session {session_id}: "
                    f"tool={tool_name}, repeats={repeat_count}/{tracker.config.max_repeats}, "
                    f"window={tracker.config.ttl_seconds}s, "
                    f"mode={tracker.config.mode.value}"
                )

                # Raise an error to stop the response
                raise ToolCallLoopError(
                    message=f"Tool call loop detected: {reason}",
                    details={
                        "tool_name": tool_name,
                        "repetitions": repeat_count,
                        "mode": tracker.config.mode.value,
                    },
                )

        # Mark tool calls as processed
        self._mark_tool_calls_processed(tool_calls)

        return content

    def reset(self) -> None:
        """Reset tool call tracking state for new stream."""
        self._session_trackers.clear()
        self._session_order.clear()
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
            except Exception as e:
                self._logger.warning(
                    f"Failed to construct LoopDetectionConfiguration: {e}"
                )
                return None

        return None

    def _get_or_create_tracker(
        self, session_id: str, config: LoopDetectionConfiguration
    ) -> ToolCallTracker:
        """Get or create a tracker for the session.

        Args:
            session_id: The session identifier
            config: The loop detection configuration

        Returns:
            ToolCallTracker for the session
        """
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
                self._logger.warning(
                    "Invalid tool loop mode '%s' provided; falling back to break mode.",
                    mode_value,
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
        while len(self._session_trackers) > self._max_cached_sessions:
            # Remove oldest session (first in order list)
            if self._session_order:
                evicted_session_id = self._session_order.pop(0)
                self._session_trackers.pop(evicted_session_id, None)
                self._logger.debug(
                    "Evicted tool call tracker for session %s due to cache limit",
                    evicted_session_id,
                )


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
    ) -> None:
        """Initialize the think tags processor.

        Args:
            enabled: Whether the processor is enabled
            streaming_buffer_size: Maximum buffer size for streaming chunks
        """
        self._enabled = enabled
        self._streaming_buffer_size = streaming_buffer_size
        self._logger = logging.getLogger(__name__)

        # Streaming state management
        self._streaming_buffers: dict[str, str] = {}
        self._reasoning_extracted: dict[str, dict[str, Any]] = {}
        self._stream_states: dict[str, str] = {}  # waiting, in_think, post_think
        self._think_tag_lookback = _THINK_TAG_LOOKBACK

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
        self._logger.debug("Think tags processor state reset")

    def _extract_text_content(self, content: str | dict | bytes) -> str:
        """Extract text content for processing.

        Args:
            content: The content to extract text from

        Returns:
            Text content suitable for processing
        """
        if isinstance(content, str):
            return content
        elif isinstance(content, bytes):
            try:
                return content.decode("utf-8")
            except UnicodeDecodeError:
                return content.decode("latin-1")
        elif isinstance(content, dict):
            # Extract text from dict (e.g., delta content)
            if "content" in content:
                return str(content["content"])
            return ""
        return str(content)

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

        # Trim the existing buffer when we're not inside a think tag to avoid
        # quadratic growth when processing long streams.
        current_state = self._stream_states[session_id]
        current_buffer = self._streaming_buffers.get(session_id, "")
        if current_state == "waiting" and current_buffer:
            current_buffer = current_buffer[-self._think_tag_lookback :]

        new_buffer = current_buffer + chunk_content
        if len(new_buffer) > self._streaming_buffer_size:
            self._logger.warning(
                "Streaming buffer overflow for session %s, processing as-is", session_id
            )
            result = self._fix_think_tags(new_buffer)
            self._cleanup_session_state(session_id)
            return result

        self._streaming_buffers[session_id] = new_buffer

        if current_state == "waiting":
            if _THINK_OPENING_PATTERN.search(new_buffer):
                self._stream_states[session_id] = "in_think"
                self._logger.debug(
                    "Started think tag detection for session %s", session_id
                )
                if _THINK_CLOSING_PATTERN.search(new_buffer):
                    result_content, reasoning_content = self._fix_think_tags(new_buffer)
                    self._stream_states[session_id] = "post_think"
                    self._streaming_buffers[session_id] = ""
                    return result_content, reasoning_content

                # Keep the buffered reasoning content until we see a closing tag
                return "", None

            # No think tags detected, only keep a short tail for cross-chunk detection
            self._streaming_buffers[session_id] = new_buffer[
                -self._think_tag_lookback :
            ]
            return chunk_content, None

        if current_state == "in_think":
            if _THINK_CLOSING_PATTERN.search(new_buffer):
                result_content, reasoning_content = self._fix_think_tags(new_buffer)
                self._stream_states[session_id] = "post_think"
                self._streaming_buffers[session_id] = ""
                return result_content, reasoning_content

            # Still inside <think>...</think>, keep buffering until we can close it
            return "", None

        if current_state == "post_think":
            # We've already extracted reasoning, reset buffer to avoid growth
            self._streaming_buffers[session_id] = ""
            return chunk_content, None

        return chunk_content, None

    def _fix_think_tags(self, content: str) -> tuple[str, str | None]:
        """Fix improperly formatted <think> tags in content.

        Args:
            content: The original content that may contain improper think tags

        Returns:
            Tuple of (response_content, reasoning_content)
        """
        if not content or not isinstance(content, str):
            return content, None

        # Check if content starts with <think> tag
        if not _THINK_OPENING_PATTERN.match(content):
            return content, None

        # Try to match the full <think>...</think> pattern
        match = _THINK_TAG_PATTERN.match(content)
        if not match:
            # If we have opening <think> but no proper closing, treat entire content as reasoning
            if content.strip().startswith("<think>"):
                # Remove the opening tag and treat rest as reasoning
                reasoning_content = content.replace("<think>", "", 1).strip()
                if reasoning_content.endswith("</think>"):
                    reasoning_content = reasoning_content[:-8].strip()

                self._logger.info(
                    "Fixed incomplete think tags - treating as pure reasoning"
                )
                # Return empty content since this was all reasoning
                return "", reasoning_content
            return content, None

        leading_space, reasoning_content, middle_space, remaining_content = (
            match.groups()
        )

        # Clean up the reasoning content while keeping response whitespace intact
        reasoning_content = reasoning_content.strip() if reasoning_content else ""
        response_content = (
            f"{leading_space}{middle_space}{remaining_content}"
            if remaining_content is not None
            else f"{leading_space}{middle_space}"
        )

        self._logger.info(
            "Fixed improperly formatted think tags - extracted %d chars of reasoning, %d chars of content",
            len(reasoning_content),
            len(response_content),
        )

        return response_content, reasoning_content

    def _cleanup_session_state(self, session_id: str) -> None:
        """Clean up streaming state for a session.

        Args:
            session_id: The session identifier to clean up
        """
        self._streaming_buffers.pop(session_id, None)
        self._stream_states.pop(session_id, None)
        # Keep reasoning_extracted for potential later retrieval

    def _ensure_session_state(self, session_id: str) -> None:
        """Initialize state containers for a session if missing."""
        if session_id not in self._streaming_buffers:
            self._streaming_buffers[session_id] = ""
        if session_id not in self._stream_states:
            self._stream_states[session_id] = "waiting"
        if session_id not in self._reasoning_extracted:
            self._reasoning_extracted[session_id] = {}

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
