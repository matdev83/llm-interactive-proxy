from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import src.core.services.metrics_service as metrics
from src.core.config.app_config import AppConfig
from src.core.interfaces.response_processor_interface import (
    IResponseFeature,
    IResponseMiddleware,
    ProcessedResponse,
)
from src.core.services.json_repair_service import (
    JsonRepairResult,
    JsonRepairService,
)

logger = logging.getLogger(__name__)


# ============================================================================
# New IResponseFeature implementation with enforced parity
# ============================================================================


class JsonRepairFeature(IResponseFeature):
    """Feature to repair JSON with enforced streaming/non-streaming parity.

    This is the IResponseFeature version of JsonRepairMiddleware that
    explicitly implements both streaming and non-streaming paths with shared
    repair logic.

    For streaming responses, this feature accumulates content across chunks
    and repairs the complete JSON at stream end.

    Thread-safety: Uses asyncio.Lock to protect _stream_content dict from
    concurrent access during streaming operations.
    """

    def __init__(
        self,
        config: AppConfig,
        json_repair_service: JsonRepairService,
        priority: int = 0,
    ) -> None:
        """Initialize the JSON repair feature.

        Args:
            config: Application configuration
            json_repair_service: Service for JSON repair
            priority: Feature priority
        """
        super().__init__(priority)
        self.config = config
        self.json_repair_service = json_repair_service
        # Streaming state: accumulate content per stream for repair
        self._stream_content: dict[str, str] = {}
        # Protect _stream_content from concurrent async access
        self._lock = asyncio.Lock()

    def _get_stream_key(self, session_id: str, context: dict[str, Any]) -> str:
        """Get unique key for tracking stream content."""
        stream_id = context.get("stream_id", "")
        return f"{session_id}:{stream_id}" if stream_id else session_id

    def _determine_strict_mode(self, response: Any, context: dict[str, Any]) -> bool:
        """Determine if strict mode should be used for repair."""
        metadata = (
            getattr(response, "metadata", {}) if hasattr(response, "metadata") else {}
        )
        if not isinstance(metadata, dict):
            metadata = {}

        headers_raw = metadata.get("headers")
        headers: dict[str, Any] = headers_raw if isinstance(headers_raw, dict) else {}
        ct_raw = metadata.get("content_type")
        content_type = (
            ct_raw
            if isinstance(ct_raw, str)
            else headers.get("Content-Type") or headers.get("content-type")
        )
        is_json_ct = (
            isinstance(content_type, str) and "application/json" in content_type.lower()
        )
        expected_json = bool(context.get("expected_json"))
        has_schema = self.config.session.json_repair_schema is not None
        return (
            bool(self.config.session.json_repair_strict_mode)
            or is_json_ct
            or expected_json
            or has_schema
        )

    def _extract_content(self, response: Any) -> str | None:
        """Extract string content from response."""
        if hasattr(response, "content"):
            content = response.content
            return content if isinstance(content, str) else None
        elif isinstance(response, dict):
            content = response.get("content")
            return content if isinstance(content, str) else None
        elif isinstance(response, str):
            return response
        return None

    def _apply_repair(
        self,
        content: str,
        strict: bool,
        mode: str,
    ) -> tuple[JsonRepairResult | None, bool]:
        """Apply JSON repair and return result.

        Returns:
            Tuple of (repair_result, should_raise_on_failure)
        """
        try:
            repair_result = self.json_repair_service.repair_and_validate_json(
                content,
                schema=self.config.session.json_repair_schema,
                strict=strict,
            )
            metric_suffix = (
                "strict_success"
                if strict and repair_result.success
                else (
                    "best_effort_success"
                    if repair_result.success
                    else ("strict_fail" if strict else "best_effort_fail")
                )
            )
            metrics.inc(f"json_repair.{mode}.{metric_suffix}")
            return repair_result, False

        except Exception:
            metrics.inc(
                f"json_repair.{mode}.strict_fail"
                if strict
                else f"json_repair.{mode}.best_effort_fail"
            )
            return None, True

    def _update_response_content(
        self, response: Any, repaired_content: str, session_id: str
    ) -> Any:
        """Update response with repaired content."""
        if hasattr(response, "content"):
            response.content = repaired_content
            if hasattr(response, "metadata") and isinstance(response.metadata, dict):
                response.metadata["repaired"] = True
            return response
        elif isinstance(response, dict):
            response["content"] = repaired_content
            response["repaired"] = True
            return response
        elif isinstance(response, ProcessedResponse):
            metadata = response.metadata or {}
            metadata["repaired"] = True
            return ProcessedResponse(
                content=repaired_content,
                usage=response.usage,
                metadata=metadata,
            )
        else:
            return ProcessedResponse(
                content=repaired_content,
                metadata={"repaired": True},
            )

    def _is_stream_end(self, context: dict[str, Any]) -> bool:
        """Check if this is the end of a stream."""
        if context.get("is_final_chunk"):
            return True
        if context.get("done"):
            return True
        return bool(context.get("finish_reason"))

    async def process_non_streaming(
        self,
        response: Any,
        session_id: str,
        context: dict[str, Any],
    ) -> Any:
        """Repair JSON in non-streaming response."""
        if not self.config.session.json_repair_enabled:
            return response

        content = self._extract_content(response)
        if not content:
            return response

        strict = self._determine_strict_mode(response, context)
        repair_result, should_raise = self._apply_repair(
            content, strict, "non_streaming"
        )

        if should_raise:
            raise

        if repair_result and repair_result.success:
            if logger.isEnabledFor(logging.INFO):
                logger.info("JSON detected and repaired for session %s", session_id)
            return self._update_response_content(
                response, json.dumps(repair_result.content), session_id
            )

        return response

    async def process_streaming(
        self,
        chunk: Any,
        session_id: str,
        context: dict[str, Any],
    ) -> Any:
        """Accumulate streaming content and repair at stream end.

        For streaming, we accumulate content across chunks and repair
        the complete JSON when we detect the end of the stream.
        """
        if not self.config.session.json_repair_enabled:
            return chunk

        stream_key = self._get_stream_key(session_id, context)

        # Accumulate content (protected by lock)
        content = self._extract_content(chunk)
        if content:
            async with self._lock:
                if stream_key not in self._stream_content:
                    self._stream_content[stream_key] = ""
                self._stream_content[stream_key] += content

        # Check if this is the end of the stream
        if self._is_stream_end(context):
            async with self._lock:
                accumulated_content = self._stream_content.pop(stream_key, "")

            if accumulated_content:
                strict = self._determine_strict_mode(chunk, context)
                repair_result, should_raise = self._apply_repair(
                    accumulated_content, strict, "streaming"
                )

                if should_raise:
                    raise

                if repair_result and repair_result.success:
                    if logger.isEnabledFor(logging.INFO):
                        logger.info(
                            "JSON detected and repaired in stream for session %s",
                            session_id,
                        )
                    return self._update_response_content(
                        chunk, json.dumps(repair_result.content), session_id
                    )

        return chunk

    async def reset_session(self, session_id: str) -> None:
        """Reset streaming state for a session."""
        async with self._lock:
            keys_to_remove = [
                k for k in self._stream_content if k.startswith(f"{session_id}:")
            ]
            for key in keys_to_remove:
                self._stream_content.pop(key, None)
            self._stream_content.pop(session_id, None)


