from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ACPError(BaseModel):
    """JSON-RPC error payload returned by ACP servers."""

    code: int
    message: str
    data: Any | None = None


class ACPNotification(BaseModel):
    """Loose JSON-RPC message model for ACP stdio exchange."""

    model_config = ConfigDict(extra="allow")

    jsonrpc: str = "2.0"
    id: int | None = None
    method: str | None = None
    params: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    error: ACPError | None = None

    @property
    def is_error(self) -> bool:
        return self.error is not None

    @property
    def is_response(self) -> bool:
        return self.id is not None and (
            self.result is not None or self.error is not None
        )

    @property
    def is_notification(self) -> bool:
        return self.id is None and isinstance(self.method, str)

    @property
    def is_server_request(self) -> bool:
        return (
            self.method is not None
            and self.id is not None
            and self.result is None
            and self.error is None
        )


class ACPUpdateContent(BaseModel):
    """Session update content payload."""

    model_config = ConfigDict(extra="allow")

    type: str | None = None
    text: str | None = None


class ACPSessionUpdate(BaseModel):
    """Notification payload for session/update."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    session_id: str = Field(alias="sessionId")
    update: dict[str, Any]


@dataclass(frozen=True, slots=True)
class AcpStreamPiece:
    """One streaming unit from an ACP ``session/update`` notification.

    ``content`` maps to assistant-visible text. ACP currently uses it for visible
    thinking blocks and tool summaries so downstream renderers can preserve order.
    ``reasoning_content`` remains available for back-compat and non-ACP backends
    that still surface separate reasoning deltas.
    """

    content: str | None = None
    reasoning_content: str | None = None


@dataclass(frozen=True, slots=True)
class AcpSubprocessIdentity:
    """OS-level fingerprint for a pooled ACP child process (PID reuse protection)."""

    pid: int
    create_time: float
    exe_key: str = ""


@dataclass(slots=True)
class AcpToolStreamAccum:
    """Per-tool-call state for one ACP prompt stream (sizes and timing only)."""

    tool_name: str = "tool"
    started_wall_iso: str = ""
    started_perf: float = 0.0
    ended_wall_iso: str | None = None
    ended_perf: float | None = None
    summary_emitted: bool = False
    #: Terminal status arrived before any output bytes were observed.
    pending_terminal_summary: bool = False
    last_input_bytes: int = 0
    last_output_bytes: int = 0


@dataclass(frozen=True, slots=True)
class HistoryState:
    """Tracks how much of ``processed_messages`` has been applied to the ACP agent.

    ``prefix_hash`` is an opaque SHA-256 hex digest of the acknowledged prefix; it is
    computed only inside the ACP base connector and must not be interpreted elsewhere.
    """

    message_count: int
    prefix_hash: str


@dataclass(slots=True)
class ACPProcessRuntime:
    """Live ACP runtime bound to a project directory, model, and client session."""

    project_dir: Path
    model: str
    client_session_id: str = "default"
    process: Any | None = None
    session_id: str | None = None
    initialized: bool = False
    message_id: int = 0
    last_activity: float = 0.0
    history_state: HistoryState | None = None
    process_lock: Any = field(default=None)
    request_lock: Any = field(default=None)
    cancellation_lock: Any = field(default=None)
    cancellation_event: Any = field(default=None)
    #: Per correlation key (``toolCallId`` / ``__anon__:N``) for the current stream.
    acp_tool_stream_accum: dict[str, AcpToolStreamAccum] = field(default_factory=dict)
    acp_anon_tool_seq: int = 0
    acp_last_anon_stream_key: str | None = None
    #: True while ACP reasoning/progress is being emitted as visible ``Thinking:``
    #: content so later deltas can append without reopening the block each time.
    acp_thinking_block_open: bool = False
    #: Pending idle kill task for this pooled ACP runtime (if any).
    stale_kill_task: Any = field(default=None)  # asyncio.Task | None
    #: Captured when the child starts; used before idle-kill to detect PID reuse.
    acp_subprocess_identity: AcpSubprocessIdentity | None = None


@dataclass(slots=True)
class CodexAppServerRuntime(ACPProcessRuntime):
    """Live Codex app-server runtime; extends ACPProcessRuntime with Codex ids
    and a deferred history commit.

    ``thread_id``/``turn_id`` replace ACP's ``session_id`` for the Codex
    app-server protocol. ``pending_history_state`` stages the next history state
    and is committed only when a turn completes successfully
    (``turn/completed`` status ``completed``); a failed/interrupted turn
    discards it so ``runtime.history_state`` keeps its prior value and a client
    retry hits the correct branch.
    """

    thread_id: str | None = None
    turn_id: str | None = None
    pending_history_state: HistoryState | None = None
    # Verbosity applied via ``-c model_verbosity=...`` at spawn time. When a
    # later request asks for a different value, the process is restarted.
    applied_model_verbosity: str | None = None
