from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import src.core.services.metrics_service as metrics
from src.core.common.exceptions import JSONParsingError
from src.core.domain.streaming_response_processor import (
    IStreamProcessor,
    StreamingContent,
)
from src.core.services.json_repair_service import JsonRepairService
from src.core.services.streaming.stream_utils import get_stream_id

logger = logging.getLogger(__name__)


@dataclass
class _StreamState:
    buffer: str = ""
    brace_level: int = 0
    in_string: bool = False
    json_started: bool = False


class JsonRepairProcessor(IStreamProcessor):
    """Stream processor that detects, buffers, and repairs JSON blocks in text streams."""

    def __init__(
        self,
        repair_service: JsonRepairService,
        buffer_cap_bytes: int,
        strict_mode: bool,
        schema: dict[str, Any] | None = None,
        enabled: bool = True,
    ) -> None:
        self._service = repair_service
        self._buffer_cap_bytes = int(buffer_cap_bytes)
        self._strict_mode = bool(strict_mode)
        self._schema = schema
        self._enabled = bool(enabled)
        self._states: dict[str, _StreamState] = {}

    def _get_state(self, stream_id: str) -> _StreamState:
        state = self._states.get(stream_id)
        if state is None:
            state = _StreamState()
            self._states[stream_id] = state
        return state

    def _reset_state(self, state: _StreamState) -> None:
        state.buffer = ""
        state.brace_level = 0
        state.in_string = False
        state.json_started = False

    async def process(self, content: StreamingContent) -> StreamingContent:
        stream_id = get_stream_id(content)

        if not self._enabled:
            # Feature disabled: pass through unchanged and clear any leftover state
            self._states.pop(stream_id, None)
            return content

        # Empty and not done: nothing to do
        if content.is_empty and not content.is_done:
            return content

        state = self._get_state(stream_id)

        out_parts: list[str] = []
        text = content.content or ""
        i = 0
        n = len(text)

        while i < n:
            if not state.json_started:
                i, new_out_parts = self._handle_non_json_text(text, i, n, state)
                out_parts.extend(new_out_parts)
            else:
                i = self._process_json_character(text, i, state)
                if self._is_json_complete(state):
                    repaired_json, success = self._handle_json_completion(state)
                    if success:
                        out_parts.append(json.dumps(repaired_json))
                    else:
                        out_parts.append(state.buffer)
                    self._reset_state(state)

            self._log_buffer_capacity_warning(state)

        if content.is_done:
            final_output = self._flush_final_buffer(state)
            if final_output:
                out_parts.append(final_output)
            self._states.pop(stream_id, None)

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

    def _handle_non_json_text(
        self, text: str, i: int, n: int, state: _StreamState
    ) -> tuple[int, list[str]]:
        out_parts: list[str] = []
        brace_pos_obj = text.find("{", i)
        brace_pos_arr = text.find("[", i)
        candidates = [p for p in [brace_pos_obj, brace_pos_arr] if p != -1]

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

    def _process_json_character(self, text: str, i: int, state: _StreamState) -> int:
        ch = text[i]
        if ch == '"':
            if not self._is_current_quote_escaped(state):
                state.in_string = not state.in_string
        elif not state.in_string:
            if ch == "{" or ch == "[":
                state.brace_level += 1
            elif ch == "}" or ch == "]":
                state.brace_level -= 1
        state.buffer += ch
        return i + 1

    def _is_current_quote_escaped(self, state: _StreamState) -> bool:
        backslash_count = 0
        for existing_char in reversed(state.buffer):
            if existing_char == "\\":
                backslash_count += 1
            else:
                break
        return backslash_count % 2 == 1

    def _is_json_complete(self, state: _StreamState) -> bool:
        return state.json_started and state.brace_level == 0 and not state.in_string

    def _handle_json_completion(self, state: _StreamState) -> tuple[Any, bool]:
        repaired = None
        success = False
        try:
            repaired = self._service.repair_and_validate_json(
                state.buffer,
                schema=self._schema,
                strict=self._strict_mode,
            )
            if repaired is not None:
                success = True
        except Exception as e:  # pragma: no cover - strict mode rethrow
            if self._strict_mode:
                raise JSONParsingError(
                    message=f"JSON repair failed in strict mode: {e}",
                    details={"original_buffer": state.buffer},
                ) from e
            logger.warning("JSON repair raised error: %s", e)

        if repaired is not None:
            metrics.inc(
                "json_repair.streaming.strict_success"
                if self._strict_mode
                else "json_repair.streaming.best_effort_success"
            )
        else:
            metrics.inc(
                "json_repair.streaming.strict_fail"
                if self._strict_mode
                else "json_repair.streaming.best_effort_fail"
            )
            logger.warning(
                "JSON block detected but failed to repair. Flushing raw buffer."
            )
        return repaired, success

    def _log_buffer_capacity_warning(self, state: _StreamState) -> None:
        if state.json_started and len(state.buffer) > self._buffer_cap_bytes:
            logger.warning(
                "Buffer capacity exceeded during JSON repair. Continuing to buffer until completion."
            )

    def _flush_final_buffer(self, state: _StreamState) -> str | None:
        if state.json_started and state.buffer:
            buf = state.buffer
            if not state.in_string and buf.rstrip().endswith(":"):
                buf = buf + " null"
            try:
                repaired = self._service.repair_and_validate_json(
                    buf,
                    schema=self._schema,
                    strict=self._strict_mode,
                )
                if repaired is not None:
                    return json.dumps(repaired)
            except Exception as e:  # pragma: no cover - strict mode rethrow
                if self._strict_mode:
                    raise JSONParsingError(
                        message=f"JSON repair failed in strict mode: {e}",
                        details={"original_buffer": state.buffer},
                    ) from e
                logger.warning(
                    "JSON repair raised error during final flush: %s", e
                )
            return buf
        return None
