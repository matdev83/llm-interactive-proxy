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


class LoggingMiddleware(IResponseMiddleware):
    """Middleware to log response details."""

    async def process(
        self,
        response: ProcessedResponse,
        session_id: str,
        context: dict[str, Any] | None = None,
    ) -> ProcessedResponse:
        """Process a response, logging information as needed."""
        if logger.isEnabledFor(logging.DEBUG):
            response_type = (
                context.get("response_type", "unknown") if context else "unknown"
            )
            usage_info = response.usage if response.usage else {}

            logger.debug(
                f"Response processed for session {session_id} ({response_type}): "
                f"content_len={len(response.content) if response.content else 0}, "
                f"usage={usage_info}"
            )

        return response


class ContentFilterMiddleware(IResponseMiddleware):
    """Middleware to filter response content."""

    async def process(
        self,
        response: ProcessedResponse,
        session_id: str,
        context: dict[str, Any] | None = None,
    ) -> ProcessedResponse:
        """Process a response, filtering content as needed."""
        content = response.content

        if not content:
            return response

        # Example filtering logic
        if content.startswith("I'll help you with that. "):
            content = content.replace("I'll help you with that. ", "", 1)

        return ProcessedResponse(
            content=content, usage=response.usage, metadata=response.metadata
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
        response: ProcessedResponse,
        session_id: str,
        context: dict[str, Any] | None = None,
    ) -> ProcessedResponse:
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
