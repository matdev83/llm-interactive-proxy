from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
import uuid

from src.proxy_logic import ProxyState
import logging

logger = logging.getLogger(__name__)

@dataclass
class Interaction:
    prompt: List[Any]
    response: Any
    timestamp: datetime

@dataclass
class Session:
    session_id: str
    client_app: str
    start_time: datetime
    proxy_state: ProxyState = field(default_factory=ProxyState)
    history: List[Interaction] = field(default_factory=list)
    last_activity: datetime = field(default_factory=datetime.utcnow)

class SessionManager:
    def __init__(self, ttl_seconds: int = 300) -> None:
        self.ttl = ttl_seconds
        self.sessions: Dict[str, Session] = {}

    def _generate_id(self) -> str:
        return str(uuid.uuid4())

    def _cleanup_expired(self) -> None:
        now = datetime.utcnow()
        expired = [sid for sid, sess in self.sessions.items() if now - sess.last_activity > timedelta(seconds=self.ttl)]
        for sid in expired:
            logger.info(f"Session {sid} expired, removing")
            self.sessions.pop(sid, None)

    def get_session(self, session_id: Optional[str], client_app: str) -> Session:
        self._cleanup_expired()
        now = datetime.utcnow()
        if session_id and session_id in self.sessions:
            sess = self.sessions[session_id]
            sess.last_activity = now
            return sess
        # create new session with a fresh id
        new_id = self._generate_id()
        sess = Session(session_id=new_id, client_app=client_app, start_time=now)
        self.sessions[new_id] = sess
        return sess

    def add_history(self, session_id: str, prompt: List[Any], response: Any) -> None:
        sess = self.sessions.get(session_id)
        if not sess:
            return
        sess.history.append(Interaction(prompt=prompt, response=response, timestamp=datetime.utcnow()))
        sess.last_activity = datetime.utcnow()

