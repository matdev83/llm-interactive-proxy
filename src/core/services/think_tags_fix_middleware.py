"""
Think tags fix middleware for correcting improperly formatted reasoning tags.

Some models from less known vendors produce <think> </think> tags inside plain message body
instead of using standard conventions to mark reasoning and non-reasoning parts of the output.
This middleware detects and corrects such improperly marked reasoning streams.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any, cast
from uuid import uuid4

from src.core.interfaces.response_processor_interface import (
    IResponseFeature,
    IResponseMiddleware,
    ProcessedResponse,
)

logger = logging.getLogger(__name__)


class ThinkTagsFixFeature(IResponseFeature):
    """Feature to fix think tags with enforced streaming/non-streaming parity.

    This feature detects and corrects improperly formatted <think> tags in model
    responses. Both streaming and non-streaming paths use shared logic where possible.
    """

    _THINK_TAG_PATTERN = re.compile(
        r"^(\s*)<think>(.*?)</think>(\s*)(.*?)$", re.DOTALL | re.IGNORECASE
    )
    _THINK_OPENING_PATTERN = re.compile(r"^(\s*)<think>", re.IGNORECASE)
    _THINK_CLOSING_PATTERN = re.compile(r"</think>", re.IGNORECASE)

    def __init__(
        self,
        enabled: bool = True,
        streaming_buffer_size: int = 4096,
        per_model_config: dict[str, dict[str, Any]] | None = None,
        reasoning_ttl_seconds: int = 300,
        max_reasoning_entries: int = 1000,
        priority: int = 5,
    ) -> None:
        """Initialize the think tags fix feature."""
        super().__init__(priority)
        self._enabled = enabled
        self._streaming_buffer_size = streaming_buffer_size
        self._per_model_config: dict[str, dict[str, Any]] = per_model_config or {}
        self._logger = logging.getLogger(__name__)
        self._reasoning_ttl_seconds = reasoning_ttl_seconds
        self._max_reasoning_entries = max_reasoning_entries

        # State management
        self._streaming_buffers: dict[str, str] = {}
        self._reasoning_extracted: dict[str, dict[str, Any]] = {}
        self._stream_states: dict[str, str] = {}
        self._session_aliases: dict[str, str] = {}

    def _should_process_for_model(self, backend: str | None, model: str | None) -> bool:
        """Determine if think tags fix should be enabled for a specific model."""
        if not backend or not model:
            return self._enabled

        backend_model_key = f"{backend}:{model}"
        if backend_model_key in self._per_model_config:
            config = self._per_model_config[backend_model_key]
            return bool(config.get("enabled", False))

        if model in self._per_model_config:
            config = self._per_model_config[model]
            return bool(config.get("enabled", False))

        return self._enabled

    def _resolve_session_id(
        self,
        session_id: str,
        context: dict[str, Any],
        processed_response: ProcessedResponse,
    ) -> str:
        """Resolve stable session identifier."""
        fallback_context = context or {}
        resolved_session_id = session_id or fallback_context.get("stream_id")

        if not resolved_session_id and hasattr(processed_response, "metadata"):
            metadata = getattr(processed_response, "metadata", {})
            if isinstance(metadata, dict):
                resolved_session_id = metadata.get("stream_id") or metadata.get(
                    "session_id"
                )

        if not resolved_session_id:
            resolved_session_id = fallback_context.setdefault(
                "_think_tags_session_id", uuid4().hex
            )
        else:
            resolved_session_id = str(resolved_session_id)
            fallback_context.setdefault("_think_tags_session_id", resolved_session_id)

        if session_id and session_id != resolved_session_id:
            self._session_aliases[session_id] = resolved_session_id
        elif not session_id:
            self._session_aliases.setdefault(session_id, resolved_session_id)

        return str(resolved_session_id)

    def _ensure_processed_response(self, response: Any) -> ProcessedResponse:
        """Ensure response is a ProcessedResponse."""
        if isinstance(response, ProcessedResponse):
            return response

        content = ""
        if hasattr(response, "content"):
            raw_content = response.content
            if isinstance(raw_content, str):
                content = raw_content
            elif raw_content is not None:
                content = str(raw_content)
        elif isinstance(response, dict):
            raw_content = response.get("content")
            if isinstance(raw_content, str):
                content = raw_content
            elif raw_content is not None:
                content = str(raw_content)
        elif isinstance(response, str):
            content = response
        elif response is not None:
            content = str(response)

        metadata = None
        if hasattr(response, "metadata"):
            raw_metadata = response.metadata
            if isinstance(raw_metadata, dict):
                metadata = raw_metadata
        elif isinstance(response, dict):
            raw_metadata = response.get("metadata")
            if isinstance(raw_metadata, dict):
                metadata = raw_metadata

        return ProcessedResponse(
            content=content,
            usage=getattr(response, "usage", None),
            metadata=metadata,
        )

    def _fix_think_tags(self, content: str) -> tuple[str, str | None]:
        """Fix think tags in content (non-streaming)."""
        if not content or not isinstance(content, str):
            return content, None

        match = self._THINK_TAG_PATTERN.match(content)
        if match:
            leading_ws = match.group(1)
            reasoning = match.group(2).strip()
            middle_ws = match.group(3)
            remaining = match.group(4).strip()
            fixed_content = f"{leading_ws}{middle_ws}{remaining}".strip()
            return fixed_content, reasoning

        return content, None

    def _process_streaming_chunk(
        self,
        content: str,
        session_id: str,
        is_streaming: bool = True,
        context: dict[str, Any] | None = None,
    ) -> tuple[str, dict[str, Any] | None]:
        """Process a streaming chunk for think tags."""
        if not content or not isinstance(content, str):
            return content, None

        current_buffer = self._streaming_buffers.get(session_id, "")
        current_buffer += content
        self._streaming_buffers[session_id] = current_buffer

        state = self._stream_states.get(session_id, "initial")

        if state == "initial":
            opening_match = self._THINK_OPENING_PATTERN.match(current_buffer)
            if opening_match:
                self._stream_states[session_id] = "in_think"
                return "", None
            elif "<think" in current_buffer.lower() and len(current_buffer) < 20:
                return "", None

        if state == "in_think":
            closing_match = self._THINK_CLOSING_PATTERN.search(current_buffer)
            if closing_match:
                reasoning_end = closing_match.start()
                reasoning = current_buffer[:reasoning_end]
                after_close = current_buffer[closing_match.end() :]

                opening_match = self._THINK_OPENING_PATTERN.match(current_buffer)
                if opening_match:
                    reasoning = reasoning[opening_match.end() :]

                reasoning = reasoning.strip()
                self._stream_states[session_id] = "after_think"
                self._streaming_buffers[session_id] = after_close

                reasoning_metadata = {
                    "reasoning": reasoning,
                    "reasoning_content": reasoning,
                    "_created_at": time.time(),
                }
                self._reasoning_extracted[session_id] = reasoning_metadata

                return after_close.strip(), reasoning_metadata

            if len(current_buffer) > self._streaming_buffer_size:
                self._stream_states[session_id] = "pass_through"
                result = current_buffer
                self._streaming_buffers[session_id] = ""
                return result, None

            return "", None

        if state == "after_think" or state == "pass_through":
            self._streaming_buffers[session_id] = ""
            return content, None

        return content, None

    def _format_response_with_reasoning(
        self,
        content: str,
        reasoning: str | dict[str, Any],
        original_response: Any,
    ) -> ProcessedResponse:
        """Format response with extracted reasoning."""
        if isinstance(reasoning, dict):
            reasoning_content = reasoning.get("reasoning") or reasoning.get(
                "reasoning_content", ""
            )
        else:
            reasoning_content = reasoning

        original_metadata = {}
        if hasattr(original_response, "metadata"):
            raw_metadata = original_response.metadata
            if isinstance(raw_metadata, dict):
                original_metadata = dict(raw_metadata)

        metadata = {
            **original_metadata,
            "reasoning": reasoning_content,
            "reasoning_content": reasoning_content,
            "think_tags_extracted": True,
        }

        return ProcessedResponse(
            content=content,
            usage=getattr(original_response, "usage", None),
            metadata=metadata,
        )

    def _process_response(
        self,
        response: Any,
        session_id: str,
        context: dict[str, Any],
        is_streaming: bool,
    ) -> Any:
        """Shared processing logic."""
        backend = context.get("backend")
        model = context.get("model")

        if not self._should_process_for_model(backend, model):
            return response

        processed_response = self._ensure_processed_response(response)

        if not processed_response.content:
            return response

        resolved_session_id = self._resolve_session_id(
            session_id, context, processed_response
        )

        if is_streaming:
            fixed_content, reasoning_metadata = self._process_streaming_chunk(
                processed_response.content,
                resolved_session_id,
                is_streaming=True,
                context=context,
            )

            if reasoning_metadata:
                formatted_response = self._format_response_with_reasoning(
                    fixed_content, reasoning_metadata, response
                )
                if (
                    hasattr(formatted_response, "metadata")
                    and formatted_response.metadata
                ):
                    formatted_response.metadata["streaming_extraction"] = True
                return formatted_response
            elif fixed_content != processed_response.content:
                modified_response = self._ensure_processed_response(response)
                modified_response.content = fixed_content
                return modified_response
            else:
                return response
        else:
            fixed_content, reasoning_content = self._fix_think_tags(
                processed_response.content
            )

            if reasoning_content is not None:
                return self._format_response_with_reasoning(
                    fixed_content, reasoning_content, response
                )

        return response

    async def process_non_streaming(
        self,
        response: Any,
        session_id: str,
        context: dict[str, Any],
    ) -> Any:
        """Process non-streaming response for think tags."""
        return self._process_response(response, session_id, context, is_streaming=False)

    async def process_streaming(
        self,
        chunk: Any,
        session_id: str,
        context: dict[str, Any],
    ) -> Any:
        """Process streaming chunk for think tags."""
        return self._process_response(chunk, session_id, context, is_streaming=True)

    def reset_session(self, session_id: str) -> None:
        """Reset session-specific state."""
        alias = self._session_aliases.pop(session_id, None)
        if alias:
            session_id = alias
        self._streaming_buffers.pop(session_id, None)
        self._stream_states.pop(session_id, None)
        self._reasoning_extracted.pop(session_id, None)

        if self._logger.isEnabledFor(logging.DEBUG):
            self._logger.debug("Reset think tags fix state for session %s", session_id)

    def get_session_reasoning(self, session_id: str) -> dict[str, Any] | None:
        """Get extracted reasoning for a session."""
        data = self._reasoning_extracted.get(session_id)
        if data is None:
            return None
        result = {k: v for k, v in data.items() if not k.startswith("_")}
        return result if result else None


# Legacy middleware kept for backward compatibility during transition
# DEPRECATED: Use ThinkTagsFixFeature instead
class ThinkTagsFixMiddleware(IResponseMiddleware):
    """DEPRECATED: Use ThinkTagsFixFeature instead.

    Legacy middleware to fix improperly formatted <think> tags in model responses.
    This class is kept for backward compatibility only.
    """

    # Pre-compiled regex patterns for performance
    _THINK_TAG_PATTERN = re.compile(
        r"^(\s*)<think>(.*?)</think>(\s*)(.*?)$", re.DOTALL | re.IGNORECASE
    )

    _THINK_OPENING_PATTERN = re.compile(r"^(\s*)<think>", re.IGNORECASE)

    _THINK_CLOSING_PATTERN = re.compile(r"</think>", re.IGNORECASE)

    def __init__(
        self,
        enabled: bool = True,
        streaming_buffer_size: int = 4096,
        per_model_config: dict[str, dict[str, Any]] | None = None,
        reasoning_ttl_seconds: int = 300,
        max_reasoning_entries: int = 1000,
    ) -> None:
        """Initialize the think tags fix middleware.

        Args:
            enabled: Whether the middleware is enabled globally
            streaming_buffer_size: Default maximum buffer size for streaming chunks
            per_model_config: Per-backend/model configuration dict
            reasoning_ttl_seconds: TTL for reasoning entries to prevent data leaks (default: 5 min)
            max_reasoning_entries: Maximum reasoning entries to prevent memory exhaustion
        """
        logger.error(
            "DEPRECATED: ThinkTagsFixMiddleware instantiated. "
            "Use ThinkTagsFixFeature instead for proper streaming/non-streaming parity."
        )
        super().__init__(priority=5)  # Run early in the pipeline
        self._enabled = enabled
        self._streaming_buffer_size = streaming_buffer_size
        self._per_model_config: dict[str, dict[str, Any]] = per_model_config or {}
        self._logger = logging.getLogger(__name__)

        # TTL configuration for reasoning cleanup to prevent cross-session data leaks
        self._reasoning_ttl_seconds = reasoning_ttl_seconds
        self._max_reasoning_entries = max_reasoning_entries

        # Streaming state management
        self._streaming_buffers: dict[str, str] = (
            {}
        )  # Buffer accumulated chunks per session
        self._reasoning_extracted: dict[str, dict[str, Any]] = (
            {}
        )  # Track extracted reasoning per session (with _created_at timestamp)
        self._stream_states: dict[str, str] = {}  # Track streaming state per session
        self._session_aliases: dict[str, str] = {}

    def _should_process_for_model(self, backend: str | None, model: str | None) -> bool:
        """Determine if think tags fix should be enabled for a specific backend/model.

        Args:
            backend: The backend name (e.g., "openai", "anthropic")
            model: The model name (e.g., "gpt-4", "claude-3-sonnet")

        Returns:
            True if think tags fix should be enabled for this backend/model combination
        """
        if not backend or not model:
            return self._enabled

        # Check for exact backend:model match first
        backend_model_key = f"{backend}:{model}"
        if backend_model_key in self._per_model_config:
            config = self._per_model_config[backend_model_key]
            enabled_raw = config.get("enabled", False)
            enabled_flag = bool(enabled_raw)
            return enabled_flag

        # Check for model-only match
        if model in self._per_model_config:
            config = self._per_model_config[model]
            enabled_raw = config.get("enabled", False)
            enabled_flag = bool(enabled_raw)
            return enabled_flag

        # Check for backend-only match
        if backend in self._per_model_config:
            config = self._per_model_config[backend]
            enabled_raw = config.get("enabled", False)
            enabled_flag = bool(enabled_raw)
            return enabled_flag

        # Fall back to global setting
        return self._enabled

    def _get_buffer_size_for_model(self, backend: str | None, model: str | None) -> int:
        """Get the streaming buffer size for a specific backend/model.

        Args:
            backend: The backend name
            model: The model name

        Returns:
            The buffer size to use for this backend/model combination
        """
        if not backend or not model:
            return self._streaming_buffer_size

        # Check for exact backend:model match first
        backend_model_key = f"{backend}:{model}"
        if backend_model_key in self._per_model_config:
            config = self._per_model_config[backend_model_key]
            buffer_raw = config.get(
                "streaming_buffer_size", self._streaming_buffer_size
            )
            buffer_size = int(buffer_raw)
            return buffer_size

        # Check for model-only match
        if model in self._per_model_config:
            config = self._per_model_config[model]
            buffer_raw = config.get(
                "streaming_buffer_size", self._streaming_buffer_size
            )
            buffer_size = int(buffer_raw)
            return buffer_size

        # Check for backend-only match
        if backend in self._per_model_config:
            config = self._per_model_config[backend]
            buffer_raw = config.get(
                "streaming_buffer_size", self._streaming_buffer_size
            )
            buffer_size = int(buffer_raw)
            return buffer_size

        # Fall back to global setting
        return self._streaming_buffer_size

    def _fix_think_tags(self, content: str) -> tuple[str, str | None]:
        """Fix improperly formatted <think> tags in content.

        Args:
            content: The original content that may contain improper think tags

        Returns:
            Tuple of (response_content, reasoning_content) where reasoning_content
            is None if no think tags were found
        """
        if not content or not isinstance(content, str):
            return content, None

        # Check if content starts with <think> tag (the problematic case)
        if not self._THINK_OPENING_PATTERN.match(content):
            return content, None

        # Try to match the full <think>...</think> pattern
        match = self._THINK_TAG_PATTERN.match(content)
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

    def _process_streaming_chunk(
        self,
        chunk_content: str,
        session_id: str,
        is_streaming: bool = False,
        context: dict[str, Any] | None = None,
    ) -> tuple[str, str | None]:
        """Process a streaming chunk and handle think tags that may span multiple chunks.

        Args:
            chunk_content: The content of the current chunk
            session_id: The session identifier
            is_streaming: Whether this is part of a streaming response

        Returns:
            Tuple of (processed_chunk_content, reasoning_metadata)
            reasoning_metadata is None if no reasoning was extracted in this chunk
        """
        if not is_streaming or not chunk_content:
            # For non-streaming, use the regular processing
            fixed_content, reasoning_content = self._fix_think_tags(chunk_content)
            return fixed_content, reasoning_content

        # Initialize session state if needed
        if session_id not in self._streaming_buffers:
            self._streaming_buffers[session_id] = ""
            self._reasoning_extracted[session_id] = {"_created_at": time.time()}
            self._stream_states[session_id] = "waiting"  # waiting, in_think, post_think

        # Cleanup expired reasoning entries to prevent cross-session data leaks
        # NOTE: This must run AFTER buffer initialization to avoid removing aliases
        # for sessions that were just created but not yet added to buffers
        self._cleanup_expired_reasoning()

        current_buffer = self._streaming_buffers[session_id]
        current_state = self._stream_states[session_id]

        # Add chunk to buffer
        new_buffer = current_buffer + chunk_content

        # Get model-specific buffer size
        buffer_size = self._get_buffer_size_for_model(
            context.get("backend") if context else None,
            context.get("model") if context else None,
        )

        # Prevent buffer overflow
        if len(new_buffer) > buffer_size:
            self._logger.warning(
                f"Streaming buffer overflow for session {session_id}, processing as-is"
            )
            # Process what we have and reset
            result = self._process_buffer_content(new_buffer, session_id)
            self._cleanup_session_state(session_id)
            return result, None

        self._streaming_buffers[session_id] = new_buffer

        # State machine for processing think tags across chunks
        if current_state == "waiting":
            # Check if we're starting to see think tags
            if self._THINK_OPENING_PATTERN.search(new_buffer):
                self._stream_states[session_id] = "in_think"
                if self._logger.isEnabledFor(logging.DEBUG):
                    self._logger.debug(
                        f"Started think tag detection for session {session_id}"
                    )
                # Check if we have complete tags in this first chunk
                if self._THINK_CLOSING_PATTERN.search(new_buffer):
                    # Complete tags in single chunk
                    result_content, reasoning_metadata = (
                        self._process_complete_think_buffer(new_buffer, session_id)
                    )
                    self._stream_states[session_id] = "post_think"
                    reasoning_content = (
                        reasoning_metadata.get("reasoning")
                        if reasoning_metadata
                        else None
                    )
                    return result_content, reasoning_content
                else:
                    # Don't output anything yet, we're collecting reasoning
                    return "", None
            else:
                # No think tags detected, output the chunk normally
                return chunk_content, None

        elif current_state == "in_think":
            # We're inside think tags, check if we have a complete set
            if self._THINK_CLOSING_PATTERN.search(new_buffer):
                # We have complete think tags, process the buffer
                result_content, reasoning_metadata = (
                    self._process_complete_think_buffer(new_buffer, session_id)
                )
                self._stream_states[session_id] = "post_think"
                reasoning_content = (
                    reasoning_metadata.get("reasoning") if reasoning_metadata else None
                )
                return result_content, reasoning_content
            else:
                # Still collecting reasoning content, don't output anything
                return "", None

        elif current_state == "post_think":
            # We've already extracted reasoning, just pass through remaining content
            return chunk_content, None

        # Default fallback
        return chunk_content, None

    def _process_complete_think_buffer(
        self, buffer_content: str, session_id: str
    ) -> tuple[str, dict[str, Any]]:
        """Process a buffer that contains complete think tags.

        Args:
            buffer_content: The complete buffer content
            session_id: The session identifier

        Returns:
            Tuple of (response_content, reasoning_metadata)
        """
        fixed_content, reasoning_content = self._fix_think_tags(buffer_content)

        if reasoning_content is not None:
            reasoning_metadata = {
                "reasoning": reasoning_content,
                "reasoning_format": "extracted_from_think_tags",
                "think_tags_fixed": True,
                "reasoning_length": len(reasoning_content),
                "fixed_content_length": len(fixed_content),
                "original_content_length": len(buffer_content),
                "streaming_extraction": True,
            }

            # Store reasoning for this session (with timestamp for TTL cleanup)
            reasoning_metadata["_created_at"] = time.time()
            self._reasoning_extracted[session_id] = reasoning_metadata

            self._logger.info(
                f"Extracted reasoning from streaming buffer for session {session_id}: "
                f"{len(reasoning_content)} chars reasoning, {len(fixed_content)} chars content"
            )

            return fixed_content, reasoning_metadata

        return buffer_content, {}

    def _process_buffer_content(self, buffer_content: str, session_id: str) -> str:
        """Process buffer content when we need to flush it.

        Args:
            buffer_content: The buffer content to process
            session_id: The session identifier

        Returns:
            Processed content
        """
        fixed_content, reasoning_content = self._fix_think_tags(buffer_content)

        if reasoning_content is not None:
            # Store reasoning metadata for later retrieval (with timestamp for TTL cleanup)
            self._reasoning_extracted[session_id] = {
                "reasoning": reasoning_content,
                "reasoning_format": "extracted_from_think_tags",
                "think_tags_fixed": True,
                "streaming_extraction": True,
                "_created_at": time.time(),
            }
            return fixed_content

        return buffer_content

    def _cleanup_session_state(self, session_id: str) -> None:
        """Clean up streaming state for a session.

        Args:
            session_id: The session identifier to clean up
        """
        self._streaming_buffers.pop(session_id, None)
        self._stream_states.pop(session_id, None)
        # Note: reasoning_extracted is kept briefly for potential later retrieval
        # but will be cleaned up by _cleanup_expired_reasoning based on TTL

    def _cleanup_expired_reasoning(self) -> None:
        """Remove expired reasoning entries to prevent cross-session data leaks.

        This is called periodically during streaming processing to ensure
        reasoning data from old sessions doesn't accumulate indefinitely.
        """
        now = time.time()

        # Cleanup expired entries
        expired = [
            session_id
            for session_id, data in self._reasoning_extracted.items()
            if now - data.get("_created_at", 0) > self._reasoning_ttl_seconds
        ]
        for session_id in expired:
            del self._reasoning_extracted[session_id]
        if expired and self._logger.isEnabledFor(logging.DEBUG):
            self._logger.debug("Cleaned up %d expired reasoning entries", len(expired))

        # Enforce max entries limit (remove oldest first)
        if len(self._reasoning_extracted) > self._max_reasoning_entries:
            sorted_entries = sorted(
                self._reasoning_extracted.items(),
                key=lambda x: x[1].get("_created_at", 0),
            )
            to_remove = len(self._reasoning_extracted) - self._max_reasoning_entries
            for session_id, _ in sorted_entries[:to_remove]:
                del self._reasoning_extracted[session_id]
            if to_remove > 0 and self._logger.isEnabledFor(logging.DEBUG):
                self._logger.debug(
                    "Evicted %d oldest reasoning entries due to capacity limit",
                    to_remove,
                )

        # Also cleanup stale session aliases
        stale_aliases = [
            alias
            for alias, target in self._session_aliases.items()
            if target not in self._streaming_buffers
            and target not in self._reasoning_extracted
        ]
        for alias in stale_aliases:
            del self._session_aliases[alias]

    def _get_session_reasoning(self, session_id: str) -> dict[str, Any] | None:
        """Get extracted reasoning for a session.

        Args:
            session_id: The session identifier

        Returns:
            Reasoning metadata if available, None otherwise (excludes internal fields)
        """
        data = self._reasoning_extracted.get(session_id)
        if data is None:
            return None
        # Filter out internal metadata fields
        result = {k: v for k, v in data.items() if not k.startswith("_")}
        # Return None if no actual reasoning data
        return result if result else None

    def _ensure_processed_response(self, response: Any) -> ProcessedResponse:
        """Normalize arbitrary response objects into ProcessedResponse instances."""
        if isinstance(response, ProcessedResponse):
            return response

        content: str = ""
        metadata: dict[str, Any] | None = None
        usage: Any = None

        # Extract content from various response formats
        if hasattr(response, "content"):
            raw_content = response.content
            if isinstance(raw_content, str):
                content = raw_content
            elif raw_content is not None:
                content = str(raw_content)
        elif isinstance(response, dict):
            # Handle OpenAI-style responses
            raw_content = response.get("content")
            if isinstance(raw_content, str):
                content = raw_content
            elif raw_content is not None:
                content = str(raw_content)
            elif "choices" in response:
                try:
                    first_choice = response.get("choices", [])[0]
                    if isinstance(first_choice, dict):
                        message = first_choice.get("message", {})
                        if isinstance(message, dict):
                            msg_content = message.get("content")
                            if isinstance(msg_content, str):
                                content = msg_content
                            elif msg_content is not None:
                                content = str(msg_content)
                except (IndexError, KeyError, TypeError):
                    pass
        elif response is not None:
            content = str(response)

        # Extract metadata and usage if available
        if hasattr(response, "metadata"):
            metadata = getattr(response, "metadata", None)
        if hasattr(response, "usage"):
            usage = getattr(response, "usage", None)
        elif isinstance(response, dict):
            metadata = response.get("metadata")
            usage = response.get("usage")

        from pydantic.types import JsonValue

        from src.core.domain.usage_summary import UsageSummary

        usage_summary: UsageSummary | None = None
        if isinstance(usage, UsageSummary):
            usage_summary = usage
        elif isinstance(usage, dict):
            usage_summary = UsageSummary.from_dict(usage)

        metadata_json: dict[str, JsonValue] | None = None
        if isinstance(metadata, dict):
            metadata_json = cast(dict[str, JsonValue], metadata)

        return ProcessedResponse(
            content=content, metadata=metadata_json, usage=usage_summary
        )

    def _format_response_with_reasoning(
        self, response_content: str, reasoning_content: str, original_response: Any
    ) -> Any:
        """Format response with properly separated reasoning content.

        Args:
            response_content: The main response content
            reasoning_content: The extracted reasoning content
            original_response: The original response object

        Returns:
            Properly formatted response with reasoning separated according to standards
        """
        # Handle OpenAI-style responses with choices structure
        if isinstance(original_response, dict) and "choices" in original_response:
            # Create a copy to avoid mutating the original
            formatted_response = dict(original_response)

            if formatted_response["choices"]:
                # Create a copy of the first choice
                choice = dict(formatted_response["choices"][0])
                message = dict(choice.get("message", {}))

                # Set the main content
                message["content"] = response_content

                # Add reasoning in the standard reasoning field
                message["reasoning"] = reasoning_content

                # Update the choice and response
                choice["message"] = message
                formatted_response["choices"] = [
                    choice,
                    *formatted_response["choices"][1:],
                ]

                if self._logger.isEnabledFor(logging.DEBUG):
                    self._logger.debug(
                        "Formatted OpenAI-style response with reasoning field: %d chars reasoning, %d chars content",
                        len(reasoning_content),
                        len(response_content),
                    )

                return formatted_response

        # Handle dict responses that might be other formats
        elif isinstance(original_response, dict):
            # Create a copy and add reasoning metadata
            formatted_response = dict(original_response)
            formatted_response["content"] = response_content

            # Add reasoning in metadata section
            if "metadata" not in formatted_response:
                formatted_response["metadata"] = {}
            formatted_response["metadata"]["reasoning"] = reasoning_content
            formatted_response["metadata"][
                "reasoning_format"
            ] = "extracted_from_think_tags"

            if self._logger.isEnabledFor(logging.DEBUG):
                self._logger.debug(
                    "Formatted dict response with reasoning metadata: %d chars reasoning, %d chars content",
                    len(reasoning_content),
                    len(response_content),
                )

            return formatted_response

        # For ProcessedResponse and other objects, use metadata approach
        processed_response = self._ensure_processed_response(original_response)

        # Update content
        processed_response.content = response_content

        # Add reasoning to metadata
        if processed_response.metadata is None:
            processed_response.metadata = {}

        processed_response.metadata["reasoning"] = reasoning_content
        processed_response.metadata["reasoning_format"] = "extracted_from_think_tags"
        processed_response.metadata["think_tags_fixed"] = True
        processed_response.metadata["original_content_length"] = len(
            str(original_response)
        )
        processed_response.metadata["fixed_content_length"] = len(response_content)
        processed_response.metadata["reasoning_length"] = len(reasoning_content)

        if self._logger.isEnabledFor(logging.DEBUG):
            self._logger.debug(
                "Formatted ProcessedResponse with reasoning metadata: %d chars reasoning, %d chars content",
                len(reasoning_content),
                len(response_content),
            )

        return processed_response

    async def process(
        self,
        response: Any,
        session_id: str,
        context: dict[str, Any],
        is_streaming: bool = False,
        stop_event: Any = None,
    ) -> Any:
        """Process a response, fixing improperly formatted think tags.

        Args:
            response: The response to process
            session_id: The session ID
            context: Additional context for processing
            is_streaming: Whether this is a streaming response
            stop_event: Optional stop event for streaming

        Returns:
            The processed response with fixed think tags
        """
        # Extract backend and model from context
        backend = context.get("backend")
        model = context.get("model")

        # Check if we should process this backend/model combination
        if not self._should_process_for_model(backend, model):
            return response

        # Convert to ProcessedResponse for consistent handling
        processed_response = self._ensure_processed_response(response)

        if not processed_response.content:
            return response

        # Derive a stable session identifier for buffering
        fallback_context = context or {}
        resolved_session_id = session_id or fallback_context.get("stream_id")
        if not resolved_session_id and hasattr(processed_response, "metadata"):
            metadata = getattr(processed_response, "metadata", {})
            if isinstance(metadata, dict):
                resolved_session_id = metadata.get("stream_id") or metadata.get(
                    "session_id"
                )
        if not resolved_session_id:
            resolved_session_id = fallback_context.setdefault(
                "_think_tags_session_id", uuid4().hex
            )
        else:
            resolved_session_id = str(resolved_session_id)
            fallback_context.setdefault("_think_tags_session_id", resolved_session_id)

        if session_id and session_id != resolved_session_id:
            self._session_aliases[session_id] = resolved_session_id
        elif not session_id:
            self._session_aliases.setdefault(session_id, resolved_session_id)

        session_id = resolved_session_id

        # Handle streaming vs non-streaming processing
        if is_streaming:
            # Use streaming-aware processing
            fixed_content, reasoning_metadata = self._process_streaming_chunk(
                processed_response.content,
                resolved_session_id,
                is_streaming=True,
                context=context,
            )

            if reasoning_metadata:
                # We extracted reasoning in this chunk, format the response
                formatted_response = self._format_response_with_reasoning(
                    fixed_content, reasoning_metadata, response
                )
                # Ensure streaming_extraction is in the metadata
                if (
                    hasattr(formatted_response, "metadata")
                    and formatted_response.metadata
                ):
                    formatted_response.metadata["streaming_extraction"] = True
                return formatted_response
            elif fixed_content != processed_response.content:
                # Content was modified (e.g., think tags filtered out)
                modified_response = self._ensure_processed_response(response)
                modified_response.content = fixed_content
                return modified_response
            else:
                # No changes needed
                return response
        else:
            # Use regular non-streaming processing
            fixed_content, reasoning_content = self._fix_think_tags(
                processed_response.content
            )

            # If reasoning content was extracted, format the response properly
            if reasoning_content is not None:
                return self._format_response_with_reasoning(
                    fixed_content, reasoning_content, response
                )

        return response

    def reset_session(self, session_id: str) -> None:
        """Reset any session-specific state."""
        alias = self._session_aliases.pop(session_id, None)
        if alias:
            session_id = alias
        self._cleanup_session_state(session_id)
        # Also clean up reasoning extracted data
        self._reasoning_extracted.pop(session_id, None)

        if self._logger.isEnabledFor(logging.DEBUG):
            self._logger.debug(f"Reset think tags fix state for session {session_id}")

    def get_session_reasoning(self, session_id: str) -> dict[str, Any] | None:
        """Public method to get extracted reasoning for a session.

        This can be used by other components to access reasoning that was
        extracted during streaming processing.

        Args:
            session_id: The session identifier

        Returns:
            Reasoning metadata if available, None otherwise (excludes internal fields)
        """
        data = self._reasoning_extracted.get(session_id)
        if data is None:
            return None
        # Filter out internal metadata fields (e.g., _created_at)
        result = {k: v for k, v in data.items() if not k.startswith("_")}
        # Return None if no actual reasoning data
        return result if result else None
