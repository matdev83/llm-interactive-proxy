from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import src.core.services.metrics_service as metrics
from src.core.common.exceptions import JSONParsingError, ValidationError
from src.core.domain.streaming_response_processor import (
    IStreamProcessor,
    StreamingContent,
)
from src.core.services.json_repair_service import JsonRepairResult, JsonRepairService
from src.core.services.streaming.stream_utils import get_stream_id

logger = logging.getLogger(__name__)


@dataclass
class _JsonStreamState:
    buffer: str = ""
    brace_level: int = 0
    in_string: bool = False
    json_started: bool = False
    last_accessed: float = field(default_factory=time.time)


class JsonRepairProcessor(IStreamProcessor):
    """Stream processor that repairs JSON blocks while isolating per-stream state."""

    def __init__(
        self,
        repair_service: JsonRepairService,
        buffer_cap_bytes: int,
        strict_mode: bool,
        schema: dict[str, Any] | None = None,
        enabled: bool = True,
        state_ttl_seconds: int = 300,
    ) -> None:
        self._service = repair_service
        self._buffer_cap_bytes = int(buffer_cap_bytes)
        self._strict_mode = bool(strict_mode)
        self._schema = schema
        self._enabled = bool(enabled)
        self._states: dict[str, _JsonStreamState] = {}
        ttl = int(state_ttl_seconds)
        self._state_ttl_seconds = ttl if ttl > 0 else None

    def reset(self) -> None:
        """Clear any buffered state across streams (called per new streaming session)."""
        self._states.clear()

    async def process(self, content: StreamingContent) -> StreamingContent:
        if not self._enabled:
            return content

        self._cleanup_stale_states()

        if content.is_empty and not content.is_done:
            return content

        stream_id = get_stream_id(content)
        state = self._states.setdefault(stream_id, _JsonStreamState())
        state.last_accessed = time.time()

        out_parts: list[str] = []
        text = content.content or ""
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
            self._states.pop(stream_id, None)
        elif content.is_cancellation:
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

    def _cleanup_stale_states(self) -> None:
        if not self._states or self._state_ttl_seconds is None:
            return

        current_time = time.time()
        expired_streams = [
            stream_id
            for stream_id, state in list(self._states.items())
            if current_time - state.last_accessed > self._state_ttl_seconds
        ]

        if not expired_streams:
            return

        for stream_id in expired_streams:
            self._states.pop(stream_id, None)
            logger.debug(
                "Cleaned up stale JSON repair state for stream_id=%s after %s seconds",
                stream_id,
                self._state_ttl_seconds,
            )

    # ---------------------------------------------------------------------
    # Internal helpers
    # ---------------------------------------------------------------------

    def _handle_non_json_text(
        self, state: _JsonStreamState, text: str, i: int, n: int
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
        self, state: _JsonStreamState, text: str, i: int
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
        state.buffer += ch
        return i + 1

    def _is_current_quote_escaped(self, state: _JsonStreamState) -> bool:
        backslash_count = 0
        for existing_char in reversed(state.buffer):
            if existing_char == "\\":
                backslash_count += 1
            else:
                break
        return backslash_count % 2 == 1

    def _is_json_complete(self, state: _JsonStreamState) -> bool:
        return state.json_started and state.brace_level == 0 and not state.in_string

    def _handle_json_completion(self, state: _JsonStreamState) -> JsonRepairResult:
        try:
            result = self._service.repair_and_validate_json(
                state.buffer,
                schema=self._schema,
                strict=self._strict_mode,
            )
        except Exception as e:  # pragma: no cover - strict mode rethrow
            if self._strict_mode:
                if isinstance(e, JSONParsingError | ValidationError):
                    raise
                raise JSONParsingError(
                    message=f"JSON repair failed in strict mode: {e}",
                    details={"original_buffer": state.buffer},
                ) from e
            logger.warning("JSON repair raised error: %s", e)
            return JsonRepairResult(success=False, content=None)

        if result.success:
            self._increment_success_metrics()
        else:
            self._increment_failure_metrics()
            logger.warning(
                "JSON block detected but failed to repair. Flushing raw buffer."
            )
        return result

    def _flush_final_buffer(self, state: _JsonStreamState) -> str | None:
        if not state.json_started or not state.buffer:
            return None

        buf = state.buffer
        if not state.in_string and buf.rstrip().endswith(":"):
            buf = buf + " null"
            state.buffer = buf

        repair_result = self._service.repair_and_validate_json(
            buf, schema=self._schema, strict=self._strict_mode
        )
        if repair_result.success:
            self._increment_success_metrics()
            result = json.dumps(repair_result.content)
        else:
            self._increment_failure_metrics()
            result = state.buffer

        self._reset_state(state)
        return result

    def _reset_state(self, state: _JsonStreamState) -> None:
        state.buffer = ""
        state.brace_level = 0
        state.in_string = False
        state.json_started = False

    def _log_buffer_capacity_warning(self, state: _JsonStreamState) -> None:
        if state.json_started and len(state.buffer) > self._buffer_cap_bytes:
            logger.warning(
                "Buffer capacity exceeded during JSON repair. Continuing to buffer until completion."
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
