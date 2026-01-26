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

from src.core.domain.streaming.contracts import StreamingChunk
from src.core.domain.streaming.sentinels import SentinelManager
from src.core.domain.streaming.stop_chunk_with_usage import (
    StopChunkWithUsage,
    UsageChunkLeakError,
)
from src.core.domain.streaming.streaming_content import StreamingContent

logger = logging.getLogger(__name__)


class SSESerializer:
    """Serializer for converting StreamingContent to SSE bytes."""

    def _serialize_stop_chunk_with_usage(self, content: StreamingContent) -> bytes:
        """Serialize StopChunkWithUsage to SSE bytes with usage at top level."""
        assert isinstance(content.content, StopChunkWithUsage)
        # Type hint for content.content as StopChunkWithUsage is already asserted
        plain_dict = dict(content.content)
        return f"data: {json.dumps(plain_dict)}\n\ndata: [DONE]\n\n".encode()

    def _serialize_error_chunk(
        self, chunk: StreamingChunk, content: StreamingContent
    ) -> bytes | None:
        """Serialize error chunk to SSE bytes. Returns None if not an error chunk."""
        if chunk.metadata.finish_reason == "error" and (
            chunk.metadata.error is not None or "error" in content.metadata
        ):
            error_dict: dict[str, Any] = (
                chunk.metadata.error.model_dump(exclude_none=True)
                if chunk.metadata.error is not None
                else content.metadata.get("error", {})
            )
            if not isinstance(error_dict, dict):
                error_dict = {}
            error_data: dict[str, Any] = {
                "choices": [{"delta": {}, "finish_reason": "error"}],
                "error": error_dict,
            }
            for key in ("id", "model", "created"):
                if key in content.metadata:
                    error_data[key] = content.metadata[key]
            return f"data: {json.dumps(error_data)}\n\ndata: [DONE]\n\n".encode()

        # Check for error in content if it's a dict
        if isinstance(content.content, dict) and content.content.get("error"):
            return f"data: {json.dumps(content.content)}\n\ndata: [DONE]\n\n".encode()
        return None

    def _serialize_cancellation_chunk(
        self, chunk: StreamingChunk, content: StreamingContent
    ) -> bytes | None:
        """Serialize cancellation chunk to SSE bytes. Returns None if not cancellation."""
        if chunk.is_cancellation and chunk.payload.kind != "empty":
            data: dict[str, Any] = {
                "choices": [{"delta": {"content": str(content.content)}}],
                "finish_reason": "cancelled",
            }
            for key in ("id", "model", "created"):
                if key in content.metadata:
                    data[key] = content.metadata[key]
            return f"data: {json.dumps(data)}\n\ndata: [DONE]\n\n".encode()
        return None

    def _serialize_done_chunk(
        self, chunk: StreamingChunk, content: StreamingContent
    ) -> bytes:
        """Serialize done chunk to SSE bytes (may include content or just [DONE])."""
        if content._is_empty_completion_payload():  # type: ignore[attr-defined]
            return b"data: [DONE]\n\n"

        content_is_done_marker = (
            content.content == "[DONE]"
            or content.content == SentinelManager.DONE_MARKER
            or content.content == b"[DONE]"
        )
        if content.content and content.content != "" and not content_is_done_marker:
            if isinstance(content.content, dict) and "choices" in content.content:
                return self._serialize_openai_chunk_with_done(chunk, content)
            else:
                # For non-empty content that's not a dict with choices, serialize normally
                # but ensure [DONE] is added since chunk.is_done is True
                return self._serialize_normal_chunk(chunk, content)
        else:
            return b"data: [DONE]\n\n"

    def serialize(self, content: StreamingContent) -> bytes:
        """Serialize StreamingContent to SSE bytes.

        Args:
            content: The StreamingContent instance to serialize

        Returns:
            Bytes representation suitable for SSE streaming

        Raises:
            UsageChunkLeakError: If StopChunkWithUsage is incorrectly handled
        """
        if isinstance(content.content, StopChunkWithUsage):
            return self._serialize_stop_chunk_with_usage(content)
        chunk = content.to_typed_chunk()
        if chunk.is_done:
            error_bytes = self._serialize_error_chunk(chunk, content)
            if error_bytes is not None:
                return error_bytes
            cancellation_bytes = self._serialize_cancellation_chunk(chunk, content)
            if cancellation_bytes is not None:
                return cancellation_bytes
            return self._serialize_done_chunk(chunk, content)
        return self._serialize_normal_chunk(chunk, content)

    def _normalize_openai_chat_completion_to_stream_chunk(
        self, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Normalize `choices[].message` payloads into `choices[].delta` for SSE."""
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            return payload

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
                new_choice: dict[str, Any] = {
                    k: v for k, v in choice.items() if k != "message"
                }
                delta: dict[str, Any] = dict(message)
                if delta.get("content") is None:
                    delta["content"] = ""
                new_choice["delta"] = delta
                normalized_choices.append(new_choice)
                converted_any = True
            else:
                new_choice = dict(choice)
                new_choice.setdefault("delta", {})
                normalized_choices.append(new_choice)
                converted_any = True

        if not converted_any and payload.get("object") != "chat.completion":
            return payload

        normalized = dict(payload)
        normalized["choices"] = normalized_choices
        if payload.get("object") == "chat.completion":
            normalized["object"] = "chat.completion.chunk"
        return normalized

    def _serialize_openai_chunk_with_done(
        self, chunk: StreamingChunk, content: StreamingContent
    ) -> bytes:
        """Serialize an OpenAI-formatted chunk with done marker."""
        is_virtual = content.metadata.get("_virtual_tool_calls", False)
        content_copy = dict(
            self._normalize_openai_chat_completion_to_stream_chunk(
                cast(dict[str, Any], content.content)
            )
        )

        # Sanitize existing tool_calls in delta/message
        existing_choices = content_copy.get("choices", [])
        if isinstance(existing_choices, list) and existing_choices:
            new_choices = []
            choices_modified = False
            for choice_item in existing_choices:
                if not isinstance(choice_item, dict):
                    new_choices.append(choice_item)
                    continue
                new_choice: dict[str, Any] = dict(choice_item)
                choice_modified = False
                for container_key in ("delta", "message"):
                    container = new_choice.get(container_key)
                    if isinstance(container, dict):
                        tc_list = container.get("tool_calls")
                        if is_virtual:
                            if "tool_calls" in container:
                                new_container: dict[str, Any] = dict(container)
                                del new_container["tool_calls"]
                                new_choice[container_key] = new_container
                                choice_modified = True
                        elif isinstance(tc_list, list) and tc_list:
                            sanitized_calls: list[dict[str, Any]] = []
                            for idx, tc in enumerate(tc_list):
                                if not isinstance(tc, dict):
                                    continue
                                sanitized_tc = {
                                    k: v
                                    for k, v in tc.items()
                                    if isinstance(k, str)
                                    and not k.startswith("_")
                                    and k != "extra_content"
                                }
                                # Ensure index is present (required by OpenAI streaming spec)
                                if "index" not in sanitized_tc:
                                    sanitized_tc["index"] = idx
                                sanitized_calls.append(sanitized_tc)
                            new_container = dict(container)
                            new_container["tool_calls"] = sanitized_calls
                            new_choice[container_key] = new_container
                            choice_modified = True
                if choice_modified:
                    choices_modified = True
                new_choices.append(new_choice)
            if choices_modified:
                content_copy["choices"] = new_choices

        # If is_virtual was handled above, content_copy is ready
        if is_virtual:
            return f"data: {json.dumps(content_copy)}\n\ndata: [DONE]\n\n".encode()

        # Non-virtual: Inject tool_calls from typed metadata into the delta if present
        tool_calls = chunk.metadata.tool_calls
        if tool_calls:
            sanitized_calls = []
            for idx, tc in enumerate(tool_calls):
                if hasattr(tc, "model_dump"):
                    tc_dict = tc.model_dump(exclude_none=True)
                elif isinstance(tc, dict):
                    tc_dict = tc
                else:
                    continue
                sanitized_dict: dict[str, Any] = {
                    k: v
                    for k, v in tc_dict.items()
                    if isinstance(k, str)
                    and not k.startswith("_")
                    and k != "extra_content"
                }
                # Ensure index is present (required by OpenAI streaming spec)
                if "index" not in sanitized_dict:
                    sanitized_dict["index"] = idx
                if sanitized_dict:
                    sanitized_calls.append(sanitized_dict)

            if sanitized_calls:
                delta = self._get_first_delta(content_copy)
                if delta:
                    delta["tool_calls"] = sanitized_calls
                    if content_copy.get("choices") and isinstance(
                        content_copy["choices"], list
                    ):
                        content_copy["choices"][0]["delta"] = delta
                return f"data: {json.dumps(content_copy)}\n\ndata: [DONE]\n\n".encode()
        return f"data: {json.dumps(content_copy)}\n\ndata: [DONE]\n\n".encode()

    def _sanitize_tool_calls(
        self, tool_calls: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Sanitize tool_calls by removing internal markers and ensuring index is present."""
        result = []
        for idx, tc in enumerate(tool_calls):
            if not isinstance(tc, dict):
                continue
            sanitized = {
                k: v
                for k, v in tc.items()
                if isinstance(k, str) and not k.startswith("_") and k != "extra_content"
            }
            # Ensure index is present (required by OpenAI streaming spec)
            if "index" not in sanitized:
                sanitized["index"] = idx
            result.append(sanitized)
        return result

    def _sanitize_chunk_tool_calls_in_place(self, content_copy: dict[str, Any]) -> None:
        """Sanitize tool_calls in choices[].delta/message in place."""
        choices = content_copy.get("choices", [])
        if not isinstance(choices, list):
            return
        for choice_item in choices:
            if not isinstance(choice_item, dict):
                continue
            for container_key in ("delta", "message"):
                container = choice_item.get(container_key)
                if isinstance(container, dict):
                    tc_list = container.get("tool_calls")
                    if isinstance(tc_list, list) and tc_list:
                        container["tool_calls"] = self._sanitize_tool_calls(tc_list)

    def _get_first_delta(self, content_copy: dict[str, Any]) -> dict[str, Any] | None:
        """Get first choice delta dict, or None."""
        choices = content_copy.get("choices", [])
        if choices and isinstance(choices, list) and isinstance(choices[0], dict):
            delta = choices[0].get("delta", {})
            if isinstance(delta, dict):
                return delta
        return None

    def _serialize_openai_formatted_dict(
        self,
        working_content: dict[str, Any],
        chunk: StreamingChunk,
        content: StreamingContent,
    ) -> bytes:
        """Serialize an OpenAI-formatted dict chunk."""
        is_virtual_tc = content.metadata.get("_virtual_tool_calls", False)
        content_copy = dict(
            self._normalize_openai_chat_completion_to_stream_chunk(working_content)
        )
        self._sanitize_chunk_tool_calls_in_place(content_copy)
        delta = self._get_first_delta(content_copy)
        if is_virtual_tc:
            if delta and "tool_calls" in delta:
                delta = {k: v for k, v in delta.items() if k != "tool_calls"}
                if content_copy.get("choices") and isinstance(
                    content_copy["choices"], list
                ):
                    content_copy["choices"][0]["delta"] = delta
        else:
            tool_calls_to_inject = chunk.metadata.tool_calls
            if tool_calls_to_inject and delta:
                tool_calls_dicts: list[dict[str, Any]] = []
                for tc in tool_calls_to_inject:
                    if hasattr(tc, "model_dump"):
                        tool_calls_dicts.append(tc.model_dump(exclude_none=True))
                    elif isinstance(tc, dict):
                        tool_calls_dicts.append(tc)
                if tool_calls_dicts:
                    delta["tool_calls"] = self._sanitize_tool_calls(tool_calls_dicts)
                    if content_copy.get("choices") and isinstance(
                        content_copy["choices"], list
                    ):
                        content_copy["choices"][0]["delta"] = delta

        # Inject reasoning content from metadata if present
        reasoning = chunk.metadata.reasoning_content
        if reasoning and delta is not None:
            # Ensure reasoning_content field
            if "reasoning_content" not in delta:
                delta["reasoning_content"] = reasoning
            # Ensure reasoning alias (compatibility)
            if "reasoning" not in delta:
                delta["reasoning"] = reasoning
            # Update the delta in the content copy
            if content_copy.get("choices") and isinstance(
                content_copy["choices"], list
            ):
                content_copy["choices"][0]["delta"] = delta

        parts = [f"data: {json.dumps(content_copy)}\n\n"]
        if chunk.is_done:
            parts.append("data: [DONE]\n\n")
        return "".join(parts).encode()

    def _build_delta_metadata(
        self, chunk: StreamingChunk, content: StreamingContent, delta: dict[str, Any]
    ) -> None:
        """Build delta metadata (role, tool_call_id, tool_calls, reasoning)."""
        if chunk.metadata.role:
            delta["role"] = chunk.metadata.role
        tool_call_id = content.metadata.get("tool_call_id")
        if isinstance(tool_call_id, str) and tool_call_id:
            delta["tool_call_id"] = tool_call_id
        is_virtual = content.metadata.get("_virtual_tool_calls", False)
        tool_calls = chunk.metadata.tool_calls
        if tool_calls and not is_virtual:
            sanitized_calls = []
            for idx, tc in enumerate(tool_calls):
                if hasattr(tc, "model_dump"):
                    tc_dict = tc.model_dump(exclude_none=True)
                elif isinstance(tc, dict):
                    tc_dict = tc
                else:
                    continue
                sanitized_dict = {
                    k: v
                    for k, v in tc_dict.items()
                    if not k.startswith("_") and k != "extra_content"
                }
                # Ensure index is present (required by OpenAI streaming spec)
                if "index" not in sanitized_dict:
                    sanitized_dict["index"] = idx
                if sanitized_dict:
                    sanitized_calls.append(sanitized_dict)
            if sanitized_calls:
                delta["tool_calls"] = sanitized_calls
        reasoning_value = chunk.metadata.reasoning_content
        if reasoning_value and reasoning_value.strip():
            delta["reasoning_content"] = reasoning_value
            delta.setdefault("reasoning", reasoning_value)

    def _serialize_normal_chunk(
        self, chunk: StreamingChunk, content: StreamingContent
    ) -> bytes:
        """Serialize a normal (non-done) chunk."""
        # Fast path for simple text chunks
        if (
            chunk.payload.kind == "text"
            and chunk.payload.text is not None
            and not chunk.metadata.tool_calls
            and not chunk.metadata.reasoning_content
            and not chunk.metadata.finish_reason
            and not chunk.metadata.usage
            and not content.usage
            and not content.metadata.get("tool_call_id")
            and not content.metadata.get("_virtual_tool_calls")
        ):
            parts = ['{"choices": [{"delta": {']

            # Add role if present
            if chunk.metadata.role:
                parts.append('"role": ')
                parts.append(json.dumps(chunk.metadata.role))
                parts.append(", ")

            parts.append('"content": ')
            parts.append(json.dumps(chunk.payload.text))
            parts.append("}}]")
            # Add metadata fields
            for key in ("id", "model", "created"):
                val = content.metadata.get(key)
                if val is not None:
                    parts.append(f', "{key}": ')
                    parts.append(json.dumps(val))

            parts.append("}")
            sse_data = f"data: {''.join(parts)}\n\n"
            if chunk.is_done:
                sse_data += "data: [DONE]\n\n"
            return sse_data.encode()

        # Build delta object
        delta: dict[str, Any] = {}

        # Add metadata to delta
        self._build_delta_metadata(chunk, content, delta)

        # Add main content from typed payload
        if chunk.payload.kind == "text" and chunk.payload.text is not None:
            delta["content"] = chunk.payload.text
        elif (
            chunk.payload.kind == "opaque_json_dict" and chunk.payload.opaque_json_dict
        ):
            parsed_content = chunk.payload.opaque_json_dict
            if isinstance(parsed_content, dict):  # type: ignore[misc]
                # Check if OpenAI-formatted chunk
                if "choices" in parsed_content or "usage" in parsed_content:
                    return self._serialize_openai_formatted_dict(
                        parsed_content, chunk, content
                    )

                # Check for StopChunkWithUsage misuse
                if isinstance(content.content, StopChunkWithUsage):
                    raise UsageChunkLeakError(chunk_id=parsed_content.get("id"))

                delta["content"] = json.dumps(parsed_content)
            else:
                delta["content"] = json.dumps(parsed_content)
        elif chunk.payload.kind == "opaque_json" and chunk.payload.opaque_json:
            json_str = chunk.payload.opaque_json
            is_potential_openai = '"choices"' in json_str or '"usage"' in json_str
            is_leak_check_needed = isinstance(content.content, StopChunkWithUsage)

            if not is_potential_openai and not is_leak_check_needed:
                delta["content"] = json_str
            else:
                try:
                    parsed_content = json.loads(json_str)
                    if isinstance(parsed_content, dict):
                        if "choices" in parsed_content or "usage" in parsed_content:
                            return self._serialize_openai_formatted_dict(
                                parsed_content, chunk, content
                            )
                        if is_leak_check_needed:
                            raise UsageChunkLeakError(
                                chunk_id=parsed_content.get("id") if isinstance(parsed_content, dict) else None  # type: ignore[misc]
                            )
                        delta["content"] = json.dumps(parsed_content)
                    else:
                        delta["content"] = json.dumps(parsed_content)
                except json.JSONDecodeError:
                    delta["content"] = json_str

        elif chunk.payload.kind == "binary" and chunk.payload.binary_b64:
            # Decode base64 binary content
            binary_data: bytes | None = None
            try:
                binary_data = base64.b64decode(chunk.payload.binary_b64)
                delta["content"] = binary_data.decode("utf-8")
            except (UnicodeDecodeError, ValueError):
                if binary_data is not None:
                    try:
                        delta["content"] = binary_data.decode("latin-1")
                    except UnicodeDecodeError:
                        if logger.isEnabledFor(logging.DEBUG):
                            logger.debug(
                                "Failed to decode binary content, using string representation",
                                exc_info=True,
                            )
                        delta["content"] = str(binary_data)
                else:
                    delta["content"] = ""
        else:
            delta["content"] = ""

        # Build response data
        response_data: dict[str, Any] = {"choices": [{"delta": delta}]}

        if chunk.metadata.finish_reason:
            response_data["choices"][0]["finish_reason"] = chunk.metadata.finish_reason  # type: ignore[index]
        for key in ("id", "model", "created"):
            if key in content.metadata:
                response_data[key] = content.metadata[key]
        if chunk.metadata.usage:
            response_data["usage"] = chunk.metadata.usage.model_dump(exclude_none=True)
        elif content.usage:
            to_dict = getattr(content.usage, "to_legacy_dict", None)
            response_data["usage"] = to_dict() if callable(to_dict) else content.usage
        parts = [f"data: {json.dumps(response_data)}\n\n"]
        if chunk.is_done:
            parts.append("data: [DONE]\n\n")
        return "".join(parts).encode()


__all__ = ["SSESerializer"]
