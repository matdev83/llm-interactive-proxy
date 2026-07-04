"""Codex app-server notification -> stream-piece mapper.

Maps Codex JSON-RPC notifications (``item/agentMessage/delta``,
``item/reasoning/*``, ``turn/started``, ``turn/plan/updated``, ``item/started``,
``item/completed``, ``turn/completed``) to :class:`CodexStreamPiece` sequences
that the shared base-connector streaming/SSE scaffolding consumes. Maintains
internal state for open thinking blocks and the once-per-turn ``turn/started``
marker. Never streams raw diffs, command output, env or secrets; only short
progress summaries.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from src.connectors.acp_core.types import ACPNotification, AcpStreamPiece
from src.connectors.codex_helpers import _command_basename, _cwd_basename

logger = logging.getLogger(__name__)

CODEX_TURN_COMPLETED_METHOD = "turn/completed"


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
    """Map Codex JSON-RPC notifications to :class:`CodexStreamPiece` sequences.

    Maintains internal state for open thinking blocks and in-progress
    command/file items so completions can emit compact summaries. Never streams
    raw diffs, command output, env or secrets; only short progress summaries.
    """

    def __init__(self, progress_mode: str = "text_plus_summaries") -> None:
        self._progress_mode = progress_mode or "text_plus_summaries"
        self._thinking_block_open = False
        self._turn_started_emitted = False

    @staticmethod
    def _open_thinking_block(text: str) -> str:
        return f"Thinking:\n{text}"

    @staticmethod
    def _append_thinking_block(text: str) -> str:
        return text

    @staticmethod
    def _close_thinking_block() -> str:
        return "\n\n"

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

    def handle(self, msg: ACPNotification) -> list[CodexStreamPiece]:
        method = msg.method or ""
        params = msg.params if isinstance(msg.params, dict) else {}

        if method == "item/agentMessage/delta":
            delta = params.get("delta")
            if isinstance(delta, str) and delta:
                return [CodexStreamPiece(content=delta)]
            return []

        if method in ("item/reasoning/summaryTextDelta", "item/reasoning/textDelta"):
            delta = params.get("delta")
            if not isinstance(delta, str) or not delta:
                return []
            if self._thinking_block_open:
                return [
                    CodexStreamPiece(
                        reasoning_content=self._append_thinking_block(delta)
                    )
                ]
            self._thinking_block_open = True
            return [
                CodexStreamPiece(reasoning_content=self._open_thinking_block(delta))
            ]

        if method == "turn/started":
            if not self._summaries_enabled() or self._turn_started_emitted:
                return []
            self._turn_started_emitted = True
            return [CodexStreamPiece(content="\n[turn started]\n")]

        if method == "turn/plan/updated":
            if not self._summaries_enabled():
                return []
            return [self._plan_summary_piece(params)]

        if method == "item/started":
            return self._item_started_pieces(params)

        if method == "item/completed":
            return self._item_completed_pieces(params)

        if method == CODEX_TURN_COMPLETED_METHOD:
            return self._turn_completed_pieces(params)

        # Explicitly suppressed raw streams / informational notifications.
        if method in (
            "item/commandExecution/outputDelta",
            "item/fileChange/outputDelta",
            "item/plan/delta",
            "turn/diff/updated",
            "thread/started",
            "thread/tokenUsage/updated",
            "serverRequest/resolved",
            "item/reasoning/summaryPartAdded",
        ):
            return []

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

    def _item_started_pieces(self, params: dict[str, Any]) -> list[CodexStreamPiece]:
        item = self._item_from_params(params)
        item_type = item.get("type")
        if item_type == "commandExecution":
            command = item.get("command")
            cwd = item.get("cwd")
            if self._summaries_enabled():
                return [
                    CodexStreamPiece(
                        content=(
                            f"[command] start: {_command_basename(command)} "
                            f"(cwd: {_cwd_basename(cwd)})"
                        )
                    )
                ]
            return []
        if item_type == "fileChange":
            if self._summaries_enabled():
                summary = self._file_change_summary(item)
                return [CodexStreamPiece(content=summary)]
            return []
        return []

    def _item_completed_pieces(self, params: dict[str, Any]) -> list[CodexStreamPiece]:
        item = self._item_from_params(params)
        item_type = item.get("type")
        if item_type == "commandExecution":
            # Gate command-completion summaries behind the same summaries flag
            # used by ``_item_started_pieces`` so ``progress_mode="text_only"``
            # suppresses both start and done summaries (only agentMessage deltas
            # and reasoning are emitted).
            if not self._summaries_enabled():
                return []
            command = item.get("command")
            exit_code = item.get("exitCode")
            duration_ms = item.get("durationMs")
            exit_text = f" exit={exit_code}" if exit_code is not None else ""
            dur_text = f" dur={duration_ms}ms" if duration_ms is not None else ""
            return [
                CodexStreamPiece(
                    content=(
                        f"[command] done: {_command_basename(command)}{exit_text}{dur_text}"
                    )
                )
            ]
        if item_type == "fileChange":
            if not self._summaries_enabled():
                return []
            summary = self._file_change_summary(item)
            return [CodexStreamPiece(content=summary)]
        if item_type == "agentMessage":
            return []
        return []

    @staticmethod
    def _file_change_summary(item: dict[str, Any]) -> str:
        changes = item.get("changes")
        paths: list[str] = []
        kind = ""
        if isinstance(changes, list):
            for change in changes:
                if not isinstance(change, dict):
                    continue
                path = change.get("path")
                if isinstance(path, str) and path:
                    paths.append(path)
                change_kind = change.get("kind")
                if isinstance(change_kind, str) and change_kind and not kind:
                    kind = change_kind
        paths_text = ", ".join(paths) if paths else "<no paths>"
        summary = (
            f"[file] changed: {paths_text} ({kind})"
            if kind
            else f"[file] changed: {paths_text}"
        )
        if len(summary) > 120:
            summary = summary[:117] + "..."
        return summary

    def _turn_completed_pieces(self, params: dict[str, Any]) -> list[CodexStreamPiece]:
        pieces: list[CodexStreamPiece] = []
        if self._thinking_block_open:
            pieces.append(
                CodexStreamPiece(reasoning_content=self._close_thinking_block())
            )
            self._thinking_block_open = False
        turn_obj = params.get("turn")
        status = (
            turn_obj.get("status")
            if isinstance(turn_obj, dict)
            else params.get("status")
        )
        status_str = status if isinstance(status, str) else ""
        if self._summaries_enabled():
            pieces.append(
                CodexStreamPiece(content=f"\n[turn completed: {status_str}]\n")
            )
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
