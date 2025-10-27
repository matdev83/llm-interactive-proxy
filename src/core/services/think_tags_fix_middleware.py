"""
Think tags fix middleware for correcting improperly formatted reasoning tags.

Some models from less known vendors produce <think> </think> tags inside plain message body
instead of using standard conventions to mark reasoning and non-reasoning parts of the output.
This middleware detects and corrects such improperly marked reasoning streams.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from src.core.interfaces.response_processor_interface import (
    IResponseMiddleware,
    ProcessedResponse,
)

logger = logging.getLogger(__name__)


class ThinkTagsFixMiddleware(IResponseMiddleware):
    """Middleware to fix improperly formatted <think> tags in model responses."""

    # Pre-compiled regex patterns for performance
    _THINK_TAG_PATTERN = re.compile(
        r"^(\s*)<think>(.*?)</think>(\s*)(.*?)$", re.DOTALL | re.IGNORECASE
    )

    _THINK_OPENING_PATTERN = re.compile(r"^(\s*)<think>", re.IGNORECASE)

    _THINK_CLOSING_PATTERN = re.compile(r"</think>", re.IGNORECASE)

    def __init__(self, enabled: bool = True, streaming_buffer_size: int = 4096) -> None:
        """Initialize the think tags fix middleware.

        Args:
            enabled: Whether the middleware is enabled
            streaming_buffer_size: Maximum buffer size for streaming chunks
        """
        super().__init__(priority=5)  # Run early in the pipeline
        self._enabled = enabled
        self._streaming_buffer_size = streaming_buffer_size
        self._logger = logging.getLogger(__name__)

        # Streaming state management
        self._streaming_buffers: dict[str, str] = (
            {}
        )  # Buffer accumulated chunks per session
        self._reasoning_extracted: dict[str, dict[str, Any]] = (
            {}
        )  # Track extracted reasoning per session
        self._stream_states: dict[str, str] = {}  # Track streaming state per session

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
        self, chunk_content: str, session_id: str, is_streaming: bool = False
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
            self._reasoning_extracted[session_id] = {}
            self._stream_states[session_id] = "waiting"  # waiting, in_think, post_think

        current_buffer = self._streaming_buffers[session_id]
        current_state = self._stream_states[session_id]

        # Add chunk to buffer
        new_buffer = current_buffer + chunk_content

        # Prevent buffer overflow
        if len(new_buffer) > self._streaming_buffer_size:
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

            # Store reasoning for this session
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
            # Store reasoning metadata for later retrieval
            self._reasoning_extracted[session_id] = {
                "reasoning": reasoning_content,
                "reasoning_format": "extracted_from_think_tags",
                "think_tags_fixed": True,
                "streaming_extraction": True,
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
        # Keep reasoning_extracted for potential later retrieval

    def _get_session_reasoning(self, session_id: str) -> dict[str, Any] | None:
        """Get extracted reasoning for a session.

        Args:
            session_id: The session identifier

        Returns:
            Reasoning metadata if available, None otherwise
        """
        return self._reasoning_extracted.get(session_id)

    def _ensure_processed_response(self, response: Any) -> ProcessedResponse:
        """Normalize arbitrary response objects into ProcessedResponse instances."""
        if isinstance(response, ProcessedResponse):
            return response

        content: str = ""
        metadata: dict[str, Any] | None = None
        usage: dict[str, Any] | None = None

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

        return ProcessedResponse(content=content, metadata=metadata, usage=usage)

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
        if not self._enabled:
            return response

        # Convert to ProcessedResponse for consistent handling
        processed_response = self._ensure_processed_response(response)

        if not processed_response.content:
            return response

        # Handle streaming vs non-streaming processing
        if is_streaming:
            # Use streaming-aware processing
            fixed_content, reasoning_metadata = self._process_streaming_chunk(
                processed_response.content, session_id, is_streaming=True
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
        self._cleanup_session_state(session_id)
        # Also clean up reasoning extracted data
        self._reasoning_extracted.pop(session_id, None)

        self._logger.debug(f"Reset think tags fix state for session {session_id}")

    def get_session_reasoning(self, session_id: str) -> dict[str, Any] | None:
        """Public method to get extracted reasoning for a session.

        This can be used by other components to access reasoning that was
        extracted during streaming processing.

        Args:
            session_id: The session identifier

        Returns:
            Reasoning metadata if available, None otherwise
        """
        reasoning = self._reasoning_extracted.get(session_id)
        # Return None if reasoning is empty dict or None
        if not reasoning:
            return None
        return reasoning
