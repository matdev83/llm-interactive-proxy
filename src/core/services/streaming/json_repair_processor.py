from __future__ import annotations

import json
import logging
from typing import Any

import src.core.services.metrics_service as metrics
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

        # Process content chunk text if present
        text = content.content or ""

        i = 0
        n = len(text)
        while i < n:
            if not self._json_started:
                # Find next potential JSON start
                brace_pos_obj = text.find("{", i)
                brace_pos_arr = text.find("[", i)
                # Choose earliest non -1
                candidates = [p for p in [brace_pos_obj, brace_pos_arr] if p != -1]
                if not candidates:
                    # No JSON start in the rest of this chunk: pass through remainder
                    if i < n:
                        out_parts.append(text[i:])
                    i = n
                    break
                start_pos = min(candidates)
                # Pass through any text before JSON start
                if start_pos > i:
                    out_parts.append(text[i:start_pos])
                # Initialize JSON buffering
                ch = text[start_pos]
                self._json_started = True
                self._buffer = ch
                self._brace_level = 1
                self._in_string = False
                i = start_pos + 1
            else:
                # We are inside a JSON block: consume characters updating state
                ch = text[i]
                # Toggle in_string on unescaped quote
                if ch == '"':
                    # Check if escaped
                    if not self._buffer.endswith("\\"):
                        self._in_string = not self._in_string
                elif not self._in_string:
                    if ch == "{" or ch == "[":
                        self._brace_level += 1
                    elif ch == "}" or ch == "]":
                        self._brace_level -= 1
                self._buffer += ch
                i += 1

                # Check completion
                if (
                    self._json_started
                    and self._brace_level == 0
                    and not self._in_string
                ):
                    # Attempt to repair and validate
                    try:
                        repaired = self._service.repair_and_validate_json(
                            self._buffer,
                            schema=self._schema,
                            strict=self._strict_mode,
                        )
                    except Exception as e:  # pragma: no cover - strict mode rethrow
                        logger.warning("JSON repair raised error: %s", e)
                        repaired = None

                    if repaired is not None:
                        metrics.inc(
                            "json_repair.streaming.strict_success"
                            if self._strict_mode
                            else "json_repair.streaming.best_effort_success"
                        )
                        out_parts.append(json.dumps(repaired))
                    else:
                        metrics.inc(
                            "json_repair.streaming.strict_fail"
                            if self._strict_mode
                            else "json_repair.streaming.best_effort_fail"
                        )
                        logger.warning(
                            "JSON block detected but failed to repair. Flushing raw buffer."
                        )
                        out_parts.append(self._buffer)

                    # Reset for next detection
                    self._reset_state()

                    # Soft-cap: if buffer exceeded during processing, we only log; state has reset now

            # Soft-cap logging (only informational, do not flush)
            if self._json_started and len(self._buffer) > self._buffer_cap_bytes:
                logger.warning(
                    "Buffer capacity exceeded during JSON repair. Continuing to buffer until completion."
                )

        # If this is the final chunk, flush remaining buffer if any
        if content.is_done:
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
                    out_parts.append(json.dumps(repaired_final))
                else:
                    metrics.inc(
                        "json_repair.streaming.strict_fail"
                        if self._strict_mode
                        else "json_repair.streaming.best_effort_fail"
                    )
                    out_parts.append(self._buffer)
            # After flushing, reset state
            self._reset_state()

        # If we have any output or this is done marker, return content
        new_text = "".join(out_parts)
        if new_text or content.is_done:
            return StreamingContent(
                content=new_text,
                is_done=content.is_done,
                metadata=content.metadata,
                usage=content.usage,
                raw_data=content.raw_data,
            )

        # Otherwise, return empty to indicate no emission this round
        return StreamingContent(content="")
