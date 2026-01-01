"""Streaming content conversion for response adapters.

This module contains StreamingContentConverter class for converting raw stream
chunks to StreamingContent, refactoring 670+ line _streaming_adapter closure.
Normalizes ProcessedResponse and raw chunks, decodes SSE payloads, merges
metadata, tracks usage, and detects completion signals.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Iterable
from typing import TYPE_CHECKING, Any, NamedTuple

from pydantic.types import JsonValue

from src.core.app.constants.logging_constants import TRACE_LEVEL
from src.core.domain.streaming.streaming_content import StreamingContent
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.transport.fastapi.adapters.protocols import (
    IReasoningInjector,
    ISSEDecoder,
    IToolBlockBuffer,
    IUsageNormalizer,
)

if TYPE_CHECKING:
    from src.core.domain.request_context import RequestContext
else:
    from src.core.domain.request_context import RequestContext

logger = logging.getLogger(__name__)


class PayloadAndMetadata(NamedTuple):
    """Result of extracting payload and metadata from a chunk.

    Provides named fields for clarity when unpacking the result.
    """

    payload: Any
    metadata: dict[str, JsonValue]


class StreamingContentConverter:
    """Convert raw stream chunks to StreamingContent.

    Refactors the 670+ line _streaming_adapter closure into a testable class.
    Normalizes ProcessedResponse and raw chunks, decodes SSE payloads, merges
    metadata, tracks usage, and detects completion signals.
    """

    def __init__(
        self,
        sse_decoder: ISSEDecoder | None = None,
        reasoning_injector: IReasoningInjector | None = None,
        usage_normalizer: IUsageNormalizer | None = None,
        tool_block_buffer: IToolBlockBuffer | None = None,
    ) -> None:
        """Initialize streaming content converter.

        Args:
            sse_decoder: Optional SSE decoder instance.
                        If not provided, creates default SSEDecoder.
            reasoning_injector: Optional reasoning injector instance.
                               If not provided, creates default ReasoningInjector.
            usage_normalizer: Optional usage normalizer instance.
                             If not provided, creates default UsageNormalizer.
            tool_block_buffer: Optional tool block buffer instance.
                              If not provided, creates default ToolBlockBuffer.
        """
        self._sse_decoder = sse_decoder
        self._reasoning_injector = reasoning_injector
        self._usage_normalizer = usage_normalizer
        self._tool_block_buffer = tool_block_buffer

    async def convert_stream(
        self,
        raw_stream: AsyncIterator[ProcessedResponse],
        context: dict[str, JsonValue | RequestContext | None],
    ) -> AsyncIterator[StreamingContent]:
        """Convert raw chunks to StreamingContent.

        Args:
            raw_stream: Raw stream iterator of ProcessedResponse chunks
            context: Conversion context containing:
                    - envelope_metadata: dict[str, JsonValue] with envelope metadata
                    - context: RequestContext | None for usage recalculation
                    Note: RequestContext is allowed here as it's needed for usage
                    recalculation logic, but envelope_metadata must be JSON-safe.

        Yields:
            StreamingContent chunks
        """
        envelope_metadata_raw = context.get("envelope_metadata", {})
        request_context_raw = context.get("context")

        # Extract typed values from context dict
        # envelope_metadata should be dict[str, JsonValue]
        envelope_metadata: dict[str, JsonValue] = (
            envelope_metadata_raw if isinstance(envelope_metadata_raw, dict) else {}
        )
        # request_context should be RequestContext | None
        request_context: RequestContext | None = (
            request_context_raw
            if isinstance(request_context_raw, RequestContext)
            or request_context_raw is None
            else None
        )

        # Ensure async iterator
        async_stream = self._ensure_async_iterator(raw_stream)

        # Convert to StreamingContent
        async for content in self._convert_to_streaming_content(
            async_stream, envelope_metadata, request_context
        ):
            yield content

    async def _ensure_async_iterator(
        self, source: AsyncIterator[ProcessedResponse] | Iterable[ProcessedResponse]
    ) -> AsyncIterator[ProcessedResponse]:
        """Ensure source is an async iterator.

        Args:
            source: Source iterator (async or sync) of ProcessedResponse chunks

        Yields:
            ProcessedResponse chunks from source iterator
        """
        try:
            if hasattr(source, "__aiter__"):
                async for item in source:  # type: ignore[async-for]
                    yield item
            elif hasattr(source, "__iter__"):
                # Handle sync iterables
                for item in source:  # type: ignore[union-attr]
                    yield item
            else:
                # Not iterable - treat as single item or raise error
                # This handles Mock objects and other non-iterable types
                raise TypeError(
                    f"Content must be an async iterator, sync iterator, or iterable, "
                    f"got {type(source).__name__}"
                )
        except GeneratorExit:
            # Close the source iterator if it supports aclose
            if hasattr(source, "aclose"):
                with contextlib.suppress(Exception):
                    await source.aclose()  # type: ignore[union-attr]
            raise

    def _extract_payload_and_metadata(
        self, chunk: ProcessedResponse
    ) -> PayloadAndMetadata:
        """Extract payload and metadata from ProcessedResponse chunk.

        Args:
            chunk: ProcessedResponse chunk (typed boundary contract)

        Returns:
            PayloadAndMetadata namedtuple with payload and metadata fields
        """
        # At the transport adapter boundary, we only accept ProcessedResponse
        # (per Requirement 2.5, 6.3 - typed contracts at boundaries)
        return PayloadAndMetadata(chunk.content, chunk.metadata or {})

    def _extract_usage_from_metadata(
        self, metadata: dict[str, JsonValue] | None
    ) -> dict[str, Any] | None:
        """Extract usage dict from metadata.

        Args:
            metadata: Metadata dictionary

        Returns:
            Usage dict or None
        """
        if not metadata:
            return None
        usage_block = metadata.get("usage")
        return usage_block if isinstance(usage_block, dict) else None

    def _merge_metadata_from_payload(
        self, payload: Any, metadata: dict[str, JsonValue] | None
    ) -> dict[str, JsonValue]:
        """Merge metadata hints from decoded payload.

        Args:
            payload: Decoded payload
            metadata: Existing metadata

        Returns:
            Merged metadata dictionary
        """
        merged: dict[str, JsonValue] = dict(metadata) if metadata else {}

        if isinstance(payload, dict):
            if "finish_reason" not in merged:
                finish_reason = payload.get("finish_reason")
                if not finish_reason:
                    choices = payload.get("choices")
                    if isinstance(choices, list):
                        for choice in choices:  # type: ignore[reportUnknownVariableType]
                            if isinstance(choice, dict):
                                finish_reason = choice.get("finish_reason")
                                if finish_reason:
                                    break
                if finish_reason:
                    merged["finish_reason"] = finish_reason

            if "error" not in merged and isinstance(payload.get("error"), dict):
                merged["error"] = payload["error"]

            for key in ("id", "model", "created"):
                if key not in merged and key in payload:
                    merged[key] = payload[key]

        return merged

    def _extract_delta_from_payload(self, payload: Any) -> dict[str, Any] | None:
        """Extract delta dict from OpenAI-style payload.

        Args:
            payload: Payload dictionary

        Returns:
            Delta dict or None
        """
        if not isinstance(payload, dict):
            return None
        choices: list[Any] = payload.get("choices", [])  # type: ignore[assignment]
        if not isinstance(choices, list) or not choices:
            return None
        first_choice: dict[str, Any] = choices[0]
        if not isinstance(first_choice, dict):
            return None
        delta = first_choice.get("delta")
        if isinstance(delta, dict):
            return delta
        return None

    def _extract_text_for_usage(self, payload: Any) -> str:
        """Extract textual content for usage calculation.

        Args:
            payload: Payload to extract text from

        Returns:
            Extracted text content
        """
        if isinstance(payload, dict):
            text_parts: list[str] = []
            choices = payload.get("choices")
            if isinstance(choices, list):
                for choice in choices:  # type: ignore[reportUnknownVariableType]
                    if not isinstance(choice, dict):
                        continue
                    block = choice.get("delta") or choice.get("message") or {}
                    if not isinstance(block, dict):
                        continue
                    content_val = block.get("content")
                    if isinstance(content_val, str) and content_val:
                        text_parts.append(content_val)
                if text_parts:
                    return "".join(text_parts)

            for key in ("content", "text"):
                candidate = payload.get(key)
                if isinstance(candidate, str) and candidate:
                    return candidate
            return ""

        if isinstance(payload, bytes | bytearray):
            try:
                return payload.decode("utf-8")
            except Exception as e:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Failed to decode payload as UTF-8: %s", e, exc_info=True
                    )
                return payload.decode("utf-8", errors="ignore")
        if isinstance(payload, str):
            return payload
        return ""

    def _resolve_prompt_hint(
        self, metadata: dict[str, JsonValue] | None, envelope_meta: dict[str, JsonValue]
    ) -> int:
        """Resolve prompt token hint from metadata.

        Args:
            metadata: Chunk metadata
            envelope_meta: Envelope metadata

        Returns:
            Prompt token hint (0 if not found)
        """
        for source in (metadata, envelope_meta):
            if not isinstance(source, dict):
                continue
            outbound_tokens = source.get("outbound_tokens")
            if isinstance(outbound_tokens, int | float):
                try:
                    return int(outbound_tokens)
                except Exception as e:
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Failed to convert outbound_tokens to int: %s",
                            e,
                            exc_info=True,
                        )
                    continue
        return 0

    def _resolve_stream_key(self, metadata: dict[str, JsonValue]) -> str:
        """Resolve stream identifier from metadata.

        Args:
            metadata: Metadata dictionary

        Returns:
            Stream identifier
        """
        # Priority: stream_id > session_id (NOT id, which is per-chunk)
        for candidate_key in ("stream_id", "session_id"):
            value = metadata.get(candidate_key)
            if isinstance(value, str) and value:
                return value
        return "anonymous-stream"

    def _chunk_signals_done(
        self, content: Any, metadata: dict[str, JsonValue] | None
    ) -> bool:
        """Detect if chunk signals stream completion.

        Args:
            content: Chunk content
            metadata: Chunk metadata

        Returns:
            True if chunk signals completion
        """
        # Check for explicit done markers
        if isinstance(metadata, dict):
            if metadata.get("is_done") is True:
                return True
            finish_reason = metadata.get("finish_reason")
            if finish_reason in ("stop", "length", "content_filter", "tool_calls"):
                return True

        # Check content for finish_reason
        if isinstance(content, dict):
            finish_reason = content.get("finish_reason")
            if finish_reason in ("stop", "length", "content_filter", "tool_calls"):
                return True

            # Check choices array
            choices: list[Any] = content.get("choices", [])  # type: ignore[assignment]
            if isinstance(choices, list) and len(choices) > 0:
                first_choice: dict[str, Any] = choices[0]
                if isinstance(first_choice, dict):
                    choice_finish = first_choice.get("finish_reason")
                    if choice_finish in (
                        "stop",
                        "length",
                        "content_filter",
                        "tool_calls",
                    ):
                        return True

        return False

    def _sanitize_multiline_tool_blocks(self, stream_key: str, payload: Any) -> None:
        """Sanitize multiline tool blocks in payload.

        Args:
            stream_key: Stream identifier
            payload: Payload to sanitize (modified in-place)
        """
        delta = self._extract_delta_from_payload(payload)
        if not delta:
            return

        text_value = delta.get("content")
        if not isinstance(text_value, str) or not text_value:
            return

        # Use tool block buffer to process tags
        buffer = self._get_tool_block_buffer()
        updated_text = buffer.buffer(text_value, stream_key)

        if updated_text != text_value:
            delta["content"] = updated_text

    def _flush_pending_tool_blocks(self, stream_key: str, payload: Any) -> None:
        """Flush pending tool blocks into payload.

        Args:
            stream_key: Stream identifier
            payload: Payload to modify (modified in-place)
        """
        buffer = self._get_tool_block_buffer()
        flushed = buffer.flush(stream_key)

        if not flushed:
            return

        delta = self._extract_delta_from_payload(payload)
        if not delta:
            return

        existing = delta.get("content")
        if isinstance(existing, str):
            delta["content"] = existing + flushed
        elif existing is None:
            delta["content"] = flushed
        else:
            delta["content"] = f"{existing}{flushed}"

    async def _convert_to_streaming_content(
        self,
        source: AsyncIterator[ProcessedResponse],
        envelope_metadata: dict[str, JsonValue],
        request_context: RequestContext | None,
    ) -> AsyncIterator[StreamingContent]:
        """Convert raw stream to StreamingContent.

        Args:
            source: Source async iterator of ProcessedResponse chunks
            envelope_metadata: Envelope metadata (JSON-safe values)
            request_context: Optional request context

        Yields:
            StreamingContent chunks
        """
        try:
            chunk_count = 0
            accumulated_text_parts: list[str] = []
            best_usage: dict[str, Any] | None = None

            async for chunk in source:
                chunk_count += 1
                if logger.isEnabledFor(TRACE_LEVEL):
                    logger.log(
                        TRACE_LEVEL, "[STREAMING] Processing chunk #%s", chunk_count
                    )

                payload_and_metadata = self._extract_payload_and_metadata(chunk)
                payload = payload_and_metadata.payload
                metadata = payload_and_metadata.metadata

                # Extract usage from ProcessedResponse if available
                # chunk is always ProcessedResponse at this boundary
                processed_response_usage = (
                    chunk.usage if chunk.usage is not None else None
                )

                # Decode SSE payload
                decoder = self._get_sse_decoder()
                decoded_sse = decoder.decode_payload(payload)
                decoded_payload = decoded_sse.content
                sse_metadata = decoded_sse.metadata
                forced_done = decoded_sse.is_done

                # Merge SSE metadata
                if sse_metadata:
                    updated_metadata = dict(metadata) if metadata else {}
                    updated_metadata.update(sse_metadata)
                    metadata = updated_metadata

                # Merge metadata from payload
                metadata = self._merge_metadata_from_payload(decoded_payload, metadata)

                # Add outbound_tokens from envelope if missing
                # envelope_metadata is always dict[str, JsonValue] at this boundary
                if (
                    "outbound_tokens" in envelope_metadata
                    and "outbound_tokens" not in metadata
                ):
                    with contextlib.suppress(Exception):
                        metadata["outbound_tokens"] = envelope_metadata[
                            "outbound_tokens"
                        ]

                # Resolve stream key and sanitize tool blocks
                stream_key = self._resolve_stream_key(metadata)
                self._sanitize_multiline_tool_blocks(stream_key, decoded_payload)

                # Inject reasoning metadata
                injector = self._get_reasoning_injector()
                enriched = injector.inject_reasoning(
                    decoded_payload, metadata, streaming=True
                )

                # Extract and merge usage
                # Priority: ProcessedResponse.usage > payload usage > metadata usage
                computed_usage = None
                if processed_response_usage is not None:
                    # Convert UsageSummary to dict format for merging
                    computed_usage = processed_response_usage.to_dict()

                if computed_usage is None:
                    usage_payload = (
                        enriched.get("usage") if isinstance(enriched, dict) else None
                    )
                    computed_usage = (
                        usage_payload if isinstance(usage_payload, dict) else None
                    )

                if computed_usage is None:
                    computed_usage = self._extract_usage_from_metadata(metadata)

                # Merge usage keeping highest values
                normalizer = self._get_usage_normalizer()
                if computed_usage:
                    if best_usage is None:
                        best_usage = normalizer.normalize(computed_usage)
                    else:
                        best_usage = normalizer.merge_streaming_usage(
                            best_usage, computed_usage
                        )

                # Accumulate text for usage calculation
                text_for_usage = self._extract_text_for_usage(enriched)
                if text_for_usage:
                    accumulated_text_parts.append(text_for_usage)

                # Check if chunk signals completion
                is_done = forced_done or self._chunk_signals_done(enriched, metadata)

                if is_done:
                    # Flush pending tool blocks
                    self._flush_pending_tool_blocks(stream_key, decoded_payload)

                    # Prepare for final usage recalculation
                    # metadata is always dict[str, Any] at this point
                    accumulated_content = None
                    accumulated_value = metadata.get("accumulated_content")
                    if isinstance(accumulated_value, str):
                        accumulated_content = accumulated_value

                    model_name = None
                    model_candidate = metadata.get("model")
                    if isinstance(model_candidate, str):
                        model_name = model_candidate
                    if model_name is None:
                        envelope_model = envelope_metadata.get("model")
                        if isinstance(envelope_model, str):
                            model_name = envelope_model

                    # Determine if usage recalculation is needed
                    # envelope_metadata is always dict[str, JsonValue] at this boundary
                    force_usage_recalc = bool(
                        metadata.get("allow_usage_recalculation")
                        or envelope_metadata.get("allow_usage_recalculation")
                    )
                    if not force_usage_recalc and request_context is not None:
                        try:
                            force_usage_recalc = (
                                request_context.requires_usage_recalculation()
                            )
                        except Exception as e:
                            if logger.isEnabledFor(logging.DEBUG):
                                logger.debug(
                                    "Failed to check if usage recalculation is required: %s",
                                    e,
                                    exc_info=True,
                                )
                            force_usage_recalc = False

                    if accumulated_content is None:
                        accumulated_content = "".join(accumulated_text_parts)

                    prompt_hint = self._resolve_prompt_hint(metadata, envelope_metadata)

                    # Recalculate usage via service
                    try:
                        from src.core.services.usage_calculation_service import (
                            get_usage_calculation_service,
                        )

                        service = get_usage_calculation_service()
                        computed_usage_raw: Any = service.merge_streaming_usage(
                            accumulated_content=accumulated_content or "",
                            final_chunk_usage=computed_usage,
                            context=request_context,
                            model=model_name,
                            force_recalculation=force_usage_recalc,
                        )
                        computed_usage = computed_usage_raw

                        normalizer = self._get_usage_normalizer()
                        normalized_usage = normalizer.normalize(computed_usage) or {}

                        # Preserve prompt tokens from earlier hints/usages
                        if isinstance(best_usage, dict):
                            prompt_from_best = best_usage.get("prompt_tokens", 0) or 0
                            if prompt_from_best > normalized_usage.get(
                                "prompt_tokens", 0
                            ):
                                normalized_usage["prompt_tokens"] = prompt_from_best

                        # Use prompt_hint (outbound_tokens) when larger
                        if prompt_hint > 0:
                            current_prompt = (
                                normalized_usage.get("prompt_tokens", 0) or 0
                            )
                            if prompt_hint > current_prompt:
                                normalized_usage["prompt_tokens"] = prompt_hint

                        # For completion tokens, honor recalculation when requested,
                        # otherwise keep the higher value
                        if isinstance(best_usage, dict):
                            best_completion = (
                                best_usage.get("completion_tokens", 0) or 0
                            )
                            if not force_usage_recalc and (
                                best_completion
                                > normalized_usage.get("completion_tokens", 0)
                            ):
                                normalized_usage["completion_tokens"] = best_completion

                        # Recompute totals
                        prompt_val = normalized_usage.get("prompt_tokens", 0) or 0
                        completion_val = (
                            normalized_usage.get("completion_tokens", 0) or 0
                        )
                        normalized_usage["total_tokens"] = prompt_val + completion_val

                        # Preserve higher cost
                        if isinstance(best_usage, dict):
                            for cost_key in ("cost", "total_cost"):
                                prev_cost = best_usage.get(cost_key)
                                curr_cost = normalized_usage.get(cost_key)
                                if isinstance(prev_cost, int | float) and (
                                    not isinstance(curr_cost, int | float)
                                    or prev_cost > curr_cost
                                ):
                                    # Type: ignore[assignment] - cost can be float
                                    normalized_usage[cost_key] = prev_cost  # type: ignore[assignment]

                        best_usage = (
                            normalized_usage if normalized_usage else best_usage
                        )

                        # Apply usage to enriched payload
                        if isinstance(best_usage, dict) and isinstance(enriched, dict):
                            try:
                                enriched["usage"] = best_usage
                            except Exception as e:
                                if logger.isEnabledFor(logging.DEBUG):
                                    logger.debug(
                                        "Failed to apply usage to enriched payload (dict): %s",
                                        e,
                                        exc_info=True,
                                    )
                                enriched = dict(enriched)
                                enriched["usage"] = best_usage
                    except Exception as e:
                        if logger.isEnabledFor(logging.DEBUG):
                            logger.debug(
                                "Failed to merge streaming usage: %s",
                                e,
                                exc_info=True,
                            )

                    # If is_done and no usage yet, synthesize from outbound_tokens if available
                    if is_done and best_usage is None:
                        prompt_hint = self._resolve_prompt_hint(
                            metadata, envelope_metadata
                        )
                        if prompt_hint > 0:
                            # Synthesize minimal usage from outbound_tokens
                            best_usage = {
                                "prompt_tokens": prompt_hint,
                                "completion_tokens": 0,
                                "total_tokens": prompt_hint,
                            }
                            # Apply to enriched payload
                            if isinstance(enriched, dict):
                                enriched["usage"] = best_usage

                # Create StreamingContent
                from src.core.domain.usage_summary import UsageSummary

                usage_summary = (
                    UsageSummary.from_dict(best_usage)
                    if isinstance(best_usage, dict)
                    else None
                )
                # Extract stream_id with type check
                stream_id_value = metadata.get("stream_id") if metadata else None
                stream_id: str | None = (
                    stream_id_value if isinstance(stream_id_value, str) else None
                )
                streaming_content = StreamingContent(
                    content=enriched,
                    metadata=metadata,
                    is_done=is_done,
                    stream_id=stream_id,
                    usage=usage_summary,
                )

                yield streaming_content

                # Yield to event loop
                await asyncio.sleep(0)

                if is_done:
                    break

            if logger.isEnabledFor(TRACE_LEVEL):
                logger.log(
                    TRACE_LEVEL,
                    "[STREAMING] Stream completed with %s chunks",
                    chunk_count,
                )

        except GeneratorExit:
            # Client disconnected - this is expected, don't log as error
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("[STREAMING] Client disconnected during stream")
            raise
        except Exception as e:
            if logger.isEnabledFor(logging.ERROR):
                logger.error(
                    "Error during streaming content conversion: %s",
                    e,
                    exc_info=True,
                )
            yield StreamingContent(
                content="",
                metadata={"error": str(e), "finish_reason": "error"},
                is_done=True,
            )

    def _get_sse_decoder(self) -> ISSEDecoder:
        """Get SSE decoder instance (DI or fallback).

        Returns:
            ISSEDecoder instance
        """
        if self._sse_decoder is not None:
            return self._sse_decoder

        from src.core.transport.fastapi.adapters.sse.decoder import SSEDecoder

        return SSEDecoder()

    def _get_reasoning_injector(self) -> IReasoningInjector:
        """Get reasoning injector instance (DI or fallback).

        Returns:
            IReasoningInjector instance
        """
        if self._reasoning_injector is not None:
            return self._reasoning_injector

        from src.core.transport.fastapi.adapters.metadata.reasoning_injector import (
            ReasoningInjector,
        )

        return ReasoningInjector()

    def _get_usage_normalizer(self) -> IUsageNormalizer:
        """Get usage normalizer instance (DI or fallback).

        Returns:
            IUsageNormalizer instance
        """
        if self._usage_normalizer is not None:
            return self._usage_normalizer

        from src.core.transport.fastapi.adapters.usage.normalizer import (
            UsageNormalizer,
        )

        return UsageNormalizer()

    def _get_tool_block_buffer(self) -> IToolBlockBuffer:
        """Get tool block buffer instance (DI or fallback).

        Returns:
            IToolBlockBuffer instance
        """
        if self._tool_block_buffer is not None:
            return self._tool_block_buffer

        from src.core.transport.fastapi.adapters.streaming.tool_block_buffer import (
            ToolBlockBuffer,
        )

        return ToolBlockBuffer()
