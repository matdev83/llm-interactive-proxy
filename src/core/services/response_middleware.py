from __future__ import annotations

import logging
from typing import Any

from src.core.common.exceptions import LoopDetectionError
from src.core.interfaces.loop_detector_interface import ILoopDetector
from src.core.interfaces.response_processor_interface import (
    IResponseFeature,
    IResponseMiddleware,
    ProcessedResponse,
)

logger = logging.getLogger(__name__)


# ============================================================================
# New IResponseFeature implementations with enforced parity
# ============================================================================


class ResponseLoggingFeature(IResponseFeature):
    """Feature to log response details with enforced streaming/non-streaming parity.

    This is the IResponseFeature version of ResponseLoggingMiddleware that
    explicitly implements both paths with shared logging logic.
    """

    def __init__(self, priority: int = 0) -> None:
        """Initialize the logging feature."""
        super().__init__(priority)

    def _log_response(
        self,
        response: Any,
        session_id: str,
        context: dict[str, Any],
        *,
        is_streaming: bool,
    ) -> None:
        """Shared logging logic for both paths."""
        if not logger.isEnabledFor(logging.DEBUG):
            return

        response_type = context.get(
            "response_type", "streaming" if is_streaming else "complete"
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

    async def process_non_streaming(
        self,
        response: Any,
        session_id: str,
        context: dict[str, Any],
    ) -> Any:
        """Log non-streaming response."""
        self._log_response(response, session_id, context, is_streaming=False)
        return response

    async def process_streaming(
        self,
        chunk: Any,
        session_id: str,
        context: dict[str, Any],
    ) -> Any:
        """Log streaming chunk."""
        self._log_response(chunk, session_id, context, is_streaming=True)
        return chunk


class ContentFilterFeature(IResponseFeature):
    """Feature to filter response content with enforced streaming/non-streaming parity.

    This is the IResponseFeature version of ContentFilterMiddleware that
    explicitly implements both paths with shared filtering logic.
    """

    def __init__(
        self,
        filter_prefix: str = "I'll help you with that. ",
        priority: int = 0,
    ) -> None:
        """Initialize the filter feature.

        Args:
            filter_prefix: Prefix to filter from content
            priority: Execution priority
        """
        super().__init__(priority)
        self._filter_prefix = filter_prefix

    def _filter_content(self, content: str) -> str:
        """Shared filtering logic for both paths."""
        if not content or not isinstance(content, str):
            return content
        if not content.startswith(self._filter_prefix):
            return content
        return content.replace(self._filter_prefix, "", 1)

    def _apply_filter(self, response: Any) -> Any:
        """Apply filter to response."""
        if isinstance(response, dict):
            content = response.get("content")
            if not isinstance(content, str):
                return response
            filtered = self._filter_content(content)
            if filtered == content:
                return response
            result = response.copy()
            result["content"] = filtered
            return result

        content = getattr(response, "content", None)
        if not isinstance(content, str):
            return response

        filtered = self._filter_content(content)
        if filtered == content:
            return response

        if isinstance(response, ProcessedResponse):
            return ProcessedResponse(
                content=filtered,
                usage=response.usage,
                metadata=response.metadata,
            )

        # Try to modify in place
        try:
            response.content = filtered
            return response
        except AttributeError:
            usage = getattr(response, "usage", None)
            metadata = getattr(response, "metadata", None)
            return ProcessedResponse(
                content=filtered,
                usage=usage,
                metadata=metadata,
            )

    async def process_non_streaming(
        self,
        response: Any,
        session_id: str,
        context: dict[str, Any],
    ) -> Any:
        """Filter non-streaming response."""
        return self._apply_filter(response)

    async def process_streaming(
        self,
        chunk: Any,
        session_id: str,
        context: dict[str, Any],
    ) -> Any:
        """Filter streaming chunk.

        Note: For streaming, we filter every chunk since the prefix
        could appear at the start of any chunk boundary.
        """
        return self._apply_filter(chunk)


class LoopDetectionFeature(IResponseFeature):
    """Feature to detect response loops with enforced streaming/non-streaming parity.

    This is the IResponseFeature version of LoopDetectionMiddleware that
    explicitly implements both paths with shared detection logic.
    """

    def __init__(self, loop_detector: ILoopDetector, priority: int = 0) -> None:
        """Initialize the loop detection feature.

        Args:
            loop_detector: The loop detector service
            priority: Execution priority
        """
        super().__init__(priority)
        self._loop_detector = loop_detector
        self._accumulated_content: dict[str, str] = {}

    async def _check_and_accumulate(
        self,
        response: Any,
        session_id: str,
    ) -> Any:
        """Shared accumulation and detection logic."""
        content = getattr(response, "content", None)
        if not content:
            return response

        self._accumulated_content.setdefault(session_id, "")
        self._accumulated_content[session_id] += str(content)
        accumulated = self._accumulated_content[session_id]

        if len(accumulated) > 100:
            loop_result = await self._loop_detector.check_for_loops(accumulated)
            if loop_result.has_loop:
                error_message = (
                    f"Loop detected: The response contains repetitive content. "
                    f"Detected {loop_result.repetitions} repetitions."
                )
                logger.warning(
                    "Loop detected in session %s: %s repetitions",
                    session_id,
                    loop_result.repetitions,
                )
                raise LoopDetectionError(
                    message=error_message,
                    details={
                        "repetitions": loop_result.repetitions,
                        "pattern": loop_result.pattern,
                    },
                )

        return response

    async def process_non_streaming(
        self,
        response: Any,
        session_id: str,
        context: dict[str, Any],
    ) -> Any:
        """Check non-streaming response for loops."""
        return await self._check_and_accumulate(response, session_id)

    async def process_streaming(
        self,
        chunk: Any,
        session_id: str,
        context: dict[str, Any],
    ) -> Any:
        """Check streaming chunk for loops (accumulates across chunks)."""
        return await self._check_and_accumulate(chunk, session_id)

    def reset_session(self, session_id: str) -> None:
        """Reset the accumulated content for a session."""
        if session_id in self._accumulated_content:
            del self._accumulated_content[session_id]


# ============================================================================
# Legacy IResponseMiddleware implementations (kept for backward compatibility)
# DEPRECATED: Use *Feature classes instead
# ============================================================================


class ResponseLoggingMiddleware(IResponseMiddleware):
    """DEPRECATED: Use ResponseLoggingFeature instead.

    Legacy middleware to log response details.
    This class is kept for backward compatibility only.
    """

    def __init__(self, priority: int = 0) -> None:
        """Initialize the middleware."""
        logger.error(
            "DEPRECATED: ResponseLoggingMiddleware instantiated. "
            "Use ResponseLoggingFeature instead for proper streaming/non-streaming parity."
        )
        super().__init__(priority)

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

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Response processed for session %s (%s): content_len=%s, usage=%s",
                    session_id,
                    response_type,
                    content_length,
                    usage_info,
                )

        return response


class ContentFilterMiddleware(IResponseMiddleware):
    """DEPRECATED: Use ContentFilterFeature instead.

    Legacy middleware to filter response content.
    This class is kept for backward compatibility only.
    """

    def __init__(self, priority: int = 0) -> None:
        """Initialize the middleware."""
        logger.error(
            "DEPRECATED: ContentFilterMiddleware instantiated. "
            "Use ContentFilterFeature instead for proper streaming/non-streaming parity."
        )
        super().__init__(priority)

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
    """DEPRECATED: Use LoopDetectionFeature instead.

    Legacy middleware to detect response loops.
    This class is kept for backward compatibility only.
    """

    def __init__(self, loop_detector: ILoopDetector, priority: int = 0) -> None:
        logger.error(
            "DEPRECATED: LoopDetectionMiddleware instantiated. "
            "Use LoopDetectionFeature instead for proper streaming/non-streaming parity."
        )
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
