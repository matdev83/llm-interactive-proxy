from __future__ import annotations

import json
import logging
import re
from typing import Any

import src.core.services.metrics_service as metrics
from src.core.common.exceptions import JSONParsingError, ValidationError
from src.core.domain.streaming_response_processor import (
    IStreamProcessor,
    StreamingContent,
)
from src.core.services.json_repair_service import JsonRepairResult, JsonRepairService
from src.core.services.streaming.stream_context_registry import (
    JsonRepairBufferState,
    StreamingContextRegistry,
)
from src.core.services.streaming.stream_utils import get_stream_id

logger = logging.getLogger(__name__)


class JsonRepairProcessor(IStreamProcessor):
    """Stream processor that repairs JSON blocks while isolating per-stream state."""

    _TOOL_TAG_MARKERS: tuple[str, ...] = (
        "<apply_diff",
        "<patch_file",
        "<read_file",
        "<write_to_file",
        "<insert_content",
        "<delete_file",
        "<execute_command",
        "<update_todo_list",
        "<attempt_completion",
        "<ask_followup_question",
        "<use_mcp_tool",
        "<access_mcp_resource",
        "<search_files",
        "<list_files",
        "<list_code_definition_names",
        "<codebase_search",
        "<browser_action",
    )
    _CHECKBOX_PATTERN = re.compile(r"\[\s*[-xX]\s*\]")

    def __init__(
        self,
        repair_service: JsonRepairService,
        buffer_cap_bytes: int,
        strict_mode: bool,
        schema: dict[str, Any] | None = None,
        enabled: bool = True,
        registry: StreamingContextRegistry | None = None,
    ) -> None:
        self._service = repair_service
        self._buffer_cap_bytes = int(buffer_cap_bytes)
        self._strict_mode = bool(strict_mode)
        self._schema = schema
        self._enabled = bool(enabled)
        self._registry = registry or StreamingContextRegistry()

    def reset(self) -> None:
        """Clear any buffered state across streams (called per new streaming session)."""
        self._registry.reset()

    async def process(self, content: StreamingContent) -> StreamingContent:
        if not self._enabled:
            return content

        if content.is_empty and not content.is_done:
            return content

        # Skip JSON repair for structured OpenAI-format chunks.
        # JSON repair is meant for text content that may contain broken JSON.
        # Structured chunks (dicts with "choices" or StopChunkWithUsage) should
        # pass through unchanged to preserve their format.
        from src.core.ports.streaming_contracts import StopChunkWithUsage

        if isinstance(content.content, StopChunkWithUsage):
            # StopChunkWithUsage is a special dict that must be preserved as-is
            return content
        # OpenAI-format chunks (with "choices") should pass through unchanged
        if isinstance(content.content, dict) and (
            "choices" in content.content or "usage" in content.content
        ):
            return content

        stream_id = get_stream_id(content)
        state = self._registry.get_json_repair_buffer(stream_id)

        out_parts: list[str] = []
        text = self._normalize_chunk_text(content.content)

        if self._should_bypass_json_repair(text, stream_id):
            return StreamingContent(
                content=text,
                is_done=content.is_done,
                is_cancellation=content.is_cancellation,
                metadata=content.metadata,
                usage=content.usage,
                raw_data=content.raw_data,
            )
        i = 0
        n = len(text)

        while i < n:
            if not state.json_started:
                i, new_parts = self._handle_non_json_text(state, text, i, n)
                out_parts.extend(new_parts)
            else:
                i = self._process_json_character(state, text, i)
                if self._is_json_complete(state):
                    repair_result = self._handle_json_completion(state)
                    if repair_result.success:
                        out_parts.append(json.dumps(repair_result.content))
                    else:
                        out_parts.append(state.buffer)
                    self._reset_state(state)

            self._log_buffer_capacity_warning(state)

        if content.is_done:
            final_output = self._flush_final_buffer(state)
            if final_output:
                out_parts.append(final_output)
            self._registry.clear_json_repair_buffer(stream_id)
        elif content.is_cancellation:
            self._registry.clear_json_repair_buffer(stream_id)

        new_text = "".join(out_parts)
        if new_text or content.is_done:
            return StreamingContent(
                content=new_text,
                is_done=content.is_done,
                is_cancellation=content.is_cancellation,
                metadata=content.metadata,
                usage=content.usage,
                raw_data=content.raw_data,
            )

        return StreamingContent(
            content="",
            is_done=content.is_done,
            is_cancellation=content.is_cancellation,
            metadata=content.metadata,
            usage=content.usage,
            raw_data=content.raw_data,
        )

    # ---------------------------------------------------------------------
    # Internal helpers
    # ---------------------------------------------------------------------

    def _should_bypass_json_repair(self, text: str, stream_id: str) -> bool:
        """Skip JSON repair for XML/tool-call payloads and checklists."""

        if "<![CDATA[" in text or any(tag in text for tag in self._TOOL_TAG_MARKERS):
            self._registry.clear_json_repair_buffer(stream_id)
            return True

        if self._CHECKBOX_PATTERN.search(text):
            self._registry.clear_json_repair_buffer(stream_id)
            return True

        return False

    def _handle_non_json_text(
        self, state: JsonRepairBufferState, text: str, i: int, n: int
    ) -> tuple[int, list[str]]:
        out_parts: list[str] = []
        brace_pos_obj = text.find("{", i)
        brace_pos_arr = text.find("[", i)
        candidates = [p for p in (brace_pos_obj, brace_pos_arr) if p != -1]

        if not candidates:
            if i < n:
                out_parts.append(text[i:])
            return n, out_parts

        start_pos = min(candidates)
        if start_pos > i:
            out_parts.append(text[i:start_pos])

        ch = text[start_pos]
        state.json_started = True
        state.buffer = ch
        state.brace_level = 1
        state.in_string = False
        return start_pos + 1, out_parts

    def _process_json_character(
        self, state: JsonRepairBufferState, text: str, i: int
    ) -> int:
        ch = text[i]
        if ch == '"':
            if not self._is_current_quote_escaped(state):
                state.in_string = not state.in_string
        elif not state.in_string:
            if ch == "{" or ch == "[":
                state.brace_level += 1
            elif ch == "}" or ch == "]":
                state.brace_level -= 1
        state.buffer_parts.append(ch)
        state.buffer_length += len(ch)
        return i + 1

    def _is_current_quote_escaped(self, state: JsonRepairBufferState) -> bool:
        backslash_count = 0
        # Iterate backwards through buffer parts
        for part in reversed(state.buffer_parts):
            for existing_char in reversed(part):
                if existing_char == "\\":
                    backslash_count += 1
                else:
                    return backslash_count % 2 == 1
            # If we processed the whole part and it was all backslashes, continue to previous part
        return backslash_count % 2 == 1

    def _is_json_complete(self, state: JsonRepairBufferState) -> bool:
        return state.json_started and state.brace_level == 0 and not state.in_string

    def _handle_json_completion(self, state: JsonRepairBufferState) -> JsonRepairResult:
        full_buffer = state.buffer
        try:
            result = self._service.repair_and_validate_json(
                full_buffer,
                schema=self._schema,
                strict=self._strict_mode,
            )
        except Exception as e:  # pragma: no cover - strict mode rethrow
            if self._strict_mode:
                if isinstance(e, JSONParsingError | ValidationError):
                    raise
                raise JSONParsingError(
                    message=f"JSON repair failed in strict mode: {e}",
                    details={"original_buffer": full_buffer},
                ) from e
            if logger.isEnabledFor(logging.WARNING):
                logger.warning("JSON repair raised error: %s", e)
            return JsonRepairResult(success=False, content=None)

        if result.success:
            self._increment_success_metrics()
        else:
            self._increment_failure_metrics()
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "JSON block detected but failed to repair. Flushing raw buffer."
                )
        return result

    def _flush_final_buffer(self, state: JsonRepairBufferState) -> str | None:
        if not state.json_started or not state.buffer_parts:
            return None

        buf = state.buffer
        if not state.in_string and buf.rstrip().endswith(":"):
            buf = buf + " null"
            # Update state to match buf modification (though we are resetting anyway)
            state.buffer = buf

        repair_result = self._service.repair_and_validate_json(
            buf, schema=self._schema, strict=self._strict_mode
        )
        if repair_result.success:
            self._increment_success_metrics()
            result = json.dumps(repair_result.content)
        else:
            self._increment_failure_metrics()
            result = buf

        self._reset_state(state)
        return result

    def _reset_state(self, state: JsonRepairBufferState) -> None:
        state.buffer_parts.clear()
        state.buffer_length = 0
        state.brace_level = 0
        state.in_string = False
        state.json_started = False

    def _log_buffer_capacity_warning(self, state: JsonRepairBufferState) -> None:
        if (
            state.json_started
            and state.buffer_length > self._buffer_cap_bytes
            and logger.isEnabledFor(logging.WARNING)
        ):
            logger.warning(
                "Buffer capacity exceeded during JSON repair. "
                "Continuing to buffer until completion."
            )

    def _increment_success_metrics(self) -> None:
        metrics.inc(
            "json_repair.streaming.strict_success"
            if self._strict_mode
            else "json_repair.streaming.best_effort_success"
        )

    def _increment_failure_metrics(self) -> None:
        metrics.inc(
            "json_repair.streaming.strict_fail"
            if self._strict_mode
            else "json_repair.streaming.best_effort_fail"
        )

    @staticmethod
    def _normalize_chunk_text(chunk: Any) -> str:
        """Normalize mixed streaming payloads into text."""
        from src.core.ports.streaming_contracts import StopChunkWithUsage

        if chunk is None:
            return ""
        if isinstance(chunk, str):
            return chunk
        if isinstance(chunk, bytes | bytearray):
            return chunk.decode("utf-8", errors="ignore")
        if isinstance(chunk, dict):
            # Handle StopChunkWithUsage specially - it's a dict subclass that
            # raises errors on direct serialization to prevent usage data leaks.
            # Convert to plain dict first before JSON serialization.
            if isinstance(chunk, StopChunkWithUsage):
                return json.dumps(dict(chunk))
            try:
                return json.dumps(chunk)
            except (TypeError, ValueError):
                # For other dict types that fail, convert to plain dict first
                return json.dumps(dict(chunk))
        return str(chunk)
