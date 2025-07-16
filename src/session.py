from __future__ import annotations

import logging  # Add logging import
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

import src.models as models

from .proxy_logic import ProxyState

logger = logging.getLogger(__name__)  # Add logger definition


class SessionInteraction(BaseModel):
    """Represents one user prompt and the resulting response."""

    prompt: str
    handler: str  # "proxy" or "backend"
    backend: str | None = None
    model: str | None = None
    project: str | None = None
    parameters: dict[str, Any] = {}
    response: str | None = None
    usage: models.CompletionUsage | None = None


class Session(BaseModel):
    """Container for conversation state and history."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    session_id: str
    proxy_state: ProxyState
    history: list[SessionInteraction] = Field(default_factory=list)
    agent: str | None = None

    def add_interaction(self, interaction: SessionInteraction) -> None:
        self.history.append(interaction)


class SessionManager:
    """Manages Session instances keyed by session_id."""

    def __init__(
        self,
        default_interactive_mode: bool = True,
        failover_routes: dict[str, dict[str, object]] | None | None = None,
    ) -> None:
        self.sessions: dict[str, Session] = {}
        self.default_interactive_mode = default_interactive_mode
        self.failover_routes = failover_routes if failover_routes is not None else {}

    def get_session(self, session_id: str) -> Session:
        if session_id not in self.sessions:
            self.sessions[session_id] = Session(
                session_id=session_id,
                proxy_state=ProxyState(
                    interactive_mode=self.default_interactive_mode,
                    failover_routes=self.failover_routes,
                ),
            )
            if logger.isEnabledFor(logging.INFO):
                logger.info(f"Created new session: {session_id}")
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                f"Retrieving session: {session_id}, ProxyState ID: {id(self.sessions[session_id].proxy_state)}"
        )
        return self.sessions[session_id]
