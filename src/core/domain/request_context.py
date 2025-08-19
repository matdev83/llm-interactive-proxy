from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass
class RequestContext:
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
    original_request: Any | None = None


