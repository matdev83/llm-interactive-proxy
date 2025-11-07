from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

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
        self._anonymous_session_aliases: dict[int, str] = {}

    @property
    def priority(self) -> int:
        return self._priority

    def _resolve_session_key(
        self,
        session_id: str,
        context: dict[str, Any] | None,
        response: Any,
        stop_event: Any,
    ) -> tuple[str, bool]:
        candidate_fields = (
            "session_id",
            "stream_id",
            "id",
            "request_id",
            "conversation_id",
            "thread_id",
            "message_id",
        )
        if session_id:
            normalized = str(session_id).strip()
            if normalized:
                return normalized, False
        sources: list[dict[str, Any]] = []
        if isinstance(context, dict):
            sources.append(context)
        metadata = getattr(response, "metadata", None)
        if isinstance(metadata, dict):
            sources.append(metadata)
        for source in sources:
            for field in candidate_fields:
                try:
                    value = source.get(field)  # type: ignore[call-arg]
                except AttributeError:
                    continue
                if value is None:
                    continue
                candidate = str(value).strip()
                if candidate:
                    return candidate, False
        if stop_event is not None:
            alias = self._anonymous_session_aliases.get(id(stop_event))
            if alias is None:
                alias = uuid4().hex
                self._anonymous_session_aliases[id(stop_event)] = alias
            return alias, False
        return uuid4().hex, True

    def _cleanup_session_state(
        self,
        resolved_session_id: str,
        ephemeral_key: bool,
        stop_event: Any,
    ) -> None:
        if ephemeral_key:
            self._accumulated_content.pop(resolved_session_id, None)
            return
        if stop_event is None:
            return
        alias_id = id(stop_event)
        alias_value = self._anonymous_session_aliases.get(alias_id)
        try:
            is_done = bool(stop_event.is_set())  # type: ignore[attr-defined]
        except AttributeError:
            is_done = False
        if is_done:
            if alias_value is not None:
                self._accumulated_content.pop(alias_value, None)
            self._anonymous_session_aliases.pop(alias_id, None)

    async def process(
        self,
        response: Any,
        session_id: str,
        context: dict[str, Any],
        is_streaming: bool = False,
        stop_event: Any = None,
    ) -> Any:
        """Process a response, checking for loops."""
        resolved_session_id, ephemeral_key = self._resolve_session_key(
            session_id, context, response, stop_event
        )

        try:
            if not response.content:
                return response

            previous = self._accumulated_content.get(resolved_session_id, "")
            self._accumulated_content[resolved_session_id] = previous + response.content
            content = self._accumulated_content[resolved_session_id]

            if len(content) > 100:
                loop_result = await self._loop_detector.check_for_loops(content)
                if loop_result.has_loop:
                    error_message = (
                        "Loop detected: The response contains repetitive content. "
                        f"Detected {loop_result.repetitions} repetitions."
                    )
                    logger.warning(
                        f"Loop detected in session {resolved_session_id}: {loop_result.repetitions} repetitions"
                    )
                    raise LoopDetectionError(
                        message=error_message,
                        details={
                            "repetitions": loop_result.repetitions,
                            "pattern": loop_result.pattern,
                            "session_id": resolved_session_id,
                        },
                    )

            return response
        finally:
            self._cleanup_session_state(resolved_session_id, ephemeral_key, stop_event)

    def reset_session(self, session_id: str) -> None:
        """Reset the accumulated content for a session."""
        if session_id in self._accumulated_content:
            del self._accumulated_content[session_id]
        for alias_id, alias_value in list(self._anonymous_session_aliases.items()):
            if alias_value == session_id:
                self._anonymous_session_aliases.pop(alias_id, None)
