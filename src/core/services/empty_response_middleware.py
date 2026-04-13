"""
Empty response detection and auto-retry middleware.

This middleware detects empty responses from LLMs (no content and no tool calls)
and automatically retries with a recovery prompt to prevent agent loop breakage.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import MutableMapping
from pathlib import Path
from typing import Any

from cachetools import TTLCache

from src.core.common.exceptions import BackendError
from src.core.interfaces.response_processor_interface import (
    IResponseFeature,
    IResponseMiddleware,
    ProcessedResponse,
)

logger = logging.getLogger(__name__)


# ============================================================================
# New IResponseFeature implementation with enforced parity
# ============================================================================


class EmptyResponseFeature(IResponseFeature):
    """Feature to detect empty responses with enforced streaming/non-streaming parity.

    This is the IResponseFeature version of EmptyResponseMiddleware that
    explicitly implements both streaming and non-streaming paths with shared
    detection logic.

    For streaming responses, this feature accumulates content across chunks
    and marks the response as empty at stream completion if no meaningful
    content was received.
    """

    def __init__(
        self,
        enabled: bool = True,
        max_retries: int = 1,
        priority: int = 0,
    ) -> None:
        """Initialize the empty response feature.

        Args:
            enabled: Whether the feature is enabled
            max_retries: Maximum number of retry attempts
            priority: Execution priority
        """
        super().__init__(priority)
        self._enabled = enabled
        self._max_retries = max_retries
        self._retry_counts: MutableMapping[str, int] = TTLCache(maxsize=10000, ttl=3600)
        self._recovery_prompt: str | None = None
        # Streaming state: track activity per stream
        self._stream_activity: MutableMapping[str, dict[str, bool]] = TTLCache(
            maxsize=10000, ttl=3600
        )

    def _has_tool_calls(
        self, response: ProcessedResponse, context: dict[str, Any] | None = None
    ) -> bool:
        """Determine whether tool calls are present in the response or context."""
        has_tool_calls = False

        if response.metadata:
            has_tool_calls = bool(response.metadata.get("tool_calls"))

        if not has_tool_calls and context:
            has_tool_calls = bool(context.get("tool_calls"))

        if not has_tool_calls and context and "original_response" in context:
            original = context["original_response"]
            if hasattr(original, "tool_calls"):
                has_tool_calls = bool(original.tool_calls)
            elif isinstance(original, dict):
                choices = original.get("choices", [])
                if choices and isinstance(choices[0], dict):
                    message = choices[0].get("message", {})
                    has_tool_calls = bool(message.get("tool_calls"))

        return has_tool_calls

    async def _load_recovery_prompt(self) -> str:
        """Load the recovery prompt from the config file."""
        if self._recovery_prompt is not None:
            return self._recovery_prompt

        try:
            prompt_relative = (
                Path("config") / "prompts" / "empty_response_auto_retry_prompt.md"
            )
            current_dir = Path(__file__).resolve().parent
            prompt_path: Path | None = None

            for candidate_root in (current_dir, *tuple(current_dir.parents)):
                candidate = candidate_root / prompt_relative
                if candidate.exists():
                    prompt_path = candidate
                    break
                if candidate_root.parent == candidate_root:
                    break

            if prompt_path and prompt_path.exists():

                def _read_file() -> str:
                    with open(prompt_path, encoding="utf-8") as f:
                        return f.read().strip()

                self._recovery_prompt = await asyncio.to_thread(_read_file)
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug("Loaded recovery prompt from %s", prompt_path)
            else:
                self._recovery_prompt = (
                    "The previous response was empty. Please provide a valid response "
                    "with either text content or tool calls. Never return an empty response."
                )
                logger.warning(
                    "Recovery prompt file not found at %s, using fallback",
                    prompt_path or prompt_relative,
                )

        except OSError as e:
            logger.error("Error loading recovery prompt: %s", e, exc_info=True)
            self._recovery_prompt = (
                "The previous response was empty. Please provide a valid response "
                "with either text content or tool calls. Never return an empty response."
            )

        return self._recovery_prompt

    def _is_empty_response(
        self, response: ProcessedResponse, context: dict[str, Any] | None = None
    ) -> bool:
        """Check if a response is empty (no content and no tool calls)."""
        metadata = response.metadata if isinstance(response.metadata, dict) else {}
        finish_reason = (
            metadata.get("finish_reason") if isinstance(metadata, dict) else None
        )
        if isinstance(finish_reason, str) and finish_reason.lower() == "tool_calls":
            return False

        def _content_is_empty(val: Any) -> bool:
            if val is None:
                return True
            if isinstance(val, dict):
                if val.get("error"):
                    return False
                if val.get("choices"):
                    return False
                return not bool(val)
            if isinstance(val, list | tuple | set):
                return len(val) == 0
            if isinstance(val, bytes | bytearray):
                try:
                    val = val.decode("utf-8")
                except UnicodeDecodeError:
                    val = val.decode("utf-8", errors="ignore")
            if isinstance(val, str):
                return not val.strip()
            return not bool(val)

        content_empty = _content_is_empty(response.content)
        has_tool_calls = self._has_tool_calls(response, context)
        return content_empty and not has_tool_calls

    def _ensure_processed_response(
        self, response: Any, context: dict[str, Any] | None
    ) -> ProcessedResponse:
        """Normalize arbitrary response objects into ProcessedResponse instances."""
        if isinstance(response, ProcessedResponse):
            return response

        content: str = ""
        metadata: dict[str, Any] | None = None

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
            elif "choices" in response:
                try:
                    first_choice = response.get("choices", [])[0]
                except IndexError:
                    first_choice = None
                if isinstance(first_choice, dict):
                    message = first_choice.get("message", {})
                    if isinstance(message, dict):
                        msg_content = message.get("content")
                        if isinstance(msg_content, str):
                            content = msg_content
                        elif msg_content is not None:
                            content = str(msg_content)
                        tool_calls = message.get("tool_calls")
                        if isinstance(tool_calls, list):
                            metadata = {"tool_calls": tool_calls}
        elif response is not None:
            content = str(response)

        if metadata is None:
            raw_metadata = getattr(response, "metadata", None)
            if isinstance(raw_metadata, dict):
                metadata = raw_metadata
            elif isinstance(response, dict):
                raw_metadata = response.get("metadata")
                if isinstance(raw_metadata, dict):
                    metadata = raw_metadata

        if metadata is None and context and isinstance(context, dict):
            tool_calls = context.get("tool_calls")
            if isinstance(tool_calls, list):
                metadata = {"tool_calls": tool_calls}

        return ProcessedResponse(content=content, metadata=metadata)

    def _get_stream_key(self, session_id: str, context: dict[str, Any]) -> str:
        """Get unique key for tracking stream activity."""
        stream_id = context.get("stream_id", "")
        return f"{session_id}:{stream_id}" if stream_id else session_id

    def _track_stream_activity(
        self,
        stream_key: str,
        processed_response: ProcessedResponse,
        context: dict[str, Any],
    ) -> None:
        """Track streaming activity for empty detection."""
        if stream_key not in self._stream_activity:
            self._stream_activity[stream_key] = {
                "has_content": False,
                "has_tool_calls": False,
            }

        activity = self._stream_activity[stream_key]

        # Check for content
        if processed_response.content:
            content_str = (
                processed_response.content
                if isinstance(processed_response.content, str)
                else str(processed_response.content)
            )
            if content_str.strip():
                activity["has_content"] = True

        # Check for tool calls
        if self._has_tool_calls(processed_response, context):
            activity["has_tool_calls"] = True

    def _is_stream_end(self, context: dict[str, Any]) -> bool:
        """Check if this is the end of a stream."""
        if context.get("is_final_chunk"):
            return True
        if context.get("done"):
            return True
        return bool(context.get("finish_reason"))

    async def process_chunk(
        self,
        payload: Any,
        session_id: str,
        context: dict[str, object],
        *,
        is_streaming: bool,
    ) -> Any:
        """Detect empty responses (non-streaming retries; streaming end-of-stream flag)."""
        ctx: dict[str, Any] = dict(context or {})
        if not self._enabled:
            return payload

        if not is_streaming:
            original_request = ctx.get("original_request")

            processed_response = self._ensure_processed_response(payload, ctx)

            if original_request is None and isinstance(
                processed_response.metadata, dict
            ):
                original_request = processed_response.metadata.pop(
                    "original_request", None
                )
            elif isinstance(processed_response.metadata, dict):
                processed_response.metadata.pop("original_request", None)

            if self._is_empty_response(processed_response, ctx):
                retry_count = self._retry_counts.get(session_id, 0)

                if retry_count < self._max_retries:
                    if original_request is None:
                        logger.warning(
                            "Empty response detected but no original_request in context; "
                            "skipping retry"
                        )
                        return payload

                    recovery_prompt = await self._load_recovery_prompt()
                    next_retry_count = retry_count + 1
                    self._retry_counts[session_id] = next_retry_count

                    logger.info(
                        "Empty response detected for session %s, attempt %s/%s",
                        session_id,
                        next_retry_count,
                        self._max_retries,
                    )

                    raise EmptyResponseRetryError(
                        recovery_prompt=recovery_prompt,
                        session_id=session_id,
                        retry_count=next_retry_count,
                        original_request=original_request,
                    )
                self._retry_counts.pop(session_id, None)
                logger.error(
                    "Max retries exceeded for empty response in session %s", session_id
                )

                raise BackendError(
                    message="The LLM failed to generate a valid response after retry "
                    "attempts. The response was empty (no content or tool calls).",
                    details={
                        "session_id": session_id,
                        "retry_count": retry_count,
                        "error_type": "empty_response_max_retries_exceeded",
                    },
                )
            self._retry_counts.pop(session_id, None)

            return payload

        processed_response = self._ensure_processed_response(payload, ctx)

        if isinstance(processed_response.metadata, dict):
            processed_response.metadata.pop("original_request", None)

        stream_key = self._get_stream_key(session_id, ctx)

        self._track_stream_activity(stream_key, processed_response, ctx)

        if self._is_stream_end(ctx):
            activity = self._stream_activity.pop(stream_key, None)
            if activity:
                is_empty = (
                    not activity["has_content"] and not activity["has_tool_calls"]
                )
                if is_empty:
                    logger.warning(
                        "Empty streaming response detected for session %s", session_id
                    )
                    if processed_response.metadata is None:
                        processed_response.metadata = {}
                    if isinstance(processed_response.metadata, dict):
                        processed_response.metadata["empty_stream_detected"] = True

        return processed_response

    def reset_session(self, session_id: str) -> None:
        """Reset retry count and stream activity for a session."""
        self._retry_counts.pop(session_id, None)
        # Clean up any stream activity keys that start with this session
        keys_to_remove = [
            k for k in self._stream_activity if k.startswith(f"{session_id}:")
        ]
        for key in keys_to_remove:
            self._stream_activity.pop(key, None)
        self._stream_activity.pop(session_id, None)


# ============================================================================
# Legacy IResponseMiddleware implementation (kept for backward compatibility)
# DEPRECATED: Use EmptyResponseFeature instead
# ============================================================================


class EmptyResponseMiddleware(IResponseMiddleware):
    """DEPRECATED: Use EmptyResponseFeature instead.

    Legacy middleware to detect and handle empty responses from LLMs.
    This class is kept for backward compatibility only.
    """

    def __init__(self, enabled: bool = True, max_retries: int = 1) -> None:
        """Initialize the empty response middleware.

        Args:
            enabled: Whether the middleware is enabled
            max_retries: Maximum number of retry attempts (default: 1)
        """
        logger.error(
            "DEPRECATED: EmptyResponseMiddleware instantiated. "
            "Use EmptyResponseFeature instead for proper streaming/non-streaming parity."
        )
        self._enabled = enabled
        self._max_retries = max_retries
        self._retry_counts: MutableMapping[str, int] = TTLCache(maxsize=10000, ttl=3600)
        self._recovery_prompt: str | None = None
        self._stream_activity: MutableMapping[str, dict[str, bool]] = TTLCache(
            maxsize=10000, ttl=3600
        )

    def _has_tool_calls(
        self, response: ProcessedResponse, context: dict[str, Any] | None = None
    ) -> bool:
        """Determine whether tool calls are present in the response or context."""
        has_tool_calls = False

        if response.metadata:
            has_tool_calls = bool(response.metadata.get("tool_calls"))

        if not has_tool_calls and context:
            has_tool_calls = bool(context.get("tool_calls"))

        if not has_tool_calls and context and "original_response" in context:
            original = context["original_response"]
            if hasattr(original, "tool_calls"):
                has_tool_calls = bool(original.tool_calls)
            elif isinstance(original, dict):
                choices = original.get("choices", [])
                if choices and isinstance(choices[0], dict):
                    message = choices[0].get("message", {})
                    has_tool_calls = bool(message.get("tool_calls"))

        return has_tool_calls

    async def _load_recovery_prompt(self) -> str:
        """Load the recovery prompt from the config file."""
        if self._recovery_prompt is not None:
            return self._recovery_prompt

        try:
            prompt_relative = (
                Path("config") / "prompts" / "empty_response_auto_retry_prompt.md"
            )
            current_dir = Path(__file__).resolve().parent
            prompt_path: Path | None = None

            for candidate_root in (current_dir, *tuple(current_dir.parents)):
                candidate = candidate_root / prompt_relative
                if candidate.exists():
                    prompt_path = candidate
                    break
                if candidate_root.parent == candidate_root:
                    break

            if prompt_path and prompt_path.exists():

                def _read_file() -> str:
                    with open(prompt_path, encoding="utf-8") as f:
                        return f.read().strip()

                self._recovery_prompt = await asyncio.to_thread(_read_file)
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug("Loaded recovery prompt from %s", prompt_path)
            else:
                # Fallback prompt if file doesn't exist
                self._recovery_prompt = (
                    "The previous response was empty. Please provide a valid response "
                    "with either text content or tool calls. Never return an empty response."
                )
                logger.warning(
                    "Recovery prompt file not found at %s, using fallback",
                    prompt_path or prompt_relative,
                )

        except OSError as e:
            logger.error(f"Error loading recovery prompt: {e}", exc_info=True)
            self._recovery_prompt = (
                "The previous response was empty. Please provide a valid response "
                "with either text content or tool calls. Never return an empty response."
            )

        return self._recovery_prompt

    def _is_empty_response(
        self, response: ProcessedResponse, context: dict[str, Any] | None = None
    ) -> bool:
        """Check if a response is empty (no content and no tool calls).

        Args:
            response: The processed response to check
            context: Additional context that might contain tool call information

        Returns:
            True if the response is empty, False otherwise
        """
        metadata = response.metadata if isinstance(response.metadata, dict) else {}
        finish_reason = (
            metadata.get("finish_reason") if isinstance(metadata, dict) else None
        )
        if isinstance(finish_reason, str) and finish_reason.lower() == "tool_calls":
            return False

        def _content_is_empty(val: Any) -> bool:
            if val is None:
                return True
            if isinstance(val, dict):
                # Treat structured payloads (including error chunks) as non-empty
                if val.get("error"):
                    return False
                if val.get("choices"):
                    return False
                return not bool(val)
            if isinstance(val, list | tuple | set):
                return len(val) == 0
            if isinstance(val, bytes | bytearray):
                try:
                    val = val.decode("utf-8")
                except UnicodeDecodeError:
                    val = val.decode("utf-8", errors="ignore")
            if isinstance(val, str):
                return not val.strip()
            return not bool(val)

        # Check if content is empty (after stripping whitespace)
        content_empty = _content_is_empty(response.content)

        has_tool_calls = self._has_tool_calls(response, context)
        # Response is empty if it has no content AND no tool calls
        is_empty = content_empty and not has_tool_calls

        if is_empty:
            logger.warning(
                f"Empty response detected: content_empty={content_empty}, has_tool_calls={has_tool_calls}"
            )

        return is_empty

    def _ensure_processed_response(
        self, response: Any, context: dict[str, Any] | None
    ) -> ProcessedResponse:
        """Normalize arbitrary response objects into ``ProcessedResponse`` instances."""

        if isinstance(response, ProcessedResponse):
            return response

        content: str = ""
        metadata: dict[str, Any] | None = None

        # Prefer explicit ``content`` attribute when present
        if hasattr(response, "content"):
            raw_content = response.content
            if isinstance(raw_content, str):
                content = raw_content
            elif raw_content is not None:
                content = str(raw_content)
        elif isinstance(response, dict):
            # Canonical OpenAI responses expose text under choices -> message
            raw_content = response.get("content")
            if isinstance(raw_content, str):
                content = raw_content
            elif raw_content is not None:
                # Convert non-None content (including structured content) to string
                content = str(raw_content)
            elif "choices" in response:
                try:
                    first_choice = response.get("choices", [])[0]
                except IndexError:
                    first_choice = None
                if isinstance(first_choice, dict):
                    message = first_choice.get("message", {})
                    if isinstance(message, dict):
                        msg_content = message.get("content")
                        if isinstance(msg_content, str):
                            content = msg_content
                        elif msg_content is not None:
                            content = str(msg_content)
                        tool_calls = message.get("tool_calls")
                        if isinstance(tool_calls, list):
                            metadata = {"tool_calls": tool_calls}
        elif response is not None:
            content = str(response)

        if metadata is None:
            raw_metadata = getattr(response, "metadata", None)
            if isinstance(raw_metadata, dict):
                metadata = raw_metadata
            elif isinstance(response, dict):
                raw_metadata = response.get("metadata")
                if isinstance(raw_metadata, dict):
                    metadata = raw_metadata

        # Context may include upstream tool-call metadata that we should preserve
        if metadata is None and context and isinstance(context, dict):
            tool_calls = context.get("tool_calls")
            if isinstance(tool_calls, list):
                metadata = {"tool_calls": tool_calls}

        return ProcessedResponse(content=content, metadata=metadata)

    async def process(
        self,
        response: Any,
        session_id: str,
        context: dict[str, Any],
        is_streaming: bool = False,
        stop_event: Any = None,
    ) -> Any:
        """Process a response, checking for empty responses and triggering recovery.

        Args:
            response: The response to process
            session_id: The session ID
            context: Additional context for processing

        Returns:
            The processed response or raises an exception for retry
        """
        if not self._enabled:
            return response

        context = context or {}
        original_request = context.get("original_request")

        processed_response = self._ensure_processed_response(response, context)

        if is_streaming:
            if isinstance(processed_response.metadata, dict):
                processed_response.metadata.pop("original_request", None)
            return processed_response

        if original_request is None and isinstance(processed_response.metadata, dict):
            original_request = processed_response.metadata.pop("original_request", None)
        elif isinstance(processed_response.metadata, dict):
            processed_response.metadata.pop("original_request", None)

        # Check if this is an empty response
        if self._is_empty_response(processed_response, context):
            # Check retry count for this session
            retry_count = self._retry_counts.get(session_id, 0)

            if retry_count < self._max_retries:
                if original_request is None:
                    logger.warning(
                        "Empty response detected but no original_request in context; skipping retry"
                    )
                    return response

                # Load recovery prompt only when a retry can actually happen
                recovery_prompt = await self._load_recovery_prompt()
                next_retry_count = retry_count + 1
                self._retry_counts[session_id] = next_retry_count

                logger.info(
                    f"Empty response detected for session {session_id}, attempt {next_retry_count}/{self._max_retries}"
                )

                # Raise a special exception that the request processor can catch
                # and use to retry with the recovery prompt
                raise EmptyResponseRetryError(
                    recovery_prompt=recovery_prompt,
                    session_id=session_id,
                    retry_count=next_retry_count,
                    original_request=original_request,
                )
            else:
                # Max retries exceeded, reset counter and return error
                self._retry_counts.pop(session_id, None)
                logger.error(
                    f"Max retries exceeded for empty response in session {session_id}"
                )

                raise BackendError(
                    message="The LLM failed to generate a valid response after retry attempts. "
                    "The response was empty (no content or tool calls).",
                    details={
                        "session_id": session_id,
                        "retry_count": retry_count,
                        "error_type": "empty_response_max_retries_exceeded",
                    },
                )
        else:
            # Response is not empty, reset retry count for this session
            self._retry_counts.pop(session_id, None)

        return response

    def reset_session(self, session_id: str) -> None:
        """Reset retry count for a session."""
        self._retry_counts.pop(session_id, None)
        self._stream_activity.pop(session_id or "default_stream", None)


class EmptyResponseRetryError(Exception):
    """Exception raised when an empty response is detected and should be retried."""

    def __init__(
        self,
        recovery_prompt: str,
        session_id: str,
        retry_count: int,
        original_request: Any,
    ):
        self.recovery_prompt = recovery_prompt
        self.session_id = session_id
        self.retry_count = retry_count
        self.original_request = original_request
        super().__init__(
            f"Empty response detected for session {session_id}, retry {retry_count}"
        )


# Backwards-compatibility alias expected by tests and integrations
EmptyResponseRetryException = EmptyResponseRetryError
