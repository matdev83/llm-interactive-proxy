from __future__ import annotations

import logging
from typing import Any

from src.core.common.exceptions import LoopDetectionError
from src.core.interfaces.loop_detector_interface import ILoopDetector
from src.core.interfaces.response_processor_interface import (
    IResponseMiddleware,
    ProcessedResponse,
)

logger = logging.getLogger(__name__)


class ResponseLoggingMiddleware(IResponseMiddleware):
    """Middleware to log response details (part of response processing pipeline)."""

    async def process(
        self,
        response: Any,
        session_id: str,
        context: dict[str, Any],
        is_streaming: bool = False,
        stop_event: Any = None,
    ) -> Any:
        """Process a response, logging information as needed."""
        if logger.isEnabledFor(logging.DEBUG):
            response_type = (
                context.get("response_type", "unknown") if context else "unknown"
            )

            if isinstance(response, dict):
                raw_content = response.get("content")
                usage_info = response.get("usage", {}) or {}
            else:
                raw_content = getattr(response, "content", None)
                usage_info = getattr(response, "usage", {}) or {}

            try:
                content_length = len(raw_content) if raw_content else 0
            except TypeError:
                content_length = 0

            logger.debug(
                "Response processed for session %s (%s): content_len=%s, usage=%s",
                session_id,
                response_type,
                content_length,
                usage_info,
            )

        return response


class ContentFilterMiddleware(IResponseMiddleware):
    """Middleware to filter response content."""

    async def process(
        self,
        response: Any,
        session_id: str,
        context: dict[str, Any],
        is_streaming: bool = False,
        stop_event: Any = None,
    ) -> Any:
        """Process a response, filtering content as needed."""
        prefix = "I'll help you with that. "

        if isinstance(response, dict):
            content = response.get("content")
            if not isinstance(content, str) or not content:
                return response
            if not content.startswith(prefix):
                return response

            filtered_content = content.replace(prefix, "", 1)
            updated_response = response.copy()
            updated_response["content"] = filtered_content
            return updated_response

        content = getattr(response, "content", None)
        if not isinstance(content, str) or not content:
            return response
        if not content.startswith(prefix):
            return response

        filtered_content = content.replace(prefix, "", 1)

        try:
            response.content = filtered_content
            return response
        except AttributeError:
            usage = getattr(response, "usage", None)
            metadata = getattr(response, "metadata", None)
            return ProcessedResponse(
                content=filtered_content,
                usage=usage,
                metadata=metadata,
            )


class LoopDetectionMiddleware(IResponseMiddleware):
    """Middleware to detect response loops."""

    def __init__(self, loop_detector: ILoopDetector, priority: int = 0) -> None:
        self._loop_detector = loop_detector
        self._accumulated_content: dict[str, str] = {}
        self._priority = priority

    @property
    def priority(self) -> int:
        return self._priority

    async def process(
        self,
        response: Any,
        session_id: str,
        context: dict[str, Any],
        is_streaming: bool = False,
        stop_event: Any = None,
    ) -> Any:
        """Process a response, checking for loops."""
        if not response.content:
            return response

        self._accumulated_content.setdefault(session_id, "")
        self._accumulated_content[session_id] += response.content
        content = self._accumulated_content[session_id]

        if len(content) > 100:
            loop_result = await self._loop_detector.check_for_loops(content)
            if loop_result.has_loop:
                error_message = f"Loop detected: The response contains repetitive content. Detected {loop_result.repetitions} repetitions."
                logger.warning(
                    f"Loop detected in session {session_id}: {loop_result.repetitions} repetitions"
                )
                raise LoopDetectionError(
                    message=error_message,
                    details={
                        "repetitions": loop_result.repetitions,
                        "pattern": loop_result.pattern,
                    },
                )

        return response

    def reset_session(self, session_id: str) -> None:
        """Reset the accumulated content for a session."""
        if session_id in self._accumulated_content:
            del self._accumulated_content[session_id]
