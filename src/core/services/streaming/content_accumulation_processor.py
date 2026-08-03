import hashlib
import json
import logging
from typing import Any

from src.core.ports.streaming_contracts import IStreamProcessor, StreamingContent
from src.core.services.streaming.stream_context_registry import (
    StreamBufferState,
    StreamingContextRegistry,
)
from src.core.services.streaming.stream_utils import get_stream_id

logger = logging.getLogger(__name__)


class ContentAccumulationProcessor(IStreamProcessor):
    """
    Stream processor that accumulates content from streaming chunks.

    This processor buffers all streaming content until the stream is complete,
    then returns the full accumulated content. A maximum buffer size is enforced
    to prevent unbounded memory growth from pathologically large streams.

    Fixes memory leak by implementing TTL cleanup of stale stream states that
    don't complete normally (e.g., due to network timeouts, connection failures).
    """

    def __init__(
        self,
        max_buffer_bytes: int = 10 * 1024 * 1024,
        state_ttl_seconds: int = 300,  # 5 minutes default TTL
        registry: StreamingContextRegistry | None = None,
    ) -> None:
        """
        Initialize the content accumulation processor.

        Args:
            max_buffer_bytes: Maximum buffer size in bytes (default: 10MB).
            state_ttl_seconds: Time-to-live for stream states in seconds (default: 300).
                              Stale states older than this will be automatically cleaned up.
        """
        self._max_buffer_bytes = max_buffer_bytes
        self._state_ttl_seconds = state_ttl_seconds
        self._registry = registry or StreamingContextRegistry(state_ttl_seconds)

    def _get_state(self, stream_id: str) -> StreamBufferState:
        return self._registry.get_content_state(stream_id)

    def _cleanup_stale_states(self) -> None:
        """Remove stream states that have expired due to TTL."""
        self._registry.cleanup_expired()

    def reset(self) -> None:
        """Reset the internal buffer so stale content does not leak between streams."""
        self._registry.reset_content_states()

    async def process(self, content: StreamingContent) -> StreamingContent:
        self._cleanup_stale_states()

        stream_id = get_stream_id(content)
        state = self._get_state(stream_id)
        self._reset_state_for_steering_replacement(content, state, stream_id)

        openai_chunk = self._resolve_openai_chunk(content)
        if openai_chunk is not None:
            return self._process_openai_chunk(
                content=content,
                openai_chunk=openai_chunk,
                stream_id=stream_id,
                state=state,
            )

        return self._process_non_openai_chunk(
            content=content,
            stream_id=stream_id,
            state=state,
        )

    @staticmethod
    def _resolve_openai_chunk(content: StreamingContent) -> dict[str, Any] | None:
        if isinstance(content.content, dict) and "choices" in content.content:
            return content.content
        if isinstance(content.raw_data, dict) and "choices" in content.raw_data:
            return content.raw_data
        return None

    @staticmethod
    def _reset_state_for_steering_replacement(
        content: StreamingContent, state: StreamBufferState, stream_id: str
    ) -> None:
        if not (
            content.metadata
            and content.metadata.get("_steering_replacement")
            and (state.chunks or state.reasoning_chunks)
        ):
            return

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "ContentAccumulationProcessor: Clearing %d accumulated chunks "
                "for steering replacement, stream_id=%s",
                len(state.chunks),
                stream_id,
            )
        state.chunks.clear()
        state.encoded_chunks.clear()
        state.chunk_lengths.clear()
        state.byte_length = 0
        state.reasoning_chunks.clear()
        state.metadata_snapshot.clear()
        state.completed = False
        state.has_sent_content = False

    def _process_stop_chunk_with_usage(
        self,
        content: StreamingContent,
        openai_chunk: dict[str, Any],
        stream_id: str,
        state: StreamBufferState,
    ) -> StreamingContent:
        from src.core.domain.usage_summary import UsageSummary
        from src.core.ports.streaming_contracts import StopChunkWithUsage

        assert isinstance(openai_chunk, StopChunkWithUsage)

        usage_info = openai_chunk.get("usage") or content.usage
        output_metadata = dict(content.metadata or {})
        if usage_info:
            output_metadata["usage"] = usage_info

        if state.chunks and not state.has_sent_content:
            final_content = "".join(state.chunks)
            if final_content:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "ContentAccumulationProcessor: Merging %d bytes of buffered content "
                        "into StopChunkWithUsage, stream_id=%s",
                        len(final_content),
                        stream_id,
                    )
                if "choices" not in openai_chunk:
                    openai_chunk["choices"] = [
                        {"index": 0, "delta": {}, "finish_reason": "stop"}
                    ]

                choices = openai_chunk.get("choices")
                if isinstance(choices, list) and choices:
                    first_choice = choices[0]
                    if isinstance(first_choice, dict):
                        delta = first_choice.setdefault("delta", {})
                        if isinstance(delta, dict):
                            existing_content = delta.get("content", "")
                            delta["content"] = existing_content + final_content

                            if state.reasoning_chunks:
                                final_reasoning = "".join(state.reasoning_chunks)
                                existing_reasoning = delta.get("reasoning_content", "")
                                delta["reasoning_content"] = (
                                    existing_reasoning + final_reasoning
                                )

            state.chunks.clear()
            state.encoded_chunks.clear()
            state.chunk_lengths.clear()
            state.byte_length = 0
            state.reasoning_chunks.clear()
            state.completed = True
            self._registry.clear_content_state(stream_id)

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "ContentAccumulationProcessor: Passing through StopChunkWithUsage unchanged, "
                "chunk_id=%s, has_usage=%s, stream_id=%s",
                openai_chunk.get("id", "unknown"),
                usage_info is not None,
                stream_id,
            )

        usage_summary = None
        if isinstance(usage_info, UsageSummary):
            usage_summary = usage_info
        elif isinstance(usage_info, dict):
            usage_summary = UsageSummary.from_dict(usage_info)

        return StreamingContent(
            content=openai_chunk,
            is_done=content.is_done,
            is_cancellation=content.is_cancellation,
            metadata=output_metadata,
            usage=usage_summary,
            raw_data=content.raw_data,
        )

    def _process_openai_chunk(
        self,
        content: StreamingContent,
        openai_chunk: dict[str, Any],
        stream_id: str,
        state: StreamBufferState,
    ) -> StreamingContent:
        from src.core.domain.usage_summary import UsageSummary
        from src.core.ports.streaming_contracts import StopChunkWithUsage

        if isinstance(openai_chunk, StopChunkWithUsage):
            return self._process_stop_chunk_with_usage(
                content=content,
                openai_chunk=openai_chunk,
                stream_id=stream_id,
                state=state,
            )

        choices = openai_chunk.get("choices", [])
        usage_info = openai_chunk.get("usage") or content.usage

        extracted_content = ""
        extracted_reasoning = ""
        if isinstance(choices, list) and choices:
            for choice in choices:
                if not isinstance(choice, dict):
                    continue
                delta = choice.get("delta", {})
                if not isinstance(delta, dict):
                    continue
                delta_content = delta.get("content")
                if isinstance(delta_content, str):
                    extracted_content += delta_content

                # Extract and accumulate reasoning content
                delta_reasoning = (
                    delta.get("reasoning_content")
                    or delta.get("reasoning")
                    or delta.get("thinking")
                    or delta.get("thought")
                )
                if isinstance(delta_reasoning, str):
                    extracted_reasoning += delta_reasoning

        if extracted_content:
            # if logger.isEnabledFor(logging.DEBUG):
            #     logger.debug(
            #         "ContentAccumulationProcessor: Extracted text content, len=%d, stream_id=%s",
            #         len(extracted_content),
            #         stream_id,
            #     )

            encoded_content = extracted_content.encode("utf-8")

            content_length = len(encoded_content)
            state.append_content_chunk(
                extracted_content, encoded_content, content_length
            )

        if extracted_reasoning:
            state.append_reasoning_chunk(extracted_reasoning)

        if content.metadata:
            merged_metadata = dict(state.metadata_snapshot)
            merged_metadata.update(content.metadata)
            state.metadata_snapshot = merged_metadata

        output_metadata = dict(content.metadata or {})
        if content.is_done or content.is_cancellation:
            final_content = "".join(state.chunks)
            output_metadata["accumulated_content"] = final_content
            if state.reasoning_chunks:
                output_metadata["accumulated_reasoning"] = "".join(
                    state.reasoning_chunks
                )
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "ContentAccumulationProcessor: Final accumulated content, "
                    "len=%d, stream_id=%s, has_reasoning=%s",
                    len(final_content),
                    stream_id,
                    bool(state.reasoning_chunks),
                )
            state.chunks.clear()
            state.encoded_chunks.clear()
            state.chunk_lengths.clear()
            state.byte_length = 0
            state.reasoning_chunks.clear()
            state.completed = True
            self._registry.clear_content_state(stream_id)

        state.has_sent_content = True

        usage_summary = None
        if isinstance(usage_info, UsageSummary):
            usage_summary = usage_info
        elif isinstance(usage_info, dict):
            usage_summary = UsageSummary.from_dict(usage_info)

        return StreamingContent(
            content=openai_chunk,
            is_done=content.is_done,
            is_cancellation=content.is_cancellation,
            metadata=output_metadata,
            usage=usage_summary,
            raw_data=content.raw_data,
        )

    def _merge_metadata_snapshot(
        self, state: StreamBufferState, content: StreamingContent, stream_id: str
    ) -> None:
        if content.metadata:
            merged_metadata = dict(state.metadata_snapshot)
            merged_metadata.update(content.metadata)
            state.metadata_snapshot = merged_metadata
        elif state.metadata_snapshot is not None and content.metadata is not None:

            state.metadata_snapshot = dict(content.metadata)

        if stream_id and "stream_id" in state.metadata_snapshot:
            state.metadata_snapshot["stream_id"] = stream_id

    @staticmethod
    def _build_metadata_snapshot(
        state: StreamBufferState, content: StreamingContent
    ) -> dict[str, Any]:
        if state.metadata_snapshot:
            return dict(state.metadata_snapshot)
        if content.metadata:
            return dict(content.metadata)
        return {}

    def _process_non_openai_chunk(
        self, content: StreamingContent, stream_id: str, state: StreamBufferState
    ) -> StreamingContent:
        self._merge_metadata_snapshot(state, content, stream_id)

        if state.completed:
            metadata_snapshot = dict(content.metadata or {})
            metadata_snapshot.pop("tool_calls", None)
            if content.is_done or content.is_cancellation:
                self._registry.clear_content_state(stream_id)
            return StreamingContent(
                content=content.content or "",
                is_done=content.is_done,
                is_cancellation=content.is_cancellation,
                metadata=metadata_snapshot,
                usage=content.usage,
                raw_data=content.raw_data,
            )

        metadata_snapshot = self._build_metadata_snapshot(state, content)
        if content.is_empty and not content.is_done:
            return StreamingContent(
                content="",
                is_done=False,
                is_cancellation=content.is_cancellation,
                metadata=metadata_snapshot,
                usage=content.usage,
                raw_data=content.raw_data,
            )

        raw_chunk = content.content
        if content.metadata:
            reasoning_value = content.metadata.get(
                "reasoning_content"
            ) or content.metadata.get("reasoning")
            if isinstance(reasoning_value, str) and reasoning_value:
                # IMPORTANT: Do NOT strip here. Preserving whitespace is critical for streaming chunks.
                state.append_reasoning_chunk(reasoning_value)

        if raw_chunk:
            chunk_text = ""
            if isinstance(raw_chunk, bytes):
                chunk_text = raw_chunk.decode("utf-8", errors="ignore")
            elif isinstance(raw_chunk, str):
                chunk_text = raw_chunk
            else:
                from src.core.ports.streaming_contracts import StopChunkWithUsage

                if not isinstance(raw_chunk, StopChunkWithUsage):
                    chunk_text = StopChunkWithUsage.safe_json_dumps(raw_chunk)

            if chunk_text:
                encoded_content = chunk_text.encode("utf-8")
                content_length = len(encoded_content)
                state.append_content_chunk(chunk_text, encoded_content, content_length)

        if state.byte_length > self._max_buffer_bytes:
            if not state.truncation_logged:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "ContentAccumulationProcessor buffer exceeded %d bytes (current: %d bytes). "
                        "Truncating to most recent content to prevent memory leak.",
                        self._max_buffer_bytes,
                        state.byte_length,
                    )
                state.truncation_logged = True

            while state.chunks and state.byte_length > self._max_buffer_bytes:
                state.chunks.popleft()
                state.encoded_chunks.popleft()
                removed_length = state.chunk_lengths.popleft()
                state.byte_length -= removed_length

        if content.is_done or content.is_cancellation:
            final_content = "".join(state.chunks)
            metadata_out = metadata_snapshot
            tool_calls = metadata_out.get("tool_calls")
            if isinstance(tool_calls, list):
                unique_calls: list[dict[str, Any]] = []
                seen_signatures: set[tuple[Any | None, str]] = set()
                for call in tool_calls:
                    if not isinstance(call, dict):
                        continue
                    function_block = call.get("function", {})
                    if not isinstance(function_block, dict):
                        continue
                    name = function_block.get("name")
                    args_raw = function_block.get("arguments")
                    normalized_args = self._normalize_tool_call_arguments(args_raw)
                    identifier = call.get("id") or name
                    if not identifier:
                        identifier = self._build_function_identifier(function_block)
                    signature = (identifier, normalized_args)
                    if signature in seen_signatures:
                        continue
                    seen_signatures.add(signature)
                    unique_calls.append(call)
                metadata_out["tool_calls"] = unique_calls
            if state.reasoning_chunks:
                metadata_out["accumulated_reasoning"] = "".join(state.reasoning_chunks)
                current_metadata = content.metadata or {}
                reasoning_keys = (
                    "reasoning_content",
                    "reasoning",
                    "thinking",
                    "thought",
                )
                if not any(current_metadata.get(key) for key in reasoning_keys):
                    for key in reasoning_keys:
                        metadata_out.pop(key, None)
            metadata_out["accumulated_content"] = final_content

            state.chunks.clear()
            state.encoded_chunks.clear()
            state.chunk_lengths.clear()
            state.byte_length = 0
            state.truncation_logged = False
            state.reasoning_chunks.clear()
            state.metadata_snapshot = dict(metadata_out)
            state.completed = True
            self._registry.clear_content_state(stream_id)

            # CRITICAL: If we already streamed OpenAI-style deltas for this stream,
            # do NOT re-emit the full accumulated content on the terminal marker.
            # Doing so duplicates the entire assistant message on the client.
            emit_content = final_content
            if state.has_sent_content:
                emit_content = ""

            return StreamingContent(
                content=emit_content,
                is_done=True,
                metadata=metadata_out,
                usage=content.usage,
                raw_data=content.raw_data,
            )

        interim_metadata = dict(content.metadata)
        interim_metadata.pop("tool_calls", None)
        return StreamingContent(
            content="",
            metadata=interim_metadata,
            usage=content.usage,
            raw_data=content.raw_data,
        )

    @staticmethod
    def _normalize_tool_call_arguments(arguments: Any) -> str:
        """Normalize tool call arguments into a hashable representation."""
        if arguments is None:
            return ""
        if isinstance(arguments, str):
            try:
                return json.dumps(json.loads(arguments), sort_keys=True)
            except json.JSONDecodeError:
                return arguments.strip()
        if isinstance(arguments, dict | list):
            try:
                return json.dumps(arguments, sort_keys=True)
            except (TypeError, ValueError):
                return str(arguments)
        if isinstance(arguments, bytes | bytearray):
            return arguments.decode("utf-8", errors="ignore")
        return str(arguments)

    @staticmethod
    def _build_function_identifier(function_block: dict[str, Any]) -> str:
        """Generate a stable identifier for unnamed tool calls."""
        try:
            serialized = json.dumps(function_block, sort_keys=True)
        except (TypeError, ValueError):
            serialized = repr(function_block)
        digest = hashlib.sha256(serialized.encode("utf-8", "ignore")).hexdigest()
        return f"unnamed-{digest}"
