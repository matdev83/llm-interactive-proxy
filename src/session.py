from __future__ import annotations

from typing import List, Dict, Optional, Any

from pydantic import BaseModel, ConfigDict

from .proxy_logic import ProxyState
import src.models as models


class SessionInteraction(BaseModel):
    """Represents one user prompt and the resulting response."""

    prompt: str
    handler: str  # "proxy" or "backend"
    backend: Optional[str] = None
    model: Optional[str] = None
    parameters: Dict[str, Any] = {}
    response: Optional[str] = None
    usage: Optional[models.CompletionUsage] = None


class Session(BaseModel):
    """Container for conversation state and history."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    session_id: str
    proxy_state: ProxyState = ProxyState()
    history: List[SessionInteraction] = []

    def add_interaction(self, interaction: SessionInteraction) -> None:
        self.history.append(interaction)


class SessionManager:
    """Manages Session instances keyed by session_id."""

    def __init__(self) -> None:
        self.sessions: Dict[str, Session] = {}

    def get_session(self, session_id: str) -> Session:
        if session_id not in self.sessions:
            self.sessions[session_id] = Session(session_id=session_id)
        return self.sessions[session_id]
