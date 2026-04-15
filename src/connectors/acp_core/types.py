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

    ``content`` maps to OpenAI-style ``delta.content`` (assistant-visible text).
    ``reasoning_content`` maps to ``delta.reasoning_content`` for clients that
    surface thinking / progress separately from the final answer.
    """

    content: str | None = None
    reasoning_content: str | None = None


@dataclass(slots=True)
class ACPProcessRuntime:
    """Live ACP runtime bound to a project directory and model."""

    project_dir: Path
    model: str
    process: Any | None = None
    session_id: str | None = None
    initialized: bool = False
    message_id: int = 0
    last_activity: float = 0.0
    history_injected: bool = False
    process_lock: Any = field(default=None)
    request_lock: Any = field(default=None)
    cancellation_lock: Any = field(default=None)
    cancellation_event: Any = field(default=None)
