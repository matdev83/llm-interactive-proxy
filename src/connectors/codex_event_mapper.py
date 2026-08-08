"""Codex app-server notification -> stream-piece mapper (ACP-style rendering).

Maps Codex JSON-RPC notifications (``item/agentMessage/delta``,
``item/reasoning/*``, ``turn/plan/updated``, ``item/started``,
``item/completed``, ``turn/completed``) to :class:`CodexStreamPiece` sequences
that the shared base-connector streaming/SSE scaffolding consumes.

Rendering intentionally mirrors the ACP base connector
(:meth:`BaseAcpConnector._session_update_to_stream_pieces`) so users of the
proxy see the same formatted agent output regardless of which local-agent
backend they target:

* Reasoning is surfaced as **visible ``Thinking:\\n…`` blocks in ``content``**
  (inline with the assistant message, not a separate ``reasoning_content``
  channel) and closed with a blank line before the next non-reasoning piece.
* Command / file activity is emitted as **fenced ``\\`\\`\\`text`` /
  ``Tool: …`` completion blocks** via
  :func:`format_acp_tool_completion_summary` -- on completion only, never on
  start, and never with raw command stdout, full diffs, env, or secrets.
* ``[turn started]`` / ``[turn completed: …]`` markers are NOT emitted; the
  terminal ``turn/completed`` notification only produces the ``done`` piece
  that drives ``finish_reason`` and the deferred history-state commit.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from src.connectors.acp_core.tool_markdown import format_acp_tool_completion_summary
from src.connectors.acp_core.types import ACPNotification, AcpStreamPiece
from src.connectors.codex_helpers import _command_basename

logger = logging.getLogger(__name__)

CODEX_TURN_COMPLETED_METHOD = "turn/completed"

# Codex item types that map to an ACP-style tool-completion summary.
_COMMAND_EXECUTION_TYPE = "commandExecution"
_FILE_CHANGE_TYPE = "fileChange"


@dataclass(frozen=True, slots=True)
class CodexStreamPiece(AcpStreamPiece):
    """One streaming unit emitted by the Codex event mapper.

    Extends :class:`AcpStreamPiece` with the terminal-turn markers: ``done``
    marks the last piece for a turn and ``finish_reason`` carries the Codex turn
    status (``stop`` / ``interrupted`` / ``error``) so the SSE builder and the
    non-streaming accumulator can map it to an OpenAI-compatible value.
    """

    done: bool = False
    finish_reason: str | None = None


def accumulate_pieces(pieces: Sequence[CodexStreamPiece]) -> tuple[str, str | None]:
    """Join streamed pieces into ``(content, reasoning_content | None)``."""

    content_parts = [p.content for p in pieces if p.content]
    reasoning_parts = [p.reasoning_content for p in pieces if p.reasoning_content]
    full_content = "".join(content_parts)
    full_reasoning = "".join(reasoning_parts) if reasoning_parts else None
    return full_content, full_reasoning


class CodexEventMapper:
    """Map Codex JSON-RPC notifications to ACP-style :class:`CodexStreamPiece` sequences.

    See the module docstring for the rendering contract. Maintains internal
    state for the open thinking block so it can be closed before the next
    agent message, tool-completion summary, or terminal turn piece.
    """

    def __init__(self, progress_mode: str = "text_plus_summaries") -> None:
        self._progress_mode = progress_mode or "text_plus_summaries"
        self._thinking_block_open = False

    def _summaries_enabled(self) -> bool:
        return "summaries" in self._progress_mode

    @staticmethod
    def _item_from_params(params: dict[str, Any] | None) -> dict[str, Any]:
        if not isinstance(params, dict):
            return {}
        item = params.get("item")
        if isinstance(item, dict):
            return item
        return params

    def _close_thinking_if_open(self) -> list[CodexStreamPiece]:
        if self._thinking_block_open:
            self._thinking_block_open = False
            return [CodexStreamPiece(content="\n\n")]
        return []

    def handle(self, msg: ACPNotification) -> list[CodexStreamPiece]:
        method = msg.method or ""
        params = msg.params if isinstance(msg.params, dict) else {}

        if method == "item/agentMessage/delta":
            delta = params.get("delta")
            if isinstance(delta, str) and delta:
                return [
                    *self._close_thinking_if_open(),
                    CodexStreamPiece(content=delta),
                ]
            return []

        if method in ("item/reasoning/summaryTextDelta", "item/reasoning/textDelta"):
            delta = params.get("delta")
            if not isinstance(delta, str) or not delta:
                return []
            if self._thinking_block_open:
                return [CodexStreamPiece(content=delta)]
            self._thinking_block_open = True
            return [CodexStreamPiece(content=f"Thinking:\n{delta}")]

        if method == "turn/plan/updated":
            if not self._summaries_enabled():
                return []
            return [*self._close_thinking_if_open(), self._plan_summary_piece(params)]

        if method == "item/started":
            # ACP emits tool summaries only on completion; nothing to stream at start.
            return []

        if method == "item/completed":
            return self._item_completed_pieces(params)

        if method == CODEX_TURN_COMPLETED_METHOD:
            return self._turn_completed_pieces(params)

        # Explicitly suppressed raw streams / informational notifications:
        # item/commandExecution/outputDelta, item/fileChange/outputDelta,
        # item/plan/delta, turn/diff/updated, thread/started,
        # thread/tokenUsage/updated, serverRequest/resolved,
        # item/reasoning/summaryPartAdded, turn/started.
        return []

    def _plan_summary_piece(self, params: dict[str, Any]) -> CodexStreamPiece:
        plan = params.get("plan")
        entries: list[str] = []
        if isinstance(plan, list):
            for idx, entry in enumerate(plan, start=1):
                if not isinstance(entry, dict):
                    continue
                step = entry.get("step")
                status = entry.get("status")
                step_text = str(step) if step is not None else "?"
                status_text = str(status) if status is not None else "?"
                entries.append(f"{idx}. {step_text} ({status_text})")
        text = "[plan] " + ", ".join(entries) if entries else "[plan]"
        if len(text) > 120:
            text = text[:117] + "..."
        return CodexStreamPiece(content=text)

    def _item_completed_pieces(self, params: dict[str, Any]) -> list[CodexStreamPiece]:
        if not self._summaries_enabled():
            return []
        item = self._item_from_params(params)
        item_type = item.get("type")
        if item_type == _COMMAND_EXECUTION_TYPE:
            return [*self._close_thinking_if_open(), self._command_summary_piece(item)]
        if item_type == _FILE_CHANGE_TYPE:
            return [
                *self._close_thinking_if_open(),
                self._file_change_summary_piece(item),
            ]
        return []

    @staticmethod
    def _command_summary_piece(item: dict[str, Any]) -> CodexStreamPiece:
        """Fenced ``Tool:`` block for a completed Codex shell command (no raw I/O)."""
        # Prefer the user-facing command from ``commandActions`` (the actual
        # invoked command) over the wrapped ``command`` field, which on Windows
        # is a quoted shell path like '"C:\Program Files\PowerShell\7\pwsh.exe"
        # -Command ...' whose first-token basename mis-resolves to "Program".
        actual_command = ""
        actions = item.get("commandActions")
        if isinstance(actions, list) and actions and isinstance(actions[0], dict):
            first_action = actions[0].get("command")
            if isinstance(first_action, str) and first_action.strip():
                actual_command = first_action
        if not actual_command:
            raw_command = item.get("command")
            if isinstance(raw_command, str):
                actual_command = raw_command
        duration_ms = item.get("durationMs")
        elapsed_s = (
            float(duration_ms) / 1000.0 if isinstance(duration_ms, int | float) else 0.0
        )
        ended_dt = datetime.now(timezone.utc)
        started_dt = ended_dt - timedelta(seconds=elapsed_s)
        aggregated_output = item.get("aggregatedOutput")
        output_bytes = (
            len(aggregated_output.encode("utf-8"))
            if isinstance(aggregated_output, str)
            else 0
        )
        text = format_acp_tool_completion_summary(
            _command_basename(actual_command) or "command",
            input_payload=None,
            input_bytes=len(actual_command.encode("utf-8")),
            # Only the output SIZE is surfaced (ACP-style); raw stdout is never streamed.
            output_bytes=output_bytes,
            started_iso=started_dt.isoformat(),
            ended_iso=ended_dt.isoformat(),
            elapsed_s=elapsed_s,
        )
        return CodexStreamPiece(content=text)

    @staticmethod
    def _file_change_summary_piece(item: dict[str, Any]) -> CodexStreamPiece:
        """Fenced ``Tool:`` block for a completed Codex file change (no raw diff)."""
        changes = item.get("changes")
        paths: list[str] = []
        if isinstance(changes, list):
            for change in changes:
                if isinstance(change, dict):
                    path = change.get("path")
                    if isinstance(path, str) and path:
                        paths.append(path)
        ended_dt = datetime.now(timezone.utc)
        text = format_acp_tool_completion_summary(
            _FILE_CHANGE_TYPE,
            input_payload=None,
            input_bytes=len(", ".join(paths).encode("utf-8")) if paths else 0,
            # The diff body is never streamed; output size stays 0.
            output_bytes=0,
            started_iso=ended_dt.isoformat(),
            ended_iso=ended_dt.isoformat(),
            elapsed_s=0.0,
        )
        return CodexStreamPiece(content=text)

    def _turn_completed_pieces(self, params: dict[str, Any]) -> list[CodexStreamPiece]:
        pieces = self._close_thinking_if_open()
        turn_obj = params.get("turn")
        status = (
            turn_obj.get("status")
            if isinstance(turn_obj, dict)
            else params.get("status")
        )
        status_str = status if isinstance(status, str) else ""
        if status_str == "completed":
            finish_reason = "stop"
        elif status_str == "interrupted":
            finish_reason = "interrupted"
        elif status_str == "failed":
            finish_reason = "error"
        else:
            # Unknown/empty turn status: fail closed. Do NOT treat as success
            # (do not let the stream loop commit history_state on an
            # unrecognized status). Surface as an error so a retry resends the
            # correct input.
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Codex turn/completed with unrecognized status %r; "
                    "treating as failed",
                    status_str,
                )
            finish_reason = "error"
        pieces.append(CodexStreamPiece(done=True, finish_reason=finish_reason))
        return pieces