# ============================================================================
# Legacy IResponseMiddleware implementation (kept for backward compatibility)
# DEPRECATED: Use JsonRepairFeature instead
# ============================================================================


class JsonRepairMiddleware(IResponseMiddleware):
    """DEPRECATED: Use JsonRepairFeature instead.

    Legacy middleware to detect and repair JSON in LLM responses.
    This class is kept for backward compatibility only.
    """

    def __init__(
        self, config: AppConfig, json_repair_service: JsonRepairService
    ) -> None:
        logger.error(
            "DEPRECATED: JsonRepairMiddleware instantiated. "
            "Use JsonRepairFeature instead for proper streaming/non-streaming parity."
        )
        self.config = config
        self.json_repair_service = json_repair_service

    async def process(
        self,
        response: Any,
        session_id: str,
        context: dict[str, Any],
        is_streaming: bool = False,
        stop_event: Any = None,
    ) -> Any:
        """
        Processes the response to detect and repair JSON if enabled.
        """
        if not self.config.session.json_repair_enabled:
            return response

        # Skip for streaming chunks; handled by JsonRepairProcessor in pipeline
        if context.get("response_type") == "stream":
            return response

        if isinstance(response.content, str):
            # Gate strict mode for non-streaming repairs based on intent
            headers_raw = response.metadata.get("headers")
            headers: dict[str, Any] = (
                headers_raw if isinstance(headers_raw, dict) else {}
            )
            ct_raw = response.metadata.get("content_type")
            content_type = (
                ct_raw
                if isinstance(ct_raw, str)
                else headers.get("Content-Type") or headers.get("content-type")
            )
            is_json_ct = (
                isinstance(content_type, str)
                and "application/json" in content_type.lower()
            )
            expected_json = bool(context.get("expected_json"))
            has_schema = self.config.session.json_repair_schema is not None
            strict_effective = (
                bool(self.config.session.json_repair_strict_mode)
                or is_json_ct
                or expected_json
                or has_schema
            )

            try:
                repair_result: JsonRepairResult = (
                    self.json_repair_service.repair_and_validate_json(
                        response.content,
                        schema=self.config.session.json_repair_schema,
                        strict=strict_effective,
                    )
                )
                metric_suffix = (
                    "strict_success"
                    if strict_effective and repair_result.success
                    else (
                        "best_effort_success"
                        if repair_result.success
                        else ("strict_fail" if strict_effective else "best_effort_fail")
                    )
                )
                metrics.inc(f"json_repair.non_streaming.{metric_suffix}")
            except Exception:
                metrics.inc(
                    "json_repair.non_streaming.strict_fail"
                    if strict_effective
                    else "json_repair.non_streaming.best_effort_fail"
                )
                raise
            if repair_result.success:
                if logger.isEnabledFor(logging.INFO):
                    logger.info(f"JSON detected and repaired for session {session_id}")
                response.content = json.dumps(repair_result.content)
                response.metadata["repaired"] = True

        return response
