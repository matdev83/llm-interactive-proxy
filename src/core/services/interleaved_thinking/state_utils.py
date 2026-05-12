from __future__ import annotations

from typing import Any, cast

from src.core.domain.request_context import RequestContext
from src.core.domain.session import SessionState
from src.core.interfaces.domain_entities_interface import ISession


def as_session_state(state: Any) -> SessionState | None:
    if isinstance(state, SessionState):
        return state
    to_dict = getattr(state, "to_dict", None)
    if callable(to_dict):
        raw = to_dict()
        if isinstance(raw, dict):
            return cast(SessionState, SessionState.from_dict(raw))
    return None


def request_id(context: RequestContext | None) -> str | None:
    return context.request_id if context is not None else None


def session_id(context: RequestContext | None, session: ISession | None) -> str | None:
    if context is not None and context.session_id:
        return context.session_id
    raw_session_id = getattr(session, "session_id", None)
    return raw_session_id if isinstance(raw_session_id, str) else None
