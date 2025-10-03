from __future__ import annotations

import json
import logging
from typing import Any

import src.core.services.metrics_service as metrics
from src.core.common.exceptions import JSONParsingError
from src.core.domain.streaming_response_processor import (
    IStreamProcessor,
    StreamingContent,
)
from src.core.services.json_repair_service import JsonRepairService

logger = logging.getLogger(__name__)


class JsonRepairProcessor(IStreamProcessor):
    """Stream processor that detects, buffers, and repairs JSON blocks in text streams.

    This processor is stateful. It attempts to pass through non-JSON text as-is (in
    chunk-sized batches) and only buffers when a potential JSON structure is detected.
    When a full JSON structure is closed, it attempts to repair and optionally validate
    against a provided schema.
    """

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

        self._reset_state()

    def _reset_state(self) -> None:
        self._buffer = ""
        self._brace_level = 0
        self._in_string = False
        self._json_started = False

    async def process(self, content: StreamingContent) -> StreamingContent:
        if not self._enabled:
            # Feature disabled: pass through unchanged
            return content

        # Empty and not done: nothing to do
        if content.is_empty and not content.is_done:
            return content

        out_parts: list[str] = []
        text = content.content or ""
        i = 0
        n = len(text)

        while i < n:
            if not self._json_started:
                i, new_out_parts = self._handle_non_json_text(text, i, n)
                out_parts.extend(new_out_parts)
            else:
                i = self._process_json_character(text, i)
                if self._is_json_complete():
                    repaired_json, success = self._handle_json_completion()
                    if success:
                        out_parts.append(json.dumps(repaired_json))
                    else:
                        out_parts.append(self._buffer)
                    self._reset_state()

            self._log_buffer_capacity_warning()

        if content.is_done:
            final_output = self._flush_final_buffer()
            if final_output:
                out_parts.append(final_output)
            self._reset_state()

        new_text = "".join(out_parts)
        if new_text or content.is_done:
            return StreamingContent(
                content=new_text,
                is_done=content.is_done,
                metadata=content.metadata,
                usage=content.usage,
                raw_data=content.raw_data,
            )

        return StreamingContent(content="")

    def _handle_non_json_text(self, text: str, i: int, n: int) -> tuple[int, list[str]]:
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
        self._json_started = True
        self._buffer = ch
        self._brace_level = 1
        self._in_string = False
        return start_pos + 1, out_parts

    def _process_json_character(self, text: str, i: int) -> int:
        ch = text[i]
        if ch == '"':
            if not self._is_current_quote_escaped():
                self._in_string = not self._in_string
        elif not self._in_string:
            if ch == "{" or ch == "[":
                self._brace_level += 1
            elif ch == "}" or ch == "]":
                self._brace_level -= 1
        self._buffer += ch
        return i + 1

    def _is_current_quote_escaped(self) -> bool:
        """Check if the current quote character is escaped."""

        backslash_count = 0
        for existing_char in reversed(self._buffer):
            if existing_char == "\\":
                backslash_count += 1
            else:
                break
        return backslash_count % 2 == 1

    def _is_json_complete(self) -> bool:
        return self._json_started and self._brace_level == 0 and not self._in_string

    def _handle_json_completion(self) -> tuple[Any, bool]:
        repaired = None
        success = False
        try:
            repaired = self._service.repair_and_validate_json(
                self._buffer,
                schema=self._schema,
                strict=self._strict_mode,
            )
            if repaired is not None:
                success = True
        except Exception as e:  # pragma: no cover - strict mode rethrow
            if self._strict_mode:
                raise JSONParsingError(
                    message=f"JSON repair failed in strict mode: {e}",
                    details={"original_buffer": self._buffer},
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

    def _log_buffer_capacity_warning(self) -> None:
        if self._json_started and len(self._buffer) > self._buffer_cap_bytes:
            logger.warning(
                "Buffer capacity exceeded during JSON repair. Continuing to buffer until completion."
            )

    def _flush_final_buffer(self) -> str | None:
        if self._json_started and self._buffer:
            buf = self._buffer
            if not self._in_string and buf.rstrip().endswith(":"):
                buf = buf + " null"
            repaired_final = self._service.repair_and_validate_json(
                buf, schema=self._schema, strict=self._strict_mode
            )
            if repaired_final is not None:
                metrics.inc(
                    "json_repair.streaming.strict_success"
                    if self._strict_mode
                    else "json_repair.streaming.best_effort_success"
                )
                return json.dumps(repaired_final)
            else:
                metrics.inc(
                    "json_repair.streaming.strict_fail"
                    if self._strict_mode
                    else "json_repair.streaming.best_effort_fail"
                )
                return self._buffer
        return None
