from __future__ import annotations

import json
import logging
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
        if content.is_empty and not content.is_done:
            return content  # Nothing to process

        stream_id = get_stream_id(content)
        buffer_state = self._get_buffer_state(stream_id)
        metadata = dict(content.metadata or {})
        detected_tool_calls: list[dict[str, Any]] = []

        chunk_text = self._normalize_chunk_text(content.content)
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

        repaired_result = (
            self.tool_call_repair_service.repair_tool_calls(
                buffer_text, allowed_tools=buffer_state.allowed_tools
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
                    synthetic_calls = (
                        ("<use_mcp_tool", "tool_arguments", "</use_mcp_tool>"),
                        ("<patch_file", "patch_content", "</patch_file>"),
                        ("<execute_command", "command", "</execute_command>"),
                        ("<read_file", "file", "</read_file>"),
                        ("<write_to_file", "content", "</write_to_file>"),
                        (
                            "<ask_followup_question",
                            "question",
                            "</ask_followup_question>",
                        ),
                        ("<attempt_completion", "result", "</attempt_completion>"),
                        ("<list_files", "directory", "</list_files>"),
                        ("<search_files", "regex", "</search_files>"),
                        ("<codebase_search", "query", "</codebase_search>"),
                        ("<access_mcp_resource", "uri", "</access_mcp_resource>"),
                    )
                    handled = False
                    for outer_opener, inner_tag, outer_closer in synthetic_calls:
                        if (
                            outer_opener in buffer_text
                            and outer_closer not in buffer_text
                        ):
                            # Build synthetic buffer with both inner and outer closing tags
                            synthetic_buffer = buffer_text
                            inner_opener = f"<{inner_tag}>"
                            inner_closer = f"</{inner_tag}>"
                            # If inner tag is opened but not closed, close it first
                            if (
                                inner_opener in synthetic_buffer
                                and inner_closer not in synthetic_buffer
                            ):
                                synthetic_buffer = synthetic_buffer + inner_closer
                            # Always add outer closer
                            synthetic_buffer = synthetic_buffer + outer_closer

                            repaired_result = (
                                self.tool_call_repair_service.repair_tool_calls(
                                    synthetic_buffer
                                )
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
                                    if suffix.strip():
                                        repaired_content_parts.append(suffix)
                                handled = True
                                buffer_text = ""
                                break
                    if not handled and buffer_text:
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
                    markers = (
                        "<use_mcp_tool",
                        "<patch_file",
                        "<execute_command",
                        "<read_file",
                        "<write_to_file",
                        "<ask_followup_question",
                        "<attempt_completion",
                        "<list_files",
                        "<search_files",
                        "<codebase_search",
                        "<access_mcp_resource",
                    )
                    flush_text = ""
                    if not any(
                        marker in buffer_state.pending_text for marker in markers
                    ):
                        flush_text = buffer_state.pending_text
                        buffer_state.pending_text = ""
                    else:
                        flush_text, remainder = self._split_safe_prefix(
                            buffer_state.pending_text
                        )
                        buffer_state.pending_text = remainder

                    if flush_text:
                        repaired_content_parts.append(flush_text)

        if content.is_done or content.is_cancellation:
            self._registry.clear_tool_call_buffer(stream_id)

        new_content_str = "".join(repaired_content_parts)

        if detected_tool_calls:
            logger.debug(
                "ToolCallRepairProcessor captured tool call(s): %s",
                detected_tool_calls,
            )
            metadata.pop("reasoning_content", None)
            metadata.pop("reasoning", None)
            registered_calls = self._register_tool_calls(
                buffer_state, detected_tool_calls
            )
            if registered_calls:
                # Force override backend's finish_reason (e.g., "stop") when tool calls are detected
                # Using direct assignment instead of setdefault to ensure clients recognize tool calls
                metadata["finish_reason"] = "tool_calls"
                # Add index field to each tool call for OpenAI streaming format compliance
                sanitized_calls = [
                    self._sanitize_tool_call_for_metadata(call, index=idx)
                    for idx, call in enumerate(registered_calls)
                ]
                existing_calls = metadata.get("tool_calls")
                if isinstance(existing_calls, list) and existing_calls:
                    metadata["tool_calls"] = existing_calls + sanitized_calls
                else:
                    metadata["tool_calls"] = sanitized_calls
                # CRITICAL: Clear content when tool_calls are emitted
                # OpenAI streaming format requires content to be absent/null in
                # chunks with tool_calls. Clients like Kilo-Code fail if both present.
                new_content_str = ""
        elif has_reasoning:
            reasoning_value = reasoning_segments[-1]
            metadata.setdefault("reasoning_content", reasoning_value)
            metadata.setdefault("reasoning", reasoning_value)

        if new_content_str or detected_tool_calls or content.is_done:
            return StreamingContent(
                content=new_content_str,
                is_done=content.is_done,
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

    def _split_safe_prefix(self, buffer: str) -> tuple[str, str]:
        """
        Flush most of the buffer while keeping a small suffix to detect tool markers
        that may span chunk boundaries.
        """
        if not buffer:
            return "", ""

        # Must match the markers used in process() to prevent premature flushing
        markers = (
            "<use_mcp_tool",
            "<patch_file",
            "<execute_command",
            "<read_file",
            "<write_to_file",
            "<ask_followup_question",
            "<attempt_completion",
            "<list_files",
            "<search_files",
            "<codebase_search",
            "<access_mcp_resource",
        )
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
            try:
                return json.dumps(chunk)
            except (TypeError, ValueError):
                return str(chunk)
        return str(chunk)

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
