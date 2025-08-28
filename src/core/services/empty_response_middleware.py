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
            # Get the workspace root directory
            current_dir = Path(__file__).parent
            workspace_root = current_dir
            while workspace_root.parent != workspace_root:
                if (workspace_root / "config").exists():
                    break
                workspace_root = workspace_root.parent

            prompt_path = (
                workspace_root
                / "config"
                / "prompts"
                / "empty_response_auto_retry_prompt.md"
            )

            if prompt_path.exists():
                with open(prompt_path, encoding="utf-8") as f:
                    self._recovery_prompt = f.read().strip()
                logger.debug(f"Loaded recovery prompt from {prompt_path}")
            else:
                # Fallback prompt if file doesn't exist
                self._recovery_prompt = (
                    "The previous response was empty. Please provide a valid response "
                    "with either text content or tool calls. Never return an empty response."
                )
                logger.warning(
                    f"Recovery prompt file not found at {prompt_path}, using fallback"
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

        # Check if this is an empty response
        if self._is_empty_response(response, context):
            # Check retry count for this session
            retry_count = self._retry_counts.get(session_id, 0)

            if retry_count < self._max_retries:
                # Increment retry count
                self._retry_counts[session_id] = retry_count + 1

                # Load recovery prompt
                recovery_prompt = self._load_recovery_prompt()

                logger.info(
                    f"Empty response detected for session {session_id}, attempt {retry_count + 1}/{self._max_retries}"
                )

                # Raise a special exception that the request processor can catch
                # and use to retry with the recovery prompt
                raise EmptyResponseRetryError(
                    recovery_prompt=recovery_prompt,
                    session_id=session_id,
                    retry_count=retry_count + 1,
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

    def __init__(self, recovery_prompt: str, session_id: str, retry_count: int):
        self.recovery_prompt = recovery_prompt
        self.session_id = session_id
        self.retry_count = retry_count
        super().__init__(
            f"Empty response detected for session {session_id}, retry {retry_count}"
        )


# Backwards-compatibility alias expected by tests and integrations
EmptyResponseRetryException = EmptyResponseRetryError
