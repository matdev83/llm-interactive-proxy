"""
Example feature demonstrating IResponseFeature pattern with enforced parity.

This module provides example implementations showing how to migrate from
IResponseMiddleware to IResponseFeature to enforce streaming/non-streaming parity.

These examples can serve as templates for migrating existing middleware.
"""

from __future__ import annotations

import logging
from typing import Any, cast

from src.core.interfaces.response_processor_interface import (
    FeatureCapability,
    IResponseFeature,
    ProcessedResponse,
)

logger = logging.getLogger(__name__)


class ContentTransformFeature(IResponseFeature):
    """Example feature that transforms content with enforced parity.

    This feature demonstrates how to implement equivalent behavior for both
    streaming and non-streaming paths by sharing transformation logic.

    The key pattern is:
    1. Define a shared transformation method (_transform_content)
    2. Call it from both process_streaming and process_non_streaming
    3. Handle any path-specific concerns (like chunk boundaries) separately
    """

    def __init__(
        self,
        prefix: str = "",
        suffix: str = "",
        priority: int = 0,
    ) -> None:
        """Initialize the content transform feature.

        Args:
            prefix: Text to prepend to content
            suffix: Text to append to content
            priority: Execution priority
        """
        super().__init__(priority)
        self._prefix = prefix
        self._suffix = suffix

    def _transform_content(self, content: str) -> str:
        """Shared transformation logic for both paths.

        This is the key pattern - encapsulate the feature logic in a method
        that both streaming and non-streaming paths can call.

        Args:
            content: The content to transform

        Returns:
            Transformed content
        """
        if not content:
            return content
        return f"{self._prefix}{content}{self._suffix}"

    def _extract_content(self, response: Any) -> str:
        """Extract content from various response types."""
        if isinstance(response, ProcessedResponse):
            return str(response.content) if response.content else ""
        if isinstance(response, dict):
            return str(response.get("content", ""))
        if isinstance(response, str):
            return response
        return str(response) if response else ""

    def _apply_content(self, response: Any, new_content: str) -> Any:
        """Apply transformed content back to response."""
        if isinstance(response, ProcessedResponse):
            return ProcessedResponse(
                content=new_content,
                usage=response.usage,
                metadata=response.metadata,
            )
        if isinstance(response, dict):
            result = response.copy()
            result["content"] = new_content
            return result
        return new_content

    async def process_chunk(
        self,
        payload: Any,
        session_id: str,
        context: dict[str, object],
        *,
        is_streaming: bool,
    ) -> Any:
        """Transform content (full response or chunk-aware streaming)."""
        ctx = cast(dict[str, Any], context)
        if not is_streaming:
            content = self._extract_content(payload)
            transformed = self._transform_content(content)
            return self._apply_content(payload, transformed)

        chunk_index = ctx.get("_chunk_index", 0)
        is_last = ctx.get("is_done", False)
        content = self._extract_content(payload)
        if chunk_index == 0 and self._prefix:
            content = self._prefix + content
        if is_last and self._suffix:
            content = content + self._suffix
        ctx["_chunk_index"] = chunk_index + 1
        return self._apply_content(payload, content)


class ResponseLoggingFeature(IResponseFeature):
    """Example feature that logs responses with enforced parity.

    This demonstrates migrating ResponseLoggingMiddleware to the new pattern.
    The logging behavior is identical for both streaming and non-streaming.
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

    async def process_chunk(
        self,
        payload: Any,
        session_id: str,
        context: dict[str, object],
        *,
        is_streaming: bool,
    ) -> Any:
        """Log one response unit."""
        self._log_response(
            payload,
            session_id,
            cast(dict[str, Any], context),
            is_streaming=is_streaming,
        )
        return payload


class ContentFilterFeature(IResponseFeature):
    """Example feature that filters content with enforced parity.

    This demonstrates migrating ContentFilterMiddleware to the new pattern.
    The filtering logic is shared between both paths.
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
            return ProcessedResponse(content=filtered)

    async def process_chunk(
        self,
        payload: Any,
        session_id: str,
        context: dict[str, object],
        *,
        is_streaming: bool,
    ) -> Any:
        """Filter content (first streaming chunk only for prefix)."""
        ctx = cast(dict[str, Any], context)
        if not is_streaming:
            return self._apply_filter(payload)

        chunk_index = ctx.get("_filter_chunk_index", 0)
        if chunk_index == 0:
            result = self._apply_filter(payload)
        else:
            result = payload
        ctx["_filter_chunk_index"] = chunk_index + 1
        return result


class StreamingOnlyMetricsFeature(IResponseFeature):
    """Example feature that only makes sense for streaming.

    This demonstrates how to declare a feature that intentionally
    provides no-op behavior for one path.
    """

    @property
    def capability(self) -> str:
        """Declare streaming-only capability."""
        return FeatureCapability.STREAMING

    def __init__(self, priority: int = 0) -> None:
        """Initialize the metrics feature."""
        super().__init__(priority)
        self._chunk_counts: dict[str, int] = {}

    async def process_chunk(
        self,
        payload: Any,
        session_id: str,
        context: dict[str, object],
        *,
        is_streaming: bool,
    ) -> Any:
        """Track metrics on streaming path only."""
        ctx = cast(dict[str, Any], context)
        if not is_streaming:
            return payload

        self._chunk_counts[session_id] = self._chunk_counts.get(session_id, 0) + 1
        ctx["streaming_metrics"] = {
            "chunk_count": self._chunk_counts[session_id],
        }
        return payload
