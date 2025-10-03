"""
Empty response detection and auto-retry middleware.

This middleware detects empty responses from LLMs (no content and no tool calls)
and automatically retries with a recovery prompt to prevent agent loop breakage.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from src.core.common.exceptions import BackendError
from src.core.interfaces.response_processor_interface import (
    IResponseMiddleware,
    ProcessedResponse,
)

logger = logging.getLogger(__name__)


class EmptyResponseMiddleware(IResponseMiddleware):
    """Middleware to detect and handle empty responses from LLMs."""

    def __init__(self, enabled: bool = True, max_retries: int = 1) -> None:
        """Initialize the empty response middleware.

        Args:
            enabled: Whether the middleware is enabled
            max_retries: Maximum number of retry attempts (default: 1)
        """
        self._enabled = enabled
        self._max_retries = max_retries
        self._retry_counts: dict[str, int] = {}
        self._recovery_prompt: str | None = None

    def _load_recovery_prompt(self) -> str:
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
                with open(prompt_path, encoding="utf-8") as f:
                    self._recovery_prompt = f.read().strip()
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
            if logger.isEnabledFor(logging.ERROR):
                logger.error(f"Error loading recovery prompt: {e}")
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
        # Check if content is empty (after stripping whitespace)
        content_empty = not response.content or not response.content.strip()

        # Check if there are tool calls in the response metadata or context
        has_tool_calls = False

        # Check metadata for tool calls
        if response.metadata:
            has_tool_calls = bool(response.metadata.get("tool_calls"))

        # Check context for tool calls (might be passed from upstream processing)
        if not has_tool_calls and context:
            has_tool_calls = bool(context.get("tool_calls"))

        # Also check if the original response object has tool calls
        if not has_tool_calls and context and "original_response" in context:
            original = context["original_response"]
            if hasattr(original, "tool_calls"):
                has_tool_calls = bool(original.tool_calls)
            elif isinstance(original, dict):
                choices = original.get("choices", [])
                if choices and isinstance(choices[0], dict):
                    message = choices[0].get("message", {})
                    has_tool_calls = bool(message.get("tool_calls"))

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

        processed_response = self._ensure_processed_response(response, context)

        # Check if this is an empty response
        if self._is_empty_response(processed_response, context):
            # Check retry count for this session
            retry_count = self._retry_counts.get(session_id, 0)

            if retry_count < self._max_retries:
                original_request = context.get("original_request")
                if original_request is None:
                    logger.warning(
                        "Empty response detected but no original_request in context; skipping retry"
                    )
                    return response

                # Load recovery prompt only when a retry can actually happen
                recovery_prompt = self._load_recovery_prompt()
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
