"""
Reasoning Stream Processor for Hybrid Backend.

This module provides utilities for capturing and extracting reasoning output
from streaming LLM responses. It implements a priority-based detection strategy
to identify when the reasoning phase ends and extract the reasoning content.
"""

from __future__ import annotations

import contextlib
import json
import logging
from collections.abc import AsyncGenerator, AsyncIterator, Mapping
from typing import Any, NamedTuple

from src.connectors.utils.reasoning_models import (
    ReasoningCaptureResult,
    ReasoningDetectionMetadata,
)
from src.core.app.constants.logging_constants import TRACE_LEVEL
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.ports.streaming_contracts import StreamingContent

logger = logging.getLogger(__name__)


class DetectionResult(NamedTuple):
    """Result of reasoning phase detection.

    Provides named fields for clarity when unpacking result.
    """

    detected: bool
    reason: str | None


class ReasoningStreamProcessor:
    """
    Processor for capturing reasoning output from streaming LLM responses.

    This class implements a multi-strategy approach to detect when reasoning
    phase ends and extract the reasoning content from streaming responses.
    """

    # Explicit reasoning end tags (priority order)
    REASONING_END_TAGS = [
        "</think>",  # MiniMax, DeepSeek
        "</thinking>",  # OpenAI, Anthropic
        "</reason>",  # Alternative
        "</reasoning>",  # Generic
    ]

    # Content transition markers (lower priority)
    TRANSITION_MARKERS = [
        "therefore,",
        "in conclusion,",
        "to summarize,",
        "in summary,",
    ]

    # Default limits
    DEFAULT_MAX_TOKENS = 4096
    DEFAULT_MAX_CHARS = 16384

    async def capture_reasoning_stream(
        self,
        response_stream: (
            AsyncIterator[ProcessedResponse] | AsyncGenerator[ProcessedResponse, None]
        ),
        max_tokens: int = DEFAULT_MAX_TOKENS,
        max_chars: int = DEFAULT_MAX_CHARS,
    ) -> ReasoningCaptureResult:
        """
        Capture reasoning output from streaming response.

        This method iterates through the response stream, accumulating chunks
        until the reasoning phase is detected as complete using a priority-based
        detection strategy.

        Args:
            response_stream: Async generator of ProcessedResponse objects
            max_tokens: Maximum tokens to capture (safety limit)
            max_chars: Maximum characters to capture (safety limit)

        Returns:
            ReasoningCaptureResult containing text, completeness flag, and metadata
        """
        chunks: list[dict[str, Any]] = []
        accumulated_content = ""
        detection_metadata = ReasoningDetectionMetadata()
        raw_chunks: list[ProcessedResponse] = []
        tool_call_accumulator: dict[str, dict[str, Any]] = {}
        tool_call_order: list[str] = []
        tool_call_index_map: dict[int, str] = {}

        try:
            async for processed_response in response_stream:
                detection_metadata.chunks_processed += 1
                raw_chunks.append(processed_response)

                raw_content = processed_response.content
                streaming_chunk = None

                # Try to normalize via provider normalizer if provider info is available
                # This ensures provider-specific formats are handled correctly
                provider: str | None = None
                if processed_response.metadata:
                    provider_candidate = processed_response.metadata.get(
                        "provider"
                    ) or processed_response.metadata.get("backend_name")
                    if isinstance(provider_candidate, str):
                        provider = provider_candidate

                if provider and isinstance(raw_content, dict | str | bytes):
                    # Check if content looks like provider-specific format
                    is_provider_specific = False
                    if isinstance(raw_content, dict) and (
                        raw_content.get("type")
                        in (
                            "content_block_delta",
                            "message_delta",
                            "message_start",
                            "content_block_start",
                        )
                        or (
                            "candidates" in raw_content and "choices" not in raw_content
                        )
                    ):
                        is_provider_specific = True

                    if is_provider_specific:
                        try:
                            # Normalize via provider normalizer (async)
                            normalized_chunk = await self._normalize_via_provider(
                                raw_content, provider
                            )
                            if normalized_chunk:
                                streaming_chunk = normalized_chunk
                        except Exception as e:
                            if logger.isEnabledFor(logging.DEBUG):
                                logger.debug(
                                    "Failed to normalize via provider normalizer: %s",
                                    e,
                                    exc_info=True,
                                )
                            # Fall back to from_raw: If provider normalization fails,
                            # delegate to shared parsing. Provider-specific formats will be
                            # treated as opaque dict content per the provider-parsing boundary
                            # enforcement (see design Flow 0). This fallback preserves
                            # backward compatibility but may mask normalization failures.
                            with contextlib.suppress(Exception):
                                streaming_chunk = StreamingContent.from_raw(
                                    processed_response
                                )
                    else:
                        # Transport-neutral format, use from_raw
                        with contextlib.suppress(Exception):
                            streaming_chunk = StreamingContent.from_raw(
                                processed_response
                            )
                else:
                    # No provider info or not provider-specific format, use from_raw
                    with contextlib.suppress(Exception):
                        streaming_chunk = StreamingContent.from_raw(processed_response)

                chunk = self._normalize_chunk(raw_content)
                if chunk is None:
                    if logger.isEnabledFor(logging.DEBUG):
                        try:
                            logger.debug(
                                "Reasoning stream raw chunk could not be normalized: %s",
                                (
                                    raw_content
                                    if isinstance(raw_content, str)
                                    else str(raw_content)
                                ),
                            )
                        except Exception:
                            logger.debug(
                                "Reasoning stream raw chunk could not be normalized (non-serializable)",
                                exc_info=True,
                            )
                    continue

                chunks.append(chunk)

                if logger.isEnabledFor(TRACE_LEVEL):
                    try:
                        logger.log(
                            TRACE_LEVEL,
                            "Reasoning stream chunk parsed: id=%s, model=%s, choices=%d",
                            chunk.get("id"),
                            chunk.get("model"),
                            len(chunk.get("choices", [])),
                        )
                    except Exception:
                        logger.log(
                            TRACE_LEVEL,
                            "Reasoning stream chunk parsed (non-serializable)",
                            exc_info=True,
                        )

                if (
                    isinstance(chunk, dict)
                    and not chunk.get("choices")
                    and logger.isEnabledFor(logging.DEBUG)
                ):
                    try:
                        logger.debug(
                            "Reasoning stream chunk missing 'choices': %s",
                            json.dumps(chunk)[:500],
                        )
                    except Exception:
                        logger.debug(
                            "Reasoning stream chunk missing 'choices' (non-serializable)",
                            exc_info=True,
                        )
                    if not isinstance(raw_content, str):
                        try:
                            logger.debug(
                                "Original raw reasoning chunk: %s",
                                str(raw_content),
                            )
                        except Exception:
                            logger.debug(
                                "Original raw reasoning chunk not serializable",
                                exc_info=True,
                            )

                if isinstance(chunk, dict) and chunk.get("error"):
                    if logger.isEnabledFor(logging.WARNING):
                        try:
                            logger.warning(
                                "Reasoning stream chunk reported error: %s | raw=%s",
                                json.dumps(chunk)[:500],
                                (
                                    raw_content
                                    if isinstance(raw_content, str)
                                    else str(raw_content)
                                ),
                            )
                        except Exception:
                            logger.warning(
                                "Reasoning stream chunk reported error with non-serializable raw content",
                                exc_info=True,
                            )
                    continue

                # Extract content from chunk
                content = self._extract_content_from_chunk(chunk)
                if content:
                    accumulated_content += content
                    detection_metadata.chars_captured = len(accumulated_content)

                self._extract_tool_calls_from_chunk(
                    chunk,
                    tool_call_accumulator,
                    tool_call_order,
                    tool_call_index_map,
                    streaming_chunk.metadata if streaming_chunk else None,
                )

                # Estimate tokens
                tokens = self.estimate_tokens(accumulated_content)
                detection_metadata.tokens_estimated = tokens

                # Priority 1: Check for explicit closing tags
                is_complete, tag = self.detect_by_tags(accumulated_content)
                if is_complete:
                    detection_metadata.method = f"explicit_tag:{tag}"
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Reasoning end detected by explicit tag: %s (chunks: %d, chars: %d)",
                            tag,
                            detection_metadata.chunks_processed,
                            detection_metadata.chars_captured,
                        )
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Stream capture stopping - reasoning phase complete",
                            extra={
                                "detection_method": "explicit_tag",
                                "tag": tag,
                                "chunks_processed": detection_metadata.chunks_processed,
                                "chars_captured": detection_metadata.chars_captured,
                            },
                        )
                    break

                # Priority 2: Check finish_reason in response metadata
                is_complete, reason = self.detect_by_finish_reason(chunk)
                if is_complete:
                    detection_metadata.method = f"finish_reason:{reason}"
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Reasoning end detected by finish_reason: %s (chunks: %d, chars: %d)",
                            reason,
                            detection_metadata.chunks_processed,
                            detection_metadata.chars_captured,
                        )
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Stream capture stopping - reasoning phase complete",
                            extra={
                                "detection_method": "finish_reason",
                                "finish_reason": reason,
                                "chunks_processed": detection_metadata.chunks_processed,
                                "chars_captured": detection_metadata.chars_captured,
                            },
                        )
                    break

                # Priority 3: Check transition markers (with caution)
                is_complete, marker = self.detect_by_markers(accumulated_content)
                if is_complete and self._confirm_transition(accumulated_content):
                    detection_metadata.method = f"transition_marker:{marker}"
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Reasoning end detected by transition marker: %s (chunks: %d, chars: %d)",
                            marker,
                            detection_metadata.chunks_processed,
                            detection_metadata.chars_captured,
                        )
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Stream capture stopping - reasoning phase complete",
                            extra={
                                "detection_method": "transition_marker",
                                "marker": marker,
                                "chunks_processed": detection_metadata.chunks_processed,
                                "chars_captured": detection_metadata.chars_captured,
                            },
                        )
                    break

                # Priority 4: Safety limit - token count
                if tokens >= max_tokens:
                    detection_metadata.method = "token_limit"
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning(
                            "Reasoning capture stopped at token limit: %d >= %d (chunks: %d, chars: %d)",
                            tokens,
                            max_tokens,
                            detection_metadata.chunks_processed,
                            detection_metadata.chars_captured,
                        )
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Stream capture stopping - token limit reached",
                            extra={
                                "detection_method": "token_limit",
                                "tokens": tokens,
                                "max_tokens": max_tokens,
                                "chunks_processed": detection_metadata.chunks_processed,
                                "chars_captured": detection_metadata.chars_captured,
                            },
                        )
                    break

                # Priority 4: Safety limit - character count
                if len(accumulated_content) >= max_chars:
                    detection_metadata.method = "char_limit"
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning(
                            "Reasoning capture stopped at character limit: %d >= %d (chunks: %d)",
                            len(accumulated_content),
                            max_chars,
                            detection_metadata.chunks_processed,
                        )
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Stream capture stopping - character limit reached",
                            extra={
                                "detection_method": "char_limit",
                                "chars": len(accumulated_content),
                                "max_chars": max_chars,
                                "chunks_processed": detection_metadata.chunks_processed,
                            },
                        )
                    break

        except Exception as e:
            logger.error("Error capturing reasoning stream: %s", e, exc_info=True)
            detection_metadata.method = "error"
            detection_metadata.error = str(e)

        # Extract reasoning text from captured chunks
        reasoning_text = self.extract_reasoning_content(chunks)
        reasoning_complete = detection_metadata.method is not None
        detection_metadata.tool_calls = [
            tool_call_accumulator[call_id] for call_id in tool_call_order
        ]
        detection_metadata.raw_chunks = raw_chunks

        return ReasoningCaptureResult(
            reasoning_text=reasoning_text,
            reasoning_complete=reasoning_complete,
            metadata=detection_metadata,
        )

    def _parse_chunk(self, chunk_bytes: bytes) -> dict[str, Any] | None:
        """
        Parse a chunk from bytes to dictionary.

        Handles SSE format (data: {...}) and raw JSON.

        Args:
            chunk_bytes: Raw chunk bytes

        Returns:
            Parsed chunk as dictionary, or None if parsing fails
        """
        try:
            chunk_str = chunk_bytes.decode("utf-8").strip()

            # Handle SSE format: "data: {...}"
            if chunk_str.startswith("data: "):
                chunk_str = chunk_str[6:].strip()

            # Skip [DONE] markers
            if chunk_str == "[DONE]" or chunk_str == "data: [DONE]":
                return None

            # Parse JSON
            if chunk_str:
                parsed_json = json.loads(chunk_str)
                if isinstance(parsed_json, dict):
                    return parsed_json
                return None

            return None

        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.debug("Failed to parse chunk: %s", e)
            return None

    def _extract_content_from_chunk(self, chunk: Mapping[str, Any] | None) -> str:
        """
        Extract text content from a chunk.

        Handles various response formats from different backends.

        Args:
            chunk: Parsed chunk dictionary

        Returns:
            Extracted text content, or empty string if none found
        """
        if chunk is None or not isinstance(chunk, Mapping):
            return ""

        content_parts: list[str] = []

        try:
            streaming_chunk = StreamingContent.from_raw(chunk)
        except Exception:  # pragma: no cover - defensive guard
            streaming_chunk = None

        if streaming_chunk is not None:
            reasoning_value = streaming_chunk.metadata.get("reasoning_content")
            if reasoning_value:
                content_parts.append(self._coerce_text(reasoning_value))

            streaming_content = streaming_chunk.content
            if streaming_content:
                content_parts.append(self._coerce_text(streaming_content))

        if not content_parts:
            # OpenAI format: choices[0].delta.content
            choices = chunk.get("choices", []) if isinstance(chunk, Mapping) else []

            for choice in choices:
                if not isinstance(choice, dict):
                    continue

                delta = choice.get("delta")
                if isinstance(delta, dict):
                    content_parts.append(
                        self._coerce_text(delta.get("reasoning_content"))
                    )
                    content_parts.append(self._coerce_text(delta.get("content")))

                    # Some providers embed reasoning inside "message" even in delta
                    if "message" in delta:
                        content_parts.append(self._coerce_text(delta.get("message")))
                    if "messages" in delta:
                        content_parts.append(self._coerce_text(delta.get("messages")))

                message = choice.get("message")
                if message is not None:
                    content_parts.append(self._coerce_text(message))

        if not content_parts:
            content_parts.append(self._coerce_text(chunk.get("reasoning_content")))
            content_parts.append(self._coerce_text(chunk.get("content")))
            content_parts.append(self._coerce_text(chunk.get("text")))

        return "".join(part for part in content_parts if part)

    def _coerce_text(self, value: Any) -> str:
        """Convert different content payload shapes into text."""

        if value is None:
            return ""

        if isinstance(value, str):
            return value

        if isinstance(value, list):
            return "".join(self._coerce_text(item) for item in value)

        if isinstance(value, dict):
            # Prefer explicit text/content keys
            for key in ("text", "content", "value", "message"):
                if key in value:
                    coerced = self._coerce_text(value[key])
                    if coerced:
                        return coerced
            return ""

        # Fallback: avoid noisy repr for non-string primitives
        if isinstance(value, int | float):
            return str(value)

        return ""

    def _normalize_chunk(self, content: Any) -> dict[str, Any] | None:
        """Normalize ProcessedResponse content to a dictionary chunk."""

        if isinstance(content, dict):
            return content

        if isinstance(content, bytes):
            chunk = self._parse_chunk(content)
            if chunk is not None:
                return chunk
            try:
                text = content.decode("utf-8", errors="ignore")
            except Exception:
                return None
            if text.strip().upper() == "DATA: [DONE]":
                return None
            return {"text": text}

        if isinstance(content, str):
            encoded = content.encode("utf-8")
            chunk = self._parse_chunk(encoded)
            if chunk is not None:
                return chunk
            if content.strip().upper() == "DATA: [DONE]" or content.strip() == "[DONE]":
                return None
            return {"text": content}

        return None

    def detect_by_tags(self, content: str) -> DetectionResult:
        """
        Detect reasoning end by explicit closing tags.

        This is the primary detection method with highest priority.

        Args:
            content: Content to check for tags

        Returns:
            DetectionResult with detected flag and reason (tag)
        """
        content_lower = content.lower()
        for tag in self.REASONING_END_TAGS:
            if tag in content_lower:
                return DetectionResult(True, tag)
        return DetectionResult(False, None)

    def detect_by_finish_reason(self, chunk: dict[str, Any]) -> DetectionResult:
        """
        Detect reasoning end by finish_reason in response metadata.

        This is the secondary detection method.

        Args:
            chunk: Response chunk with potential finish_reason

        Returns:
            DetectionResult with detected flag and reason (finish_reason)
        """
        choices = chunk.get("choices", [])
        for choice in choices:
            finish_reason = choice.get("finish_reason")
            if finish_reason and finish_reason not in ("null", None):
                return DetectionResult(True, finish_reason)
        return DetectionResult(False, None)

    def detect_by_markers(self, content: str) -> DetectionResult:
        """
        Detect reasoning end by content transition markers.

        This is the tertiary detection method (use with caution).
        Less reliable than explicit tags or finish_reason.

        Args:
            content: Content to check for markers

        Returns:
            DetectionResult with detected flag and reason (marker)
        """
        content_lower = content.lower()
        for marker in self.TRANSITION_MARKERS:
            if marker in content_lower:
                return DetectionResult(True, marker)
        return DetectionResult(False, None)

    def _confirm_transition(self, content: str) -> bool:
        """
        Confirm transition marker is actually end of reasoning.

        This prevents premature cancellation on transition markers
        that appear early in the reasoning phase.

        Args:
            content: Accumulated content

        Returns:
            True if transition marker is likely end of reasoning
        """
        # Require minimum reasoning length to avoid premature detection
        return len(content) > 1000

    def extract_reasoning_content(self, chunks: list[dict[str, Any]]) -> str:
        """
        Extract reasoning text from captured chunks.

        Handles different response formats (SSE, JSON chunks) and
        extracts text content from various model response structures.

        Args:
            chunks: List of parsed response chunks

        Returns:
            Concatenated reasoning text
        """
        reasoning_parts: list[str] = []

        for chunk in chunks:
            content = self._extract_content_from_chunk(chunk)
            if content:
                reasoning_parts.append(content)

        return "".join(reasoning_parts)

    def estimate_tokens(self, text: str) -> int:
        """
        Estimate token count for safety limits.

        Uses a simple heuristic: ~4 characters per token on average.
        This is conservative and works across different tokenizers.

        Args:
            text: Text to estimate tokens for

        Returns:
            Estimated token count
        """
        # Simple heuristic: ~4 chars per token
        return len(text) // 4

    async def _normalize_via_provider(
        self, raw_content: Any, provider: str
    ) -> StreamingContent | None:
        """Normalize a single chunk using provider normalizer.

        Args:
            raw_content: Raw content to normalize
            provider: Provider name ("openai", "anthropic", "gemini")

        Returns:
            Normalized StreamingContent chunk, or None if normalization fails
        """
        from src.core.ports.anthropic_normalizer import AnthropicStreamNormalizer
        from src.core.ports.gemini_normalizer import GeminiStreamNormalizer
        from src.core.ports.openai_normalizer import OpenAIStreamNormalizer
        from src.core.ports.streaming.normalizer_base import BaseStreamNormalizer

        # Create appropriate normalizer
        provider_lower = provider.lower()
        normalizer: BaseStreamNormalizer
        if provider_lower == "openai":
            normalizer = OpenAIStreamNormalizer()
        elif provider_lower == "anthropic":
            normalizer = AnthropicStreamNormalizer()
        elif provider_lower == "gemini":
            normalizer = GeminiStreamNormalizer()
        else:
            # Unknown provider, return None to fall back to from_raw
            return None

        # Create single-item async iterator
        async def single_item_stream() -> AsyncIterator[Any]:
            yield raw_content

        # Normalize and get first result
        try:
            async for normalized in normalizer.normalize_stream(
                single_item_stream(), provider
            ):
                return normalized
        except (
            json.JSONDecodeError,
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
        ) as e:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Error normalizing via provider normalizer: %s",
                    e,
                    exc_info=True,
                )
            return None

        return None

    def _extract_tool_calls_from_chunk(
        self,
        chunk: dict[str, Any],
        accumulator: dict[str, dict[str, Any]],
        order: list[str],
        index_map: dict[int, str],
        streaming_metadata: dict[str, Any] | None = None,
    ) -> None:
        """Collect tool call fragments from a parsed chunk."""

        if not isinstance(chunk, dict):
            return

        if streaming_metadata:
            metadata_calls = streaming_metadata.get("tool_calls")
            if isinstance(metadata_calls, list):
                for tool_call in metadata_calls:
                    self._merge_tool_call(tool_call, accumulator, order, index_map)

        self._extract_tool_calls_from_container(chunk, accumulator, order, index_map)

        choices = chunk.get("choices", [])
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            for key in ("delta", "message"):
                container = choice.get(key)
                if isinstance(container, dict):
                    self._extract_tool_calls_from_container(
                        container, accumulator, order, index_map
                    )

    def _extract_tool_calls_from_container(
        self,
        container: dict[str, Any],
        accumulator: dict[str, dict[str, Any]],
        order: list[str],
        index_map: dict[int, str],
    ) -> None:
        """Inspect a container for tool call information."""

        tool_calls = container.get("tool_calls")
        if isinstance(tool_calls, list):
            for tool_call in tool_calls:
                self._merge_tool_call(tool_call, accumulator, order, index_map)

        single_tool_call = container.get("tool_call")
        if isinstance(single_tool_call, dict):
            self._merge_tool_call(single_tool_call, accumulator, order, index_map)

        function_call = container.get("function_call")
        if isinstance(function_call, dict):
            derived = {
                "id": container.get("id"),
                "index": container.get("index"),
                "type": "function",
                "function": function_call,
            }
            self._merge_tool_call(derived, accumulator, order, index_map)

    def _merge_tool_call(
        self,
        tool_call: Any,
        accumulator: dict[str, dict[str, Any]],
        order: list[str],
        index_map: dict[int, str],
    ) -> None:
        """Merge tool call fragments into a consolidated structure."""

        if not isinstance(tool_call, dict):
            return

        call_id = tool_call.get("id") or tool_call.get("tool_call_id")
        index = tool_call.get("index")

        if index is not None:
            try:
                index_int = int(index)
            except (TypeError, ValueError):
                index_int = None
            else:
                index = index_int
        if index is not None:
            if call_id:
                index_map.setdefault(index, call_id)
            else:
                call_id = index_map.get(index)

        if call_id is None:
            function = tool_call.get("function") or tool_call.get("function_call")
            name = None
            if isinstance(function, dict):
                name = function.get("name")
            if name:
                call_id = name

        if call_id is None:
            if index is not None:
                call_id = index_map.setdefault(index, f"tool_call_{index}")
            else:
                call_id = f"tool_call_{len(order)}"

        existing_raw = accumulator.get(call_id)
        if existing_raw is None:
            existing: dict[str, Any] = {
                "id": call_id,
                "type": tool_call.get("type") or "function",
            }
            accumulator[call_id] = existing
            order.append(call_id)
            if index is not None:
                index_map[index] = call_id
        else:
            # Ensure existing is a dict (accumulator is dict[str, dict[str, Any]])
            if not isinstance(existing_raw, dict):
                existing = {
                    "id": call_id,
                    "type": tool_call.get("type") or "function",
                }
                accumulator[call_id] = existing
            else:
                existing = existing_raw
            if index is not None:
                index_map.setdefault(index, call_id)
            if tool_call.get("type") and not existing.get("type"):
                existing["type"] = tool_call["type"]

        incoming_function = tool_call.get("function")
        if isinstance(incoming_function, dict):
            func = existing.setdefault("function", {})
            if incoming_function.get("name") and not func.get("name"):
                func["name"] = incoming_function["name"]
            arguments = incoming_function.get("arguments")
            if arguments:
                func["arguments"] = func.get("arguments", "") + arguments

        incoming_function_call = tool_call.get("function_call")
        if isinstance(incoming_function_call, dict):
            func = existing.setdefault("function", {})
            if incoming_function_call.get("name") and not func.get("name"):
                func["name"] = incoming_function_call["name"]
            arguments = incoming_function_call.get("arguments")
            if arguments:
                func["arguments"] = func.get("arguments", "") + arguments

        for key, value in tool_call.items():
            if key in {
                "id",
                "tool_call_id",
                "index",
                "function",
                "function_call",
                "type",
            }:
                continue
            existing.setdefault(key, value)
