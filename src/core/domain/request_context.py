from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.core.interfaces.model_bases import InternalDTO


@dataclass
class RequestContext(InternalDTO):
    """Transport-agnostic request context used by core services.

    Fields intentionally small: headers and cookies are plain dicts, state and
    app_state carry transport-specific state objects when needed. The original
    request may be provided for advanced adapters but core code should prefer
    the structured fields.
    """

    headers: dict[str, str]
    cookies: dict[str, str]
    state: Any
    app_state: Any
    client_host: str | None = None
    session_id: str | None = None
    agent: str | None = None  # Add agent field
    original_request: Any | None = None
    processing_context: dict[str, Any] | None = (
        None  # Add processing context for middleware
    )
