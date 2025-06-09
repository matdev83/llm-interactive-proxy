from __future__ import annotations

import logging # Add logging import
from typing import List, Dict, Optional, Any

from pydantic import BaseModel, ConfigDict, Field

from .proxy_logic import ProxyState
import src.models as models

logger = logging.getLogger(__name__) # Add logger definition


class SessionInteraction(BaseModel):
    """Represents one user prompt and the resulting response."""

    prompt: str
    handler: str  # "proxy" or "backend"
    backend: Optional[str] = None
    model: Optional[str] = None
    project: Optional[str] = None
    parameters: Dict[str, Any] = {}
    response: Optional[str] = None
    usage: Optional[models.CompletionUsage] = None


class Session(BaseModel):
    """Container for conversation state and history."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    session_id: str
    proxy_state: ProxyState
    history: List[SessionInteraction] = Field(default_factory=list)
    agent: Optional[str] = None

    def add_interaction(self, interaction: SessionInteraction) -> None:
        self.history.append(interaction)


class SessionManager:
    """Manages Session instances keyed by session_id."""

    def __init__(
        self,
        default_interactive_mode: bool = True,
        failover_routes: Optional[dict[str, dict[str, object]]] | None = None,
    ) -> None:
        self.sessions: Dict[str, Session] = {}
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
            logger.info(f"Created new session: {session_id}")
        logger.debug(f"Retrieving session: {session_id}, ProxyState ID: {id(self.sessions[session_id].proxy_state)}")
        return self.sessions[session_id]
