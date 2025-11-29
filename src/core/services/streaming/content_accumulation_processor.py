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
        # Clean up stale states on each request to prevent memory leaks
        self._cleanup_stale_states()

        stream_id = get_stream_id(content)
        state = self._get_state(stream_id)

        # Handle OpenAI-format dict chunks specially - pass through for SSE output
        # while accumulating the extracted text content for metadata
        if isinstance(content.content, dict) and "choices" in content.content:
            # CRITICAL: Check for StopChunkWithUsage FIRST - these must pass through
            # completely unchanged without any content accumulation. StopChunkWithUsage
            # contains usage data that must be preserved at the top level of the SSE
            # output, not embedded in delta.content.
            from src.core.ports.streaming_contracts import StopChunkWithUsage

            if isinstance(content.content, StopChunkWithUsage):
                # Pass through StopChunkWithUsage unchanged - do NOT accumulate
                # Preserve usage data in metadata for downstream processing
                usage_info = content.content.get("usage") or content.usage
                output_metadata = dict(content.metadata or {})
                if usage_info:
                    output_metadata["usage"] = usage_info
                # Log StopChunkWithUsage pass-through at DEBUG level
                logger.debug(
                    "ContentAccumulationProcessor: Passing through StopChunkWithUsage "
                    "unchanged, chunk_id=%s, has_usage=%s, stream_id=%s",
                    content.content.get("id", "unknown"),
                    usage_info is not None,
                    stream_id,
                )
                return StreamingContent(
                    content=content.content,  # Keep original StopChunkWithUsage
                    is_done=content.is_done,
                    is_cancellation=content.is_cancellation,
                    metadata=output_metadata,
                    usage=usage_info if isinstance(usage_info, dict) else None,
                    raw_data=content.raw_data,
                )

            chunk_dict = content.content
            choices = chunk_dict.get("choices", [])
            usage_info = chunk_dict.get("usage") or content.usage

            # Extract actual text content from choices[].delta.content for accumulation
            extracted_content = ""
            if choices and isinstance(choices, list):
                for choice in choices:
                    if isinstance(choice, dict):
                        delta = choice.get("delta", {})
                        if isinstance(delta, dict):
                            delta_content = delta.get("content")
                            if isinstance(delta_content, str):
                                extracted_content += delta_content

            # Log text content extraction at DEBUG level
            if extracted_content:
                logger.debug(
                    "ContentAccumulationProcessor: Extracted text content, "
                    "len=%d, stream_id=%s",
                    len(extracted_content),
                    stream_id,
                )

            # Accumulate extracted content (but don't modify the chunk for output)
            if extracted_content:
                encoded_content = extracted_content.encode("utf-8")
                content_length = len(encoded_content)
                state.chunks.append(extracted_content)
                state.encoded_chunks.append(encoded_content)
                state.chunk_lengths.append(content_length)
                state.byte_length += content_length

            # Merge metadata
            if content.metadata:
                merged_metadata = dict(state.metadata_snapshot)
                merged_metadata.update(content.metadata)
                state.metadata_snapshot = merged_metadata

            # Build output metadata
            output_metadata = dict(content.metadata or {})

            # For final chunk, add accumulated content to metadata
            if content.is_done or content.is_cancellation:
                final_content = "".join(state.chunks)
                output_metadata["accumulated_content"] = final_content
                if state.reasoning_chunks:
                    output_metadata["accumulated_reasoning"] = "".join(
                        state.reasoning_chunks
                    )
                # Log final accumulated content at DEBUG level
                logger.debug(
                    "ContentAccumulationProcessor: Final accumulated content, "
                    "len=%d, stream_id=%s, has_reasoning=%s",
                    len(final_content),
                    stream_id,
                    bool(state.reasoning_chunks),
                )
                # Clear state
                state.chunks.clear()
                state.encoded_chunks.clear()
                state.chunk_lengths.clear()
                state.byte_length = 0
                state.reasoning_chunks.clear()
                state.completed = True
                self._registry.clear_content_state(stream_id)

            # Pass through the original OpenAI-format chunk unchanged for SSE output
            # This ensures the client receives proper SSE chunks with choices/delta structure
            return StreamingContent(
                content=content.content,  # Keep original dict for SSE serialization
                is_done=content.is_done,
                is_cancellation=content.is_cancellation,
                metadata=output_metadata,
                usage=usage_info if isinstance(usage_info, dict) else None,
                raw_data=content.raw_data,
            )

        # Merge metadata so downstream processors have a holistic view
        if content.metadata:
            merged_metadata = dict(state.metadata_snapshot)
            merged_metadata.update(content.metadata)
            state.metadata_snapshot = merged_metadata
        elif not state.metadata_snapshot and content.metadata is not None:
            state.metadata_snapshot = dict(content.metadata)

        if stream_id and "stream_id" in state.metadata_snapshot:
            state.metadata_snapshot["stream_id"] = stream_id

        def _build_metadata() -> dict[str, Any]:
            if state.metadata_snapshot:
                return dict(state.metadata_snapshot)
            if content.metadata:
                return dict(content.metadata)
            return {}

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

        if content.is_empty and not content.is_done:
            # Preserve metadata/usage even when the chunk has no text so downstream
            # processors (e.g., usage accounting) still receive the updated values.
            return StreamingContent(
                content="",
                is_done=False,
                is_cancellation=content.is_cancellation,
                metadata=_build_metadata(),
                usage=content.usage,
                raw_data=content.raw_data,
            )

        # Add content to buffer and update byte length incrementally
        raw_chunk = content.content
        reasoning_value: str | None = None
        if content.metadata:
            reasoning_value = content.metadata.get(
                "reasoning_content"
            ) or content.metadata.get("reasoning")
            if isinstance(reasoning_value, str):
                normalized_reasoning = reasoning_value.strip()
                if normalized_reasoning:
                    state.reasoning_chunks.append(normalized_reasoning)

        if raw_chunk:
            if isinstance(raw_chunk, bytes):
                chunk_text = raw_chunk.decode("utf-8", errors="ignore")
            elif isinstance(raw_chunk, str):
                chunk_text = raw_chunk
            else:
                # Check for StopChunkWithUsage - don't accumulate usage chunks as content
                from src.core.ports.streaming_contracts import StopChunkWithUsage

                if isinstance(raw_chunk, StopChunkWithUsage):
                    # Skip accumulating stop chunks with usage - they should be
                    # passed through as-is for proper SSE serialization
                    chunk_text = ""
                else:
                    # Use safe_json_dumps to handle StopChunkWithUsage correctly
                    # (though we should never reach here for StopChunkWithUsage due to check above)
                    chunk_text = StopChunkWithUsage.safe_json_dumps(raw_chunk)
            # OPTIMIZATION: Encode content ONCE and cache both string and bytes
            encoded_content = chunk_text.encode("utf-8")
            content_length = len(encoded_content)

            state.chunks.append(chunk_text)
            state.encoded_chunks.append(encoded_content)
            state.chunk_lengths.append(content_length)
            state.byte_length += content_length

        # Enforce buffer size limit to prevent unbounded memory growth
        if state.byte_length > self._max_buffer_bytes:
            if not state.truncation_logged:
                logger.warning(
                    f"ContentAccumulationProcessor buffer exceeded {self._max_buffer_bytes} bytes "
                    f"(current: {state.byte_length} bytes). Truncating to most recent content to prevent memory leak."
                )
                state.truncation_logged = True

            # Remove chunks from the left until we're under the limit
            # OPTIMIZATION: Use cached lengths instead of re-encoding
            while state.chunks and state.byte_length > self._max_buffer_bytes:
                state.chunks.popleft()
                state.encoded_chunks.popleft()
                removed_length = state.chunk_lengths.popleft()
                state.byte_length -= removed_length

        if content.is_done or content.is_cancellation:
            # OPTIMIZATION: Use cached string chunks for final assembly
            # We could use cached bytes and decode, but string join is already optimal for this use case
            final_content = "".join(state.chunks)
            metadata_out = _build_metadata()
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
            metadata_out["accumulated_content"] = final_content
            state.chunks.clear()
            state.encoded_chunks.clear()
            state.chunk_lengths.clear()
            state.byte_length = 0
            state.truncation_logged = False
            state.reasoning_chunks.clear()
            state.metadata_snapshot = dict(metadata_out)
            state.completed = True
            if content.is_done or content.is_cancellation:
                self._registry.clear_content_state(stream_id)
            return StreamingContent(
                content=final_content,
                is_done=True,
                metadata=metadata_out,
                usage=content.usage,
                raw_data=content.raw_data,
            )
        else:
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
