from __future__ import annotations

import json
import logging
import re
from copy import deepcopy
from typing import Any

from src.core.domain.streaming_response_processor import (
    IStreamProcessor,
    StreamingContent,
)
from src.core.interfaces.tool_call_repair_service_interface import (
    IToolCallRepairService,
)
from src.core.services.streaming.stream_context_registry import (
    StreamingContextRegistry,
    ToolCallBufferState,
)
from src.core.services.streaming.stream_utils import get_stream_id
from src.tool_call_loop.lifecycle_registry import build_tool_call_signature

logger = logging.getLogger(__name__)


class ToolCallRepairProcessor(IStreamProcessor):
    """
    Stream processor that uses ToolCallRepairService to detect and repair
    tool calls within streaming content.
    """

    def __init__(
        self,
        tool_call_repair_service: IToolCallRepairService,
        *,
        max_buffer_bytes: int | None = None,
        registry: StreamingContextRegistry | None = None,
    ) -> None:
        self.tool_call_repair_service = tool_call_repair_service
        service_cap = getattr(tool_call_repair_service, "max_buffer_bytes", None)
        if max_buffer_bytes is not None:
            self._max_buffer_bytes = max_buffer_bytes
        elif isinstance(service_cap, int):
            self._max_buffer_bytes = service_cap
        else:
            self._max_buffer_bytes = 64 * 1024

        self._registry = registry or StreamingContextRegistry()

    async def process(self, content: StreamingContent) -> StreamingContent:
        """
        Processes a streaming content chunk, attempting to repair tool calls.
        """
        # If backend already provided structured tool calls, pass through.
        if content.metadata.get("tool_calls"):
            return content

        if content.is_empty and not content.is_done:
            return content  # Nothing to process

        stream_id = get_stream_id(content)
        buffer_state = self._get_buffer_state(stream_id)
        metadata = dict(content.metadata or {})
        is_done = content.is_done
        detected_tool_calls: list[dict[str, Any]] = []

        existing_calls = self._register_existing_tool_calls(buffer_state, metadata)

        chunk_text = self._normalize_chunk_text(content.content)
        if buffer_state.allowed_tools or buffer_state.allowed_tools is None:
            self._track_open_tags(buffer_state, chunk_text)
        reasoning_segments: list[str] = []
        for key in ("reasoning_content", "reasoning"):
            value = metadata.get(key)
            if isinstance(value, str) and value:
                reasoning_segments.append(value)

        has_reasoning = bool(reasoning_segments)

        if reasoning_segments:
            buffer_state.pending_text += "".join(reasoning_segments)

        if chunk_text:
            buffer_state.pending_text += chunk_text

        repaired_content_parts: list[str] = []
        buffer_text = buffer_state.pending_text

        allowed_tool_list = (
            buffer_state.allowed_tools
            if buffer_state.allowed_tools is not None
            else None
        )

        repaired_result = (
            self.tool_call_repair_service.repair_tool_calls(
                buffer_text, allowed_tools=allowed_tool_list
            )
            if buffer_text
            else None
        )
        if repaired_result:
            detected_tool_calls.append(repaired_result.tool_call)
            snippet = repaired_result.snippet
            if snippet:
                idx = buffer_text.find(snippet)
                if idx != -1:
                    prefix = buffer_text[:idx]
                    suffix = buffer_text[idx + len(snippet) :]
                    if prefix.strip():
                        repaired_content_parts.append(prefix)
                    # Keep XML in content for virtual tool calling clients (KiloCode, Cline, etc.)
                    # that parse tool calls from content rather than using native tool_calls.
                    repaired_content_parts.append(snippet)
                    buffer_text = suffix
            buffer_state.pending_text = buffer_text
            if content.is_done and buffer_state.pending_text:
                repaired_content_parts.append(buffer_state.pending_text)
                buffer_state.pending_text = ""
        else:
            if content.is_done:
                if buffer_text:
                    # Known XML tool tags that need synthetic closing when truncated
                    # IMPORTANT: Include ALL tools that use XML format to prevent
                    # incorrect parsing of inner tags (e.g., <command> inside <execute_command>)
                    # Format: (outer_opener, inner_tag, outer_closer)
                    # inner_tag is used to close truncated inner tags before closing outer
                    synthetic_closing = self._build_synthetic_closing(buffer_text)
                    synthetic_buffer = buffer_text + synthetic_closing

                    repaired_result = self.tool_call_repair_service.repair_tool_calls(
                        synthetic_buffer, allowed_tools=allowed_tool_list
                    )
                    if repaired_result:
                        detected_tool_calls.append(repaired_result.tool_call)
                        snippet = repaired_result.snippet
                        if snippet:
                            idx = synthetic_buffer.find(snippet)
                            prefix = synthetic_buffer[:idx]
                            suffix = synthetic_buffer[idx + len(snippet) :]
                            if prefix.strip():
                                repaired_content_parts.append(prefix)
                            # Keep XML in content for virtual tool calling
                            repaired_content_parts.append(snippet)
                            if suffix.strip():
                                repaired_content_parts.append(suffix)
                        buffer_text = ""
                    elif buffer_text:
                        repaired_content_parts.append(buffer_text)
                buffer_state.pending_text = ""
            else:
                trimmed = self._trim_buffer(buffer_text)
                if trimmed:
                    repaired_content_parts.append(trimmed)
                    buffer_state.pending_text = buffer_state.pending_text[
                        len(trimmed) :
                    ]

                should_flush_streaming = (
                    not has_reasoning and self._max_buffer_bytes > 1024
                )
                if should_flush_streaming:
                    # Markers for XML tool tags that should NOT be flushed prematurely
                    # Must match the tags in synthetic_calls above
                    markers = self._build_markers(buffer_state)
                    flush_text = ""
                    if not any(
                        marker in buffer_state.pending_text for marker in markers
                    ):
                        flush_text = buffer_state.pending_text
                        buffer_state.pending_text = ""
                    else:
                        flush_text, remainder = self._split_safe_prefix(
                            buffer_state.pending_text, buffer_state
                        )
                        buffer_state.pending_text = remainder

                    if flush_text:
                        repaired_content_parts.append(flush_text)

        if content.is_done or content.is_cancellation:
            self._registry.clear_tool_call_buffer(stream_id)

        new_content_str = "".join(repaired_content_parts)

        if detected_tool_calls:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "ToolCallRepairProcessor captured tool call(s): %s",
                    detected_tool_calls,
                )
            # Mark that a tool call has been detected in this stream
            buffer_state.tool_call_detected = True

            metadata.pop("reasoning_content", None)
            metadata.pop("reasoning", None)
            registered_calls = self._register_tool_calls(
                buffer_state, detected_tool_calls
            )
            if registered_calls:
                # Force override backend's finish_reason (e.g., "stop") when tool calls are detected
                # Using direct assignment instead of setdefault to ensure clients recognize tool calls
                metadata["finish_reason"] = "tool_calls"
                # Tool calls are terminal for the current assistant turn; mark the
                # chunk as done so downstream processors (usage, SSE assembler)
                # emit final accounting and end-of-stream markers.
                is_done = True
                # Add index field to each tool call for OpenAI streaming format compliance
                sanitized_calls = self._sanitize_and_dedupe_tool_calls(
                    existing_calls, registered_calls, buffer_state
                )
                if sanitized_calls:
                    metadata["tool_calls"] = sanitized_calls
                    # Mark these as "virtual" tool calls (extracted from XML content).
                    # This flag signals downstream processors to strip tool_calls from
                    # the final response for clients that expect XML-only (virtual mode).
                    # The XML content is preserved, and tool_calls are used internally
                    # for unified processing, then removed before client delivery.
                    metadata["_virtual_tool_calls"] = True
        elif has_reasoning:
            reasoning_value = reasoning_segments[-1]
            metadata.setdefault("reasoning_content", reasoning_value)
            metadata.setdefault("reasoning", reasoning_value)

        if is_done or content.is_cancellation:
            self._registry.clear_tool_call_buffer(stream_id)

        if new_content_str or detected_tool_calls or is_done:
            return StreamingContent(
                content=new_content_str,
                is_done=is_done,
                is_cancellation=content.is_cancellation,
                metadata=metadata,
                usage=content.usage,
                raw_data=content.raw_data,
            )

        return StreamingContent(
            content="",
            is_cancellation=content.is_cancellation,
            metadata=metadata,
            usage=content.usage,
            raw_data=content.raw_data,
        )  # Return empty if nothing to yield

    def reset(self) -> None:
        """Reset buffer state for a fresh stream."""
        # Clear tracked tags and pending text for all streams
        self._registry.reset()

    def _trim_buffer(self, buffer: str) -> str:
        """Flush enough leading content to honor the buffer cap."""

        if not buffer:
            return ""

        encoded_length = len(buffer.encode("utf-8"))
        if encoded_length <= self._max_buffer_bytes:
            return ""

        overflow = encoded_length - self._max_buffer_bytes
        flushed_chars = []
        consumed = 0

        for ch in buffer:
            char_bytes = len(ch.encode("utf-8"))
            flushed_chars.append(ch)
            consumed += char_bytes
            if consumed >= overflow:
                break

        flush_text = "".join(flushed_chars)

        logger.warning(
            "ToolCallRepairProcessor buffer exceeded %d bytes; flushed %d characters",
            self._max_buffer_bytes,
            len(flush_text),
        )

        return flush_text

    def _split_safe_prefix(
        self, buffer: str, buffer_state: ToolCallBufferState
    ) -> tuple[str, str]:
        """
        Flush most of the buffer while keeping a small suffix to detect tool markers
        that may span chunk boundaries.
        """
        if not buffer:
            return "", ""

        markers = self._build_markers(buffer_state)
        positions = [buffer.find(marker) for marker in markers if marker in buffer]
        if positions:
            marker_pos = min(pos for pos in positions if pos >= 0)
            if marker_pos <= 0:
                return "", buffer
            return buffer[:marker_pos], buffer[marker_pos:]

        max_marker = max(len(marker) for marker in markers)
        if len(buffer) <= max_marker:
            return "", buffer

        flush_len = len(buffer) - max_marker
        return buffer[:flush_len], buffer[flush_len:]

    @staticmethod
    def _normalize_chunk_text(chunk: Any) -> str:
        """Convert arbitrary chunk payloads into a text buffer."""
        if chunk is None:
            return ""
        if isinstance(chunk, str):
            return chunk
        if isinstance(chunk, bytes | bytearray):
            return chunk.decode("utf-8", errors="ignore")
        if isinstance(chunk, dict):
            # Special-case OpenAI-style chunks to extract the plain textual delta
            # instead of JSON-encoding the entire payload (which escapes XML).
            choices = chunk.get("choices")
            if isinstance(choices, list) and choices:
                first_choice = choices[0]
                if isinstance(first_choice, dict):
                    delta = first_choice.get("delta") or {}
                    if isinstance(delta, dict):
                        text_parts: list[str] = []
                        # Preserve both tool_call text (if any) and regular content
                        for key in (
                            "content",
                            "_tool_call_text",
                            "reasoning_content",
                            "reasoning",
                        ):
                            value = delta.get(key)
                            if isinstance(value, str) and value:
                                text_parts.append(value)
                        if text_parts:
                            return "".join(text_parts)
                    message = first_choice.get("message") or {}
                    if isinstance(message, dict):
                        message_content = message.get("content")
                        if isinstance(message_content, str):
                            return message_content
            try:
                return json.dumps(chunk)
            except (TypeError, ValueError):
                return str(chunk)
        return str(chunk)

    def _track_open_tags(self, buffer_state: ToolCallBufferState, text: str) -> None:
        """Discover and track open tag names for dynamic buffering.

        Handles both complete tags (e.g., '<execute_command>') and partial tags
        that may be split across streaming chunks (e.g., '<execute' followed by
        '_command>' in the next chunk).
        """
        if not text:
            return
        disallowed_tags = {"think", "thought"}

        # Track complete tags: <tagname followed by whitespace, >, or /
        for match in re.finditer(r"<([A-Za-z0-9_\-]+)(?=[\s>/])", text):
            tag = match.group(1)
            if text[match.start() + 1] == "/":
                continue
            tail = text[match.end() : match.end() + 2]
            if tail.startswith("/"):
                continue  # self-closing
            if tag.lower() in disallowed_tags and not buffer_state.allowed_tools:
                continue
            buffer_state.tracked_tags.add(tag)

        # Also track partial tags at end of chunk that may continue in next chunk
        # e.g., '<execute' at end of chunk, followed by '_command>' in next chunk
        partial_match = re.search(r"<([A-Za-z0-9_\-]+)$", text)
        if partial_match:
            tag = partial_match.group(1)
            if tag.lower() not in disallowed_tags or buffer_state.allowed_tools:
                buffer_state.tracked_tags.add(tag)

    def _build_markers(self, buffer_state: ToolCallBufferState) -> tuple[str, ...]:
        """Build dynamic markers from allowed tools and observed tags."""
        tags = {
            tag
            for tag in buffer_state.tracked_tags
            if tag.lower() not in {"think", "thought"}
        }
        if buffer_state.allowed_tools:
            tags.update(buffer_state.allowed_tools)
        return tuple(f"<{tag}" for tag in tags if tag)

    def _build_synthetic_closing(self, text: str) -> str:
        """Create synthetic closing tags for any unclosed tags in the buffer."""
        if not text:
            return ""

        tag_pattern = re.compile(r"</?([A-Za-z0-9_\-]+)(?=[\\s>/])")
        stack: list[str] = []
        for match in tag_pattern.finditer(text):
            tag = match.group(1)
            is_close = text[match.start() + 1] == "/"
            if is_close:
                # Pop matching tag if present
                for idx in range(len(stack) - 1, -1, -1):
                    if stack[idx] == tag:
                        stack = stack[:idx]
                        break
            else:
                tail = text[match.end() : match.end() + 2]
                if tail.startswith("/"):
                    continue  # self closing
                stack.append(tag)

        return "".join(f"</{tag}>" for tag in reversed(stack))

    def _get_buffer_state(self, stream_id: str) -> ToolCallBufferState:
        return self._registry.get_tool_call_buffer(stream_id)

    @staticmethod
    def _sanitize_tool_call_for_metadata(
        tool_call: dict[str, Any], index: int = 0
    ) -> dict[str, Any]:
        cloned = deepcopy(tool_call)
        cloned.pop("_already_processed", None)
        # Add index field for OpenAI streaming format compliance
        # Clients like Kilo-Code require this field to properly identify tool calls
        cloned["index"] = index
        return cloned

    def _register_tool_calls(
        self,
        buffer_state: ToolCallBufferState,
        tool_calls: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Register new tool calls in shared state, deduplicating by signature."""

        new_calls: list[dict[str, Any]] = []
        for call in tool_calls:
            signature = build_tool_call_signature(call)
            canonical_id = self._build_canonical_id(call, signature)
            if canonical_id in buffer_state.detected_canonical_ids:
                continue
            buffer_state.detected_canonical_ids.add(canonical_id)
            buffer_state.detected_signatures.add(signature)
            buffer_state.detected_calls.append(call)
            call.setdefault("_already_processed", False)
            new_calls.append(call)
        return new_calls

    def _register_existing_tool_calls(
        self, buffer_state: ToolCallBufferState, metadata: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Deduplicate and register any tool calls already present in metadata."""

        existing_calls_raw = metadata.get("tool_calls")
        if not isinstance(existing_calls_raw, list) or not existing_calls_raw:
            return []

        unique_calls: list[dict[str, Any]] = []
        seen_signatures: set[str] = set()
        for call in existing_calls_raw:
            if not isinstance(call, dict):
                continue
            dedupe_signature = self._compute_dedupe_signature(call)
            if dedupe_signature in seen_signatures:
                continue
            seen_signatures.add(dedupe_signature)

            signature = self._build_canonical_id(call, dedupe_signature)
            if signature in buffer_state.detected_canonical_ids:
                continue

            buffer_state.detected_canonical_ids.add(signature)
            buffer_state.detected_signatures.add(dedupe_signature)
            buffer_state.detected_calls.append(call)
            unique_calls.append(call)

        sanitized = [
            self._sanitize_tool_call_for_metadata(call, index=idx)
            for idx, call in enumerate(unique_calls)
        ]
        metadata["tool_calls"] = sanitized
        return sanitized

    def _sanitize_and_dedupe_tool_calls(
        self,
        existing_calls: list[dict[str, Any]],
        new_calls: list[dict[str, Any]],
        buffer_state: ToolCallBufferState,
    ) -> list[dict[str, Any]]:
        """Merge tool calls while removing duplicates by canonical signature."""

        merged: list[dict[str, Any]] = []
        seen: set[str] = set()

        def _add(call: dict[str, Any]) -> None:
            dedupe_signature = self._compute_dedupe_signature(call)
            if dedupe_signature in seen:
                return
            seen.add(dedupe_signature)
            signature = self._build_canonical_id(call, dedupe_signature)
            buffer_state.detected_canonical_ids.add(signature)
            buffer_state.detected_signatures.add(dedupe_signature)
            merged.append(call)

        for call in existing_calls:
            _add(call)
        for call in new_calls:
            _add(call)

        return [
            self._sanitize_tool_call_for_metadata(call, index=idx)
            for idx, call in enumerate(merged)
        ]

    @staticmethod
    def _build_canonical_id(call: dict[str, Any], fallback_signature: str) -> str:
        identifier = call.get("id")
        if isinstance(identifier, str) and identifier:
            return identifier
        function_block = call.get("function")
        if isinstance(function_block, dict):
            name = function_block.get("name")
            if isinstance(name, str) and name:
                return name
        return fallback_signature

    @staticmethod
    def _compute_dedupe_signature(call: dict[str, Any]) -> str:
        """Compute a stable signature for deduplication, ignoring explicit ids."""
        stripped = dict(call)
        stripped.pop("id", None)
        return build_tool_call_signature(stripped)
