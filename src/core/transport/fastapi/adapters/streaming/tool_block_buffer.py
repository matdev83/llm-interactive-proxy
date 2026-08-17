"""Tool block buffering for streaming responses.

This module contains the ToolBlockBuffer class for buffering multiline tool blocks
across streaming chunks until complete blocks are detected.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from src.core.services.streaming.stream_context_registry import (
        StreamingContextRegistry,
    )

logger = logging.getLogger(__name__)


class TagSegments(NamedTuple):
    """Result of splitting a buffer into complete and pending segments.

    Attributes:
        complete_segments: The portion of the buffer with complete tag pairs
        pending_tail: The incomplete portion of the buffer waiting for more data
    """

    complete_segments: str
    pending_tail: str


class ToolBlockBuffer:
    """Buffer multiline tool blocks across streaming chunks.

    Holds partial tool blocks until closing tag is detected, then emits
    complete blocks. Tracks detected tags via streaming context registry.
    """

    def __init__(
        self,
        registry: StreamingContextRegistry | None = None,
    ) -> None:
        """Initialize tool block buffer.

        Args:
            registry: Optional StreamContextRegistry instance.
                     If not provided, falls back to global accessor.
        """
        self._registry = registry

    def buffer(self, content: str, stream_id: str | None) -> str:
        """Buffer content, returning complete blocks only.

        Args:
            content: Content to buffer
            stream_id: Optional stream identifier

        Returns:
            Complete tool blocks (empty string if none complete)
        """
        if not content:
            return ""

        stream_key = stream_id or "anonymous-stream"
        registry = self._get_registry()

        # Update tracked tags first (even if no target tags yet)
        self._update_tracked_tags(stream_key, content, registry)

        # Get target tags for this stream
        target_tags = self._get_target_tags(stream_key, content, registry)

        if not target_tags:
            # Check if we have partial tags that need buffering
            # Detect partial opening tags (e.g., "<read_file" without closing)
            partial_tags = self._detect_partial_tags(content, registry, stream_key)
            if partial_tags:
                # Buffer partial tags
                updated_text = content
                for tag in partial_tags:
                    updated_text = self._apply_tag_buffer(
                        stream_key, tag, updated_text, registry
                    )
                # If all content was buffered, return empty
                return updated_text if updated_text else ""
            # No tags to process, return content as-is
            return content

        # Process each tag
        updated_text = content
        for tag in target_tags:
            updated_text = self._apply_tag_buffer(
                stream_key, tag, updated_text, registry
            )

        # If all content was buffered (pending), return empty string
        # This happens when we have partial tags that couldn't be emitted
        if not updated_text:
            return ""

        return updated_text

    def flush(self, stream_id: str | None) -> str:
        """Flush any pending content.

        Args:
            stream_id: Optional stream identifier

        Returns:
            All pending buffered content
        """
        stream_key = stream_id or "anonymous-stream"
        registry = self._get_registry()

        # Get all target tags (including those not in current content)
        target_tags = self._get_target_tags(stream_key, None, registry)

        if not target_tags:
            return ""

        # Collect all pending fragments
        pending_fragments: list[str] = []
        for tag in target_tags:
            buffer_key = f"tool-block:{tag}"
            fragment = registry.get_fragment(stream_key, buffer_key)
            if fragment:
                pending_fragments.append(fragment)
                registry.clear_fragment(stream_key, buffer_key)

        if not pending_fragments:
            return ""

        return "".join(pending_fragments)

    def reset(self, stream_id: str | None) -> None:
        """Reset buffer state for a stream.

        Args:
            stream_id: Optional stream identifier
        """
        stream_key = stream_id or "anonymous-stream"
        registry = self._get_registry()

        # Get all target tags
        target_tags = self._get_target_tags(stream_key, None, registry)

        # Clear all fragments for this stream
        for tag in target_tags:
            buffer_key = f"tool-block:{tag}"
            registry.clear_fragment(stream_key, buffer_key)

        try:
            buffer_state = registry.get_tool_call_buffer(stream_key)
            buffer_state.tracked_tags.clear()
        except (KeyError, ValueError):
            pass

    def _get_registry(self) -> StreamingContextRegistry:
        """Get registry instance (DI or fallback).

        Returns:
            StreamingContextRegistry instance
        """
        if self._registry is not None:
            return self._registry

        from src.core.services.streaming.stream_context_registry import (
            get_global_streaming_context_registry,
        )

        return get_global_streaming_context_registry()

    def _split_tag_segments(self, buffer: str, tag_name: str) -> TagSegments:
        """Split buffer into complete segments and pending tail.

        Args:
            buffer: Buffer content
            tag_name: Tag name to split on

        Returns:
            TagSegments with complete_segments and pending_tail
        """
        if not buffer:
            return TagSegments("", "")

        parts: list[str] = []
        idx = 0
        length = len(buffer)
        pending_tail = ""
        open_tag = f"<{tag_name}"
        close_tag = f"</{tag_name}>"

        while idx < length:
            start = buffer.find(open_tag, idx)
            if start == -1:
                parts.append(buffer[idx:])
                pending_tail = ""
                break

            if start > idx:
                parts.append(buffer[idx:start])

            end = buffer.find(close_tag, start)
            if end == -1:
                pending_tail = buffer[start:]
                break

            end += len(close_tag)
            parts.append(buffer[start:end])
            idx = end

            if idx >= length:
                pending_tail = ""
                break

        return TagSegments("".join(parts), pending_tail)

    def _update_tracked_tags(
        self,
        stream_key: str,
        text_value: str,
        registry: StreamingContextRegistry,
    ) -> list[str]:
        """Update tracked tags in registry.

        Args:
            stream_key: Stream identifier
            text_value: Text content to scan for tags
            registry: Registry instance

        Returns:
            List of detected tags
        """
        tags: list[str] = []
        try:
            buffer_state = registry.get_tool_call_buffer(stream_key)
            allowed_tools = buffer_state.allowed_tools
            allowed_set = {t.lower() for t in allowed_tools} if allowed_tools else None
            disallowed_tags = (
                {"think", "thought"} if not buffer_state.allowed_tools else set()
            )
        except (KeyError, ValueError) as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Failed to get tool call buffer state for stream %s, using default disallowed tags: %s",
                    stream_key,
                    e,
                    exc_info=True,
                )
            buffer_state = None
            allowed_set = None
            disallowed_tags = {"think", "thought"}

        if not text_value:
            return tags

        # Find opening tags (not closing tags, not self-closing)
        # Pattern matches: <tag_name where tag_name MUST start with a letter or underscore
        # followed by space, >, /, or end of string (to avoid matching <-- or <- or <3)
        for match in re.finditer(
            r"<([A-Za-z_][A-Za-z0-9_\-]*)(?=[\s>/]|$)", text_value
        ):
            tag = match.group(1)
            # Skip closing tags (check if previous char is /)
            if match.start() > 0 and text_value[match.start() - 1] == "/":
                continue
            # Skip self-closing tags (check if next char after tag name is /)
            tail_start = match.end()
            if (
                tail_start < len(text_value)
                and text_value[tail_start : tail_start + 1] == "/"
            ):
                continue
            # If allowed_tools is explicitly configured, only track allowed tools
            if allowed_set is not None:
                if tag.lower() not in allowed_set:
                    continue
            else:
                # Skip disallowed tags when allowed_tools is not configured
                if tag.lower() in disallowed_tags:
                    continue
            tags.append(tag)

        if buffer_state is not None and tags:
            buffer_state.tracked_tags.update(tags)

        return tags

    def _get_target_tags(
        self,
        stream_key: str,
        text_value: str | None,
        registry: StreamingContextRegistry,
    ) -> tuple[str, ...]:
        """Get target tool tags using allowed tools and observed tags.

        Args:
            stream_key: Stream identifier
            text_value: Optional text content to scan
            registry: Registry instance

        Returns:
            Tuple of target tag names in priority order
        """
        try:
            buffer_state = registry.get_tool_call_buffer(stream_key)
            allowed = list(buffer_state.allowed_tools or [])
            allowed_set = {t.lower() for t in allowed} if allowed else None
            tracked = list(buffer_state.tracked_tags)
            disallowed_tags = (
                {"think", "thought"} if not buffer_state.allowed_tools else set()
            )
        except (KeyError, ValueError) as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Failed to get tool call buffer state for stream %s, using defaults: %s",
                    stream_key,
                    e,
                    exc_info=True,
                )
            allowed = []
            allowed_set = None
            tracked = []
            disallowed_tags = {"think", "thought"}

        # Filter tracked tags by allowed_set if allowed_tools is configured
        if allowed_set is not None:
            tracked = [t for t in tracked if t.lower() in allowed_set]

        ordered_tags: list[str] = []

        # Get observed tags from text (tags are already tracked by buffer() method)
        observed_in_text: list[str] = []
        if text_value:
            for match in re.finditer(
                r"<([A-Za-z_][A-Za-z0-9_\-]*)(?=[\s>/])", text_value
            ):
                tag = match.group(1)
                if text_value[match.start() + 1] == "/":
                    continue
                tail = text_value[match.end() : match.end() + 2]
                if tail.startswith("/"):
                    continue
                if allowed_set is not None:
                    if tag.lower() not in allowed_set:
                        continue
                elif tag.lower() in disallowed_tags:
                    continue
                observed_in_text.append(tag)

        # Add tags in priority order: observed -> tracked -> allowed
        for tag in observed_in_text:
            if tag not in ordered_tags:
                ordered_tags.append(tag)

        for tag in tracked:
            if tag not in ordered_tags:
                ordered_tags.append(tag)

        for tag in allowed:
            if tag not in ordered_tags:
                ordered_tags.append(tag)

        return tuple(ordered_tags)

    def _detect_partial_tags(
        self,
        content: str,
        registry: StreamingContextRegistry,
        stream_key: str,
    ) -> list[str]:
        """Detect partial opening tags in content.

        Args:
            content: Content to scan
            registry: Registry instance
            stream_key: Stream identifier

        Returns:
            List of detected tag names
        """
        tags: list[str] = []
        try:
            buffer_state = registry.get_tool_call_buffer(stream_key)
            allowed = list(buffer_state.allowed_tools or [])
            allowed_set = {t.lower() for t in allowed} if allowed else None
            disallowed_tags = (
                {"think", "thought"} if not buffer_state.allowed_tools else set()
            )
        except (KeyError, ValueError) as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Failed to get tool call buffer state for stream %s, using default disallowed tags: %s",
                    stream_key,
                    e,
                    exc_info=True,
                )
            allowed_set = None
            disallowed_tags = {"think", "thought"}

        # Look for opening tags that might be partial
        # Pattern: <tag_name where tag_name MUST start with a letter or underscore
        for match in re.finditer(r"<([A-Za-z_][A-Za-z0-9_\-]*)(?=[\s>/]|$)", content):
            tag = match.group(1)
            # Skip closing tags
            if match.start() > 0 and content[match.start() - 1] == "/":
                continue
            # Skip self-closing tags
            tail_start = match.end()
            if (
                tail_start < len(content)
                and content[tail_start : tail_start + 1] == "/"
            ):
                continue
            if allowed_set is not None:
                if tag.lower() not in allowed_set:
                    continue
            elif tag.lower() in disallowed_tags:
                continue
            # Check if this tag has a closing tag in the content
            close_tag = f"</{tag}>"
            if close_tag not in content:
                # This is a partial tag
                tags.append(tag)

        return tags

    def _apply_tag_buffer(
        self,
        stream_key: str,
        tag_name: str,
        text_value: str,
        registry: StreamingContextRegistry,
    ) -> str:
        """Apply buffering for a specific tag.

        Args:
            stream_key: Stream identifier
            tag_name: Tag name to buffer
            text_value: Text content
            registry: Registry instance

        Returns:
            Text with complete blocks emitted, partial blocks buffered
        """
        MAX_PENDING_BUFFER_BYTES = 16384

        buffer_key = f"tool-block:{tag_name}"
        buffer = registry.get_fragment(stream_key, buffer_key)
        combined = buffer + text_value
        emit_text, pending_tail = self._split_tag_segments(combined, tag_name)

        if pending_tail:
            if len(pending_tail) > MAX_PENDING_BUFFER_BYTES:
                # Buffer has grown excessively without finding a closing tag.
                # Flush it as normal text to prevent withholding stream chunks indefinitely.
                emit_text = emit_text + pending_tail
                registry.clear_fragment(stream_key, buffer_key)
            else:
                registry.set_fragment(stream_key, buffer_key, pending_tail)
        else:
            registry.clear_fragment(stream_key, buffer_key)

        return emit_text
