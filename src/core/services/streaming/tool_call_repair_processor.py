"""Streaming tool-call argument repair processor.

DESIGN DECISION: Virtual tool-call detection (XML parsed from plain text content)
is intentionally disabled. The proxy remains transparent for textual content and
client-specific tags.

However, some providers emit malformed JSON in *native* OpenAI `tool_calls`
argument streams (usually missing trailing braces). This processor performs a
minimal repair at stream finalization by appending only the missing suffix so
that client-side incremental concatenation still produces valid JSON.
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any

from json_repair import repair_json

from src.core.domain.streaming_response_processor import (
    IStreamProcessor,
    StreamingContent,
)
from src.core.interfaces.tool_call_repair_service_interface import (
    IToolCallRepairService,
)
from src.core.services.streaming.stream_context_registry import (
    StreamingContextRegistry,
)
from src.core.services.streaming.stream_utils import get_stream_id

logger = logging.getLogger(__name__)


_ARGUMENTS_NAMESPACE_PREFIX = "tool-call-repair:args:"


class ToolCallRepairProcessor(IStreamProcessor):
    """
    Stream processor that keeps text transparent and repairs native tool-call JSON.

    Behavior:
    - Never parses XML or textual pseudo-tool-calls from `content`
    - Buffers native `tool_calls[].function.arguments` fragments per stream
    - On terminal chunks, repairs malformed JSON by appending only a suffix
      when repair result extends the original argument string.
    """

    def __init__(
        self,
        tool_call_repair_service: IToolCallRepairService,
        *,
        max_buffer_bytes: int | None = None,
        registry: StreamingContextRegistry | None = None,
    ) -> None:
        self.tool_call_repair_service = tool_call_repair_service
        self._max_buffer_bytes = max_buffer_bytes or 64 * 1024
        self._registry = registry or StreamingContextRegistry()
        self._argument_keys_by_stream: dict[str, set[str]] = {}
        self._state_lock = threading.Lock()

    async def process(self, content: StreamingContent) -> StreamingContent:
        """Process native tool-call argument fragments and repair at stream end."""
        stream_id = get_stream_id(content)
        metadata = content.metadata

        tool_calls_raw = metadata.get("tool_calls")
        tool_calls = tool_calls_raw if isinstance(tool_calls_raw, list) else []

        if tool_calls:
            self._buffer_tool_call_arguments(stream_id, tool_calls)

        finish_reason = metadata.get("finish_reason")
        should_finalize = bool(
            content.is_done or content.is_cancellation or finish_reason == "tool_calls"
        )

        if not should_finalize:
            return content

        if content.is_cancellation:
            self._consume_buffered_arguments(stream_id)
            return content

        repair_suffixes = self._compute_argument_suffix_repairs(stream_id)
        if not repair_suffixes:
            return content

        repaired_tool_calls = self._apply_repair_suffixes(tool_calls, repair_suffixes)
        metadata["tool_calls"] = repaired_tool_calls

        if content.is_done and repaired_tool_calls:
            content.content = self._build_terminal_openai_payload(
                metadata,
                repaired_tool_calls,
            )

        return content

    def reset(self) -> None:
        """Reset local processor state.

        Do not reset the shared StreamingContextRegistry here. The registry may be
        shared across concurrently running streams.
        """
        with self._state_lock:
            self._argument_keys_by_stream.clear()

    def _buffer_tool_call_arguments(
        self, stream_id: str, tool_calls: list[Any]
    ) -> None:
        for position, tool_call in enumerate(tool_calls):
            if not isinstance(tool_call, dict):
                continue

            call_key = self._tool_call_key(tool_call, position)
            fragment = self._extract_arguments_fragment(tool_call)
            if fragment is None:
                continue

            namespace = self._arguments_namespace(call_key)
            existing_fragment = self._registry.get_fragment(stream_id, namespace)
            combined_fragment = f"{existing_fragment}{fragment}"
            if len(combined_fragment.encode("utf-8")) > self._max_buffer_bytes:
                logger.warning(
                    "Tool-call argument buffer exceeded cap; skipping repair for key %s",
                    call_key,
                )
                self._registry.clear_fragment(stream_id, namespace)
                self._untrack_argument_key(stream_id, call_key)
                continue

            self._registry.set_fragment(stream_id, namespace, combined_fragment)
            self._track_argument_key(stream_id, call_key)

    def _compute_argument_suffix_repairs(self, stream_id: str) -> dict[str, str]:
        buffered_arguments = self._consume_buffered_arguments(stream_id)
        suffixes: dict[str, str] = {}

        for call_key, raw_arguments in buffered_arguments.items():
            if not raw_arguments or self._is_valid_json(raw_arguments):
                continue

            repaired_arguments = self._repair_arguments(raw_arguments)
            if repaired_arguments is None:
                continue

            if not repaired_arguments.startswith(raw_arguments):
                continue

            suffix = repaired_arguments[len(raw_arguments) :]
            if suffix:
                suffixes[call_key] = suffix

        return suffixes

    def _consume_buffered_arguments(self, stream_id: str) -> dict[str, str]:
        with self._state_lock:
            tracked_keys = self._argument_keys_by_stream.pop(stream_id, set())

        consumed: dict[str, str] = {}
        for call_key in tracked_keys:
            namespace = self._arguments_namespace(call_key)
            value = self._registry.get_fragment(stream_id, namespace)
            self._registry.clear_fragment(stream_id, namespace)
            if value:
                consumed[call_key] = value
        return consumed

    def _track_argument_key(self, stream_id: str, call_key: str) -> None:
        with self._state_lock:
            key_set = self._argument_keys_by_stream.setdefault(stream_id, set())
            key_set.add(call_key)

    def _untrack_argument_key(self, stream_id: str, call_key: str) -> None:
        with self._state_lock:
            key_set = self._argument_keys_by_stream.get(stream_id)
            if not key_set:
                return
            key_set.discard(call_key)
            if not key_set:
                self._argument_keys_by_stream.pop(stream_id, None)

    @staticmethod
    def _arguments_namespace(call_key: str) -> str:
        return f"{_ARGUMENTS_NAMESPACE_PREFIX}{call_key}"

    @staticmethod
    def _extract_arguments_fragment(tool_call: dict[str, Any]) -> str | None:
        function_block = tool_call.get("function")
        if not isinstance(function_block, dict):
            return None
        arguments = function_block.get("arguments")
        if isinstance(arguments, str):
            return arguments
        if arguments is None:
            return ""
        if isinstance(arguments, dict | list):
            return json.dumps(arguments)
        return str(arguments)

    @staticmethod
    def _tool_call_key(tool_call: dict[str, Any], position: int) -> str:
        index = tool_call.get("index")
        if isinstance(index, int):
            return f"index:{index}"

        call_id = tool_call.get("id")
        if isinstance(call_id, str) and call_id:
            return f"id:{call_id}"

        function_block = tool_call.get("function")
        if isinstance(function_block, dict):
            name = function_block.get("name")
            if isinstance(name, str) and name:
                return f"name:{name}:{position}"

        return f"position:{position}"

    @staticmethod
    def _is_valid_json(arguments: str) -> bool:
        try:
            json.loads(arguments)
            return True
        except (json.JSONDecodeError, TypeError):
            return False

    def _repair_arguments(self, raw_arguments: str) -> str | None:
        if len(raw_arguments.encode("utf-8")) > self._max_buffer_bytes:
            return None

        try:
            repaired = repair_json(raw_arguments)
        except Exception:
            return None

        if not repaired:
            return None

        try:
            json.loads(repaired)
        except json.JSONDecodeError:
            return None
        return repaired

    def _apply_repair_suffixes(
        self, tool_calls: list[Any], suffixes: dict[str, str]
    ) -> list[dict[str, Any]]:
        repaired_tool_calls: list[dict[str, Any]] = []
        remaining = dict(suffixes)

        for position, raw_tool_call in enumerate(tool_calls):
            if not isinstance(raw_tool_call, dict):
                continue

            repaired_call: dict[str, Any] = dict(raw_tool_call)
            call_key = self._tool_call_key(repaired_call, position)
            suffix = remaining.pop(call_key, None)

            if suffix:
                function_block = repaired_call.get("function")
                function_dict = (
                    dict(function_block) if isinstance(function_block, dict) else {}
                )
                existing_arguments = function_dict.get("arguments")
                if not isinstance(existing_arguments, str):
                    existing_arguments = ""
                function_dict["arguments"] = f"{existing_arguments}{suffix}"
                repaired_call["function"] = function_dict

            repaired_tool_calls.append(repaired_call)

        for call_key, suffix in remaining.items():
            synthetic_call = self._build_synthetic_suffix_call(call_key, suffix)
            if synthetic_call is not None:
                repaired_tool_calls.append(synthetic_call)

        return repaired_tool_calls

    @staticmethod
    def _build_synthetic_suffix_call(
        call_key: str, suffix: str
    ) -> dict[str, Any] | None:
        if not suffix:
            return None

        synthetic_call: dict[str, Any] = {
            "type": "function",
            "function": {"arguments": suffix},
        }

        if call_key.startswith("index:"):
            raw_index = call_key.removeprefix("index:")
            try:
                synthetic_call["index"] = int(raw_index)
            except ValueError:
                return None
        elif call_key.startswith("id:"):
            call_id = call_key.removeprefix("id:")
            if call_id:
                synthetic_call["id"] = call_id
        elif call_key.startswith("name:"):
            _, _, remainder = call_key.partition("name:")
            name, _, _ = remainder.partition(":")
            if name:
                synthetic_call["function"]["name"] = name

        return synthetic_call

    @staticmethod
    def _build_terminal_openai_payload(
        metadata: dict[str, Any],
        tool_calls: list[dict[str, Any]],
    ) -> dict[str, Any]:
        finish_reason = metadata.get("finish_reason")
        if not isinstance(finish_reason, str) or not finish_reason:
            finish_reason = "tool_calls"

        chunk_index = metadata.get("index")
        if not isinstance(chunk_index, int):
            chunk_index = 0

        payload: dict[str, Any] = {
            "object": "chat.completion.chunk",
            "choices": [
                {
                    "index": chunk_index,
                    "delta": {"tool_calls": tool_calls},
                    "finish_reason": finish_reason,
                }
            ],
        }

        chunk_id = metadata.get("id")
        if isinstance(chunk_id, str) and chunk_id:
            payload["id"] = chunk_id

        model = metadata.get("model")
        if isinstance(model, str) and model:
            payload["model"] = model

        created = metadata.get("created")
        if isinstance(created, int):
            payload["created"] = created

        return payload


# Keep type alias for backward compatibility
ServiceToolCallRepairProcessor = ToolCallRepairProcessor
