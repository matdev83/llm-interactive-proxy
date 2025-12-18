"""
SSE serializer for streaming content.

This module contains the SSE serialization logic, including framing,
done markers, and tool-call sanitization.
"""

from __future__ import annotations

import base64
import json
import logging
from typing import Any, cast

from src.core.app.constants.logging_constants import TRACE_LEVEL
from src.core.domain.streaming.contracts import StreamingChunk
from src.core.domain.streaming.sentinels import SentinelManager
from src.core.domain.streaming.stop_chunk_with_usage import (
    StopChunkWithUsage,
    UsageChunkLeakError,
)
from src.core.domain.streaming.streaming_content import StreamingContent

logger = logging.getLogger(__name__)


class SSESerializer:
    """Serializer for converting StreamingContent to SSE bytes.

    This serializer handles:
    - SSE framing (data: {payload}\\n\\n)
    - Done markers (data: [DONE]\\n\\n)
    - Tool-call sanitization (removing internal markers)
    - StopChunkWithUsage special handling
    - Error and cancellation handling
    """

    def _serialize_stop_chunk_with_usage(self, content: StreamingContent) -> bytes:
        """Serialize StopChunkWithUsage to SSE bytes with usage at top level."""
        # Convert to plain dict to avoid triggering __str__ protection
        assert isinstance(content.content, StopChunkWithUsage)
        plain_dict = dict(content.content)
        logger.debug(
            "[STREAMING] StreamingContent.to_bytes: Emitting StopChunkWithUsage "
            "as top-level SSE with usage, chunk_id=%s, usage=%s",
            plain_dict.get("id", "unknown"),
            plain_dict.get("usage"),
        )
        return f"data: {json.dumps(plain_dict)}\n\ndata: [DONE]\n\n".encode()

    def _serialize_error_chunk(
        self, chunk: StreamingChunk, content: StreamingContent
    ) -> bytes | None:
        """Serialize error chunk to SSE bytes. Returns None if not an error chunk."""
        # Check for error metadata first
        if chunk.metadata.finish_reason == "error" and (
            chunk.metadata.error is not None or "error" in content.metadata
        ):
            # Get error dict - prefer typed contract, fallback to original metadata
            if chunk.metadata.error is not None:
                error_dict = chunk.metadata.error.model_dump(exclude_none=True)
            else:
                # Fallback: use original error dict if typed conversion failed
                error_dict = content.metadata.get("error", {})
                if not isinstance(error_dict, dict):
                    error_dict = {}

            error_data = {
                "choices": [{"delta": {}, "finish_reason": "error"}],
                "error": error_dict,
            }

            # Extract additional metadata fields (use original for non-typed fields)
            for key in ["id", "model", "created"]:
                if key in content.metadata:
                    error_data[key] = content.metadata[key]
            return f"data: {json.dumps(error_data)}\n\ndata: [DONE]\n\n".encode()

        # If content already carries error payload, preserve it
        if isinstance(content.content, dict) and content.content.get("error"):
            return f"data: {json.dumps(content.content)}\n\ndata: [DONE]\n\n".encode()

        return None

    def _serialize_cancellation_chunk(
        self, chunk: StreamingChunk, content: StreamingContent
    ) -> bytes | None:
        """Serialize cancellation chunk to SSE bytes. Returns None if not cancellation."""
        if chunk.is_cancellation and chunk.payload.kind != "empty":
            data = {
                "choices": [{"delta": {"content": str(content.content)}}],
                "finish_reason": "cancelled",
            }
            # Extract additional metadata fields (use original for non-typed fields)
            for key in ["id", "model", "created"]:
                if key in content.metadata:
                    data[key] = content.metadata[key]
            return f"data: {json.dumps(data)}\n\ndata: [DONE]\n\n".encode()

        return None

    def _serialize_done_chunk(
        self, chunk: StreamingChunk, content: StreamingContent
    ) -> bytes:
        """Serialize done chunk to SSE bytes (may include content or just [DONE])."""
        if content._is_empty_completion_payload():
            return b"data: [DONE]\n\n"

        # Check if content is just "[DONE]" marker (treat as pure done marker)
        content_is_done_marker = (
            content.content == "[DONE]"
            or content.content == SentinelManager.DONE_MARKER
            or content.content == b"[DONE]"
        )

        if (
            content.content is not None
            and content.content != ""
            and not content_is_done_marker
        ):
            # If content is already an OpenAI-formatted chunk, emit it then [DONE]
            if isinstance(content.content, dict) and "choices" in content.content:
                return self._serialize_openai_chunk_with_done(chunk, content)

            # Otherwise, fall through to normal content handling below
        else:
            # No meaningful content or content is just "[DONE]", emit [DONE]
            return b"data: [DONE]\n\n"

        # If we get here, there's content but it's not OpenAI-formatted
        # Fall back to normal chunk serialization (shouldn't happen for done chunks)
        return self._serialize_normal_chunk(chunk, content)

    def serialize(self, content: StreamingContent) -> bytes:
        """Serialize StreamingContent to SSE bytes.

        Args:
            content: The StreamingContent instance to serialize

        Returns:
            Bytes representation suitable for SSE streaming

        Raises:
            UsageChunkLeakError: If StopChunkWithUsage is incorrectly handled
        """
        # Log SSE serialization at TRACE level for diagnostic tracking
        if logger.isEnabledFor(TRACE_LEVEL):
            content_type = type(content.content).__name__
            has_usage = (
                isinstance(content.content, dict) and "usage" in content.content
            ) or content.usage is not None
            logger.log(
                TRACE_LEVEL,
                "[STREAMING] StreamingContent.to_bytes: Serializing chunk to SSE, "
                "content_type=%s, is_done=%s, has_usage=%s, is_stop_chunk_with_usage=%s",
                content_type,
                content.is_done,
                has_usage,
                isinstance(content.content, StopChunkWithUsage),
            )

        # CRITICAL: Handle StopChunkWithUsage at the very start to ensure
        # usage data is serialized correctly at the top level, not in delta.content.
        # This prevents the usage data leak bug where JSON chunks appear in
        # conversation history.
        if isinstance(content.content, StopChunkWithUsage):
            return self._serialize_stop_chunk_with_usage(content)

        # Convert to typed contract for internal processing
        chunk = content.to_typed_chunk()

        if chunk.is_done:
            # Handle error chunks
            error_bytes = self._serialize_error_chunk(chunk, content)
            if error_bytes is not None:
                return error_bytes

            # Handle cancellation chunks
            cancellation_bytes = self._serialize_cancellation_chunk(chunk, content)
            if cancellation_bytes is not None:
                return cancellation_bytes

            # Handle done markers
            return self._serialize_done_chunk(chunk, content)

        # Build delta object for non-done chunks
        return self._serialize_normal_chunk(chunk, content)

    def _normalize_openai_chat_completion_to_stream_chunk(
        self, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Normalize `choices[].message` payloads into `choices[].delta` for SSE.

        Some internal proxy paths may generate a non-streaming OpenAI chat payload
        (`object: chat.completion` with `choices[].message`) but still deliver it
        over SSE. Streaming clients expect `choices[].delta` to exist on every
        chunk; emitting `message` inside a stream can crash strict parsers.
        """
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            return payload

        payload_object = payload.get("object")
        normalized_choices: list[Any] = []
        converted_any = False

        for choice in choices:
            if not isinstance(choice, dict):
                normalized_choices.append(choice)
                continue

            if "delta" in choice:
                normalized_choices.append(choice)
                continue

            message = choice.get("message")
            if isinstance(message, dict):
                new_choice = dict(choice)
                new_choice.pop("message", None)
                delta = dict(message)
                if delta.get("content") is None:
                    delta["content"] = ""
                new_choice["delta"] = delta
                normalized_choices.append(new_choice)
                converted_any = True
                continue

            new_choice = dict(choice)
            new_choice.setdefault("delta", {})
            normalized_choices.append(new_choice)
            converted_any = True

        if not converted_any and payload_object != "chat.completion":
            return payload

        normalized = dict(payload)
        normalized["choices"] = normalized_choices
        if payload_object == "chat.completion":
            normalized["object"] = "chat.completion.chunk"
        return normalized

    def _serialize_openai_chunk_with_done(
        self, chunk: StreamingChunk, content: StreamingContent
    ) -> bytes:
        """Serialize an OpenAI-formatted chunk with done marker.

        Args:
            chunk: Typed StreamingChunk contract
            content: Original StreamingContent for accessing non-typed fields
        """
        # Check if tool_calls are "virtual" (extracted from XML content).
        # Virtual tool calls should NOT be sent to client - they're only
        # used internally for unified processing. The XML remains in content.
        # Note: _virtual_tool_calls is not in typed contract, use original metadata
        is_virtual = content.metadata.get("_virtual_tool_calls", False)

        # Make a copy of content to potentially modify
        # CRITICAL: We must avoid modifying content.content deeply/in-place,
        # as it might be used elsewhere (e.g. history storage).
        # Shallow copy of the top object is not enough if we modify nested lists/dicts.
        # Type safety: caller ensures content.content is a dict with "choices"
        content_copy = dict(
            self._normalize_openai_chat_completion_to_stream_chunk(
                cast(dict[str, Any], content.content)
            )
        )

        # Sanitize any existing tool_calls in delta/message (remove extra_content)
        # This is critical for Gemini responses where extra_content contains
        # a thought_signature that CLI agents like Factory Droid cannot parse.
        # We must structurally copy the hierarchy we modify.
        existing_choices = content_copy.get("choices", [])
        if isinstance(existing_choices, list) and existing_choices:
            new_choices = []
            choices_modified = False

            for choice_item in existing_choices:
                if not isinstance(choice_item, dict):
                    new_choices.append(choice_item)
                    continue

                # Copy the choice dict so we can safely modify it
                # (we only modify if we find tool_calls)
                new_choice = dict(choice_item)
                choice_modified = False

                for container_key in ("delta", "message"):
                    container = new_choice.get(container_key)
                    if isinstance(container, dict):
                        tc_list = container.get("tool_calls")
                        # If virtual, we want to remove tool_calls entirely
                        if is_virtual:
                            if "tool_calls" in container:
                                # Copy container to modify
                                new_container = dict(container)
                                del new_container["tool_calls"]
                                new_choice[container_key] = new_container
                                choice_modified = True
                        # If not virtual, we want to sanitize tool_calls
                        elif isinstance(tc_list, list) and tc_list:
                            # Sanitize internal markers
                            sanitized_calls = [
                                {
                                    k: v
                                    for k, v in tc.items()
                                    if not k.startswith("_") and k != "extra_content"
                                }
                                for tc in tc_list
                                if isinstance(tc, dict)
                            ]
                            # Copy container to modify
                            new_container = dict(container)
                            new_container["tool_calls"] = sanitized_calls
                            new_choice[container_key] = new_container
                            choice_modified = True

                if choice_modified:
                    choices_modified = True
                new_choices.append(new_choice)

            if choices_modified:
                content_copy["choices"] = new_choices

        # If is_virtual was handled above within the loop (by removing tool_calls),
        # content_copy is already ready.
        if is_virtual:
            return f"data: {json.dumps(content_copy)}\n\ndata: [DONE]\n\n".encode()

        # Non-virtual: Inject tool_calls from typed metadata into the delta if present
        tool_calls = chunk.metadata.tool_calls
        if tool_calls:
            # Convert ToolCall objects to dicts and sanitize internal markers
            sanitized_calls = []
            for tc in tool_calls:
                if hasattr(tc, "model_dump"):
                    tc_dict = tc.model_dump(exclude_none=True)
                elif isinstance(tc, dict):
                    tc_dict = tc
                else:
                    continue
                # Sanitize internal markers
                sanitized_dict = {
                    k: v
                    for k, v in tc_dict.items()
                    if not k.startswith("_") and k != "extra_content"
                }
                if sanitized_dict:
                    sanitized_calls.append(sanitized_dict)

            if sanitized_calls:
                # Ensure choices and delta exist
                choices = content_copy.get("choices", [])
                if choices and isinstance(choices[0], dict):
                    inner_delta = choices[0].get("delta", {})
                    if isinstance(inner_delta, dict):
                        inner_delta["tool_calls"] = sanitized_calls
                        choices[0]["delta"] = inner_delta
                        content_copy["choices"] = choices
                return f"data: {json.dumps(content_copy)}\n\ndata: [DONE]\n\n".encode()
        # Use dict() to safely convert StopChunkWithUsage to plain dict
        return f"data: {json.dumps(content_copy)}\n\ndata: [DONE]\n\n".encode()

    def _sanitize_tool_calls(
        self, tool_calls: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Sanitize tool_calls by removing internal markers."""
        return [
            {
                k: v
                for k, v in tc.items()
                if not k.startswith("_") and k != "extra_content"
            }
            for tc in tool_calls
            if isinstance(tc, dict)
        ]

    def _sanitize_chunk_tool_calls_in_place(self, content_copy: dict[str, Any]) -> None:
        """Sanitize tool_calls in choices[].delta/message in place."""
        for choice_item in content_copy.get("choices", []):
            if not isinstance(choice_item, dict):
                continue
            for container_key in ("delta", "message"):
                container = choice_item.get(container_key)
                if not isinstance(container, dict):
                    continue
                tc_list = container.get("tool_calls")
                if isinstance(tc_list, list) and tc_list:
                    container["tool_calls"] = self._sanitize_tool_calls(tc_list)

    def _handle_virtual_tool_calls(
        self, content_copy: dict[str, Any]
    ) -> dict[str, Any]:
        """Strip virtual tool_calls from delta."""
        choices = content_copy.get("choices", [])
        if not (choices and isinstance(choices[0], dict)):
            return content_copy

        inner_delta = choices[0].get("delta", {})
        if isinstance(inner_delta, dict) and "tool_calls" in inner_delta:
            inner_delta = dict(inner_delta)
            del inner_delta["tool_calls"]
            choices[0] = dict(choices[0])
            choices[0]["delta"] = inner_delta
            content_copy["choices"] = choices
        return content_copy

    def _inject_tool_calls_into_chunk(
        self, content_copy: dict[str, Any], tool_calls: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Inject tool_calls into chunk delta."""
        sanitized_calls = self._sanitize_tool_calls(tool_calls)
        if not sanitized_calls:
            return content_copy

        choices = content_copy.get("choices", [])
        if not (choices and isinstance(choices[0], dict)):
            return content_copy

        inner_delta = choices[0].get("delta", {})
        if isinstance(inner_delta, dict):
            inner_delta["tool_calls"] = sanitized_calls
            choices[0]["delta"] = inner_delta
            content_copy["choices"] = choices
        return content_copy

    def _serialize_openai_formatted_dict(
        self,
        working_content: dict[str, Any],
        chunk: StreamingChunk,
        content: StreamingContent,
    ) -> bytes:
        """Serialize an OpenAI-formatted dict chunk.

        Args:
            working_content: The dict content to serialize
            chunk: Typed StreamingChunk contract
            content: Original StreamingContent for accessing non-typed fields
        """
        # Note: _virtual_tool_calls is not in typed contract, use original metadata
        is_virtual_tc = content.metadata.get("_virtual_tool_calls", False)

        # Make a copy and normalize
        content_copy = dict(
            self._normalize_openai_chat_completion_to_stream_chunk(working_content)
        )

        # Sanitize existing tool_calls
        self._sanitize_chunk_tool_calls_in_place(content_copy)

        # Handle virtual vs non-virtual tool_calls
        if is_virtual_tc:
            content_copy = self._handle_virtual_tool_calls(content_copy)
        else:
            # Inject tool_calls from typed metadata if present
            tool_calls_to_inject = chunk.metadata.tool_calls
            if tool_calls_to_inject:
                # Convert ToolCall objects to dicts
                tool_calls_dicts = []
                for tc in tool_calls_to_inject:
                    if hasattr(tc, "model_dump"):
                        tool_calls_dicts.append(tc.model_dump(exclude_none=True))
                    elif isinstance(tc, dict):
                        tool_calls_dicts.append(tc)
                if tool_calls_dicts:
                    content_copy = self._inject_tool_calls_into_chunk(
                        content_copy, tool_calls_dicts
                    )

        result = f"data: {json.dumps(content_copy)}\n\n"
        if chunk.is_done:
            result += "data: [DONE]\n\n"
        return result.encode()

    def _build_delta_metadata(
        self, chunk: StreamingChunk, content: StreamingContent, delta: dict[str, Any]
    ) -> None:
        """Build delta metadata (role, tool_call_id, tool_calls, reasoning).

        Args:
            chunk: Typed StreamingChunk contract
            content: Original StreamingContent for accessing non-typed fields
            delta: Dictionary to populate with delta metadata
        """
        # Add role if present (from typed contract)
        if chunk.metadata.role:
            delta["role"] = chunk.metadata.role

        # Add tool_call_id if present (not in typed contract, use original)
        tool_call_id = content.metadata.get("tool_call_id")
        if isinstance(tool_call_id, str) and tool_call_id:
            delta["tool_call_id"] = tool_call_id

        # Add tool_calls if present and not virtual
        # Note: _virtual_tool_calls is not in typed contract, use original metadata
        is_virtual = content.metadata.get("_virtual_tool_calls", False)
        tool_calls = chunk.metadata.tool_calls
        if tool_calls and not is_virtual:
            # Convert ToolCall objects to dicts and sanitize
            tool_calls_dicts = []
            for tc in tool_calls:
                if hasattr(tc, "model_dump"):
                    tool_calls_dicts.append(tc.model_dump(exclude_none=True))
                elif isinstance(tc, dict):
                    tool_calls_dicts.append(tc)
            if tool_calls_dicts:
                sanitized_calls = self._sanitize_tool_calls(tool_calls_dicts)
                if sanitized_calls:
                    delta["tool_calls"] = sanitized_calls

        # Add reasoning content if present (from typed contract)
        reasoning_value = chunk.metadata.reasoning_content
        if reasoning_value and reasoning_value.strip():
            delta["reasoning_content"] = reasoning_value
            delta.setdefault("reasoning", reasoning_value)

    def _serialize_normal_chunk(
        self, chunk: StreamingChunk, content: StreamingContent
    ) -> bytes:
        """Serialize a normal (non-done) chunk.

        Args:
            chunk: Typed StreamingChunk contract
            content: Original StreamingContent for accessing non-typed fields
        """
        # Build delta object
        delta: dict[str, Any] = {}

        # Add metadata to delta
        self._build_delta_metadata(chunk, content, delta)

        # Add main content from typed payload
        if chunk.payload.kind == "text" and chunk.payload.text is not None:
            delta["content"] = chunk.payload.text
        elif chunk.payload.kind == "opaque_json" and chunk.payload.opaque_json:
            # Parse JSON to check if it's OpenAI-formatted
            try:
                parsed_content = json.loads(chunk.payload.opaque_json)
                if isinstance(parsed_content, dict):
                    # Check if OpenAI-formatted chunk
                    if "choices" in parsed_content or "usage" in parsed_content:
                        return self._serialize_openai_formatted_dict(
                            parsed_content, chunk, content
                        )

                    # Check for StopChunkWithUsage misuse
                    if isinstance(content.content, StopChunkWithUsage):
                        raise UsageChunkLeakError(
                            chunk_id=(
                                parsed_content.get("id")
                                if isinstance(parsed_content, dict)
                                else None
                            )
                        )

                    delta["content"] = chunk.payload.opaque_json
                else:
                    delta["content"] = chunk.payload.opaque_json
            except json.JSONDecodeError:
                delta["content"] = chunk.payload.opaque_json
        elif chunk.payload.kind == "binary" and chunk.payload.binary_b64:
            # Decode base64 binary content
            try:
                binary_data = base64.b64decode(chunk.payload.binary_b64)
                delta["content"] = binary_data.decode("utf-8")
            except (UnicodeDecodeError, ValueError):
                try:
                    delta["content"] = binary_data.decode("latin-1")
                except Exception:
                    delta["content"] = str(binary_data)
        else:
            delta["content"] = ""

        # Build response data
        response_data: dict[str, Any] = {"choices": [{"delta": delta}]}

        # Add finish_reason from typed contract
        if chunk.metadata.finish_reason:
            response_data["choices"][0]["finish_reason"] = chunk.metadata.finish_reason  # type: ignore[index]

        # Add metadata fields (use original for non-typed fields like id, model, created)
        metadata_dict = content.metadata
        for key in ["id", "model", "created"]:
            if key in metadata_dict:
                response_data[key] = metadata_dict[key]

        # Add usage from typed contract or original
        if chunk.metadata.usage:
            response_data["usage"] = chunk.metadata.usage.model_dump(exclude_none=True)
        elif content.usage:
            to_dict = getattr(content.usage, "to_legacy_dict", None)
            response_data["usage"] = to_dict() if callable(to_dict) else content.usage

        result = f"data: {json.dumps(response_data)}\n\n"
        if chunk.is_done:
            result += "data: [DONE]\n\n"
        return result.encode()


__all__ = ["SSESerializer"]
