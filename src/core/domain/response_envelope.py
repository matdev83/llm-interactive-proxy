from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ResponseEnvelope:
    """Transport-agnostic response container for non-streaming responses.
    
    Decouples backend connectors from FastAPI/Starlette Response.
    Adapters in controller layers are responsible for mapping this to the 
    appropriate transport-specific response types.
    """
    
    content: Any  # Response content (dict, string, bytes, etc.)
    headers: dict[str, str] | None = None
    status_code: int = 200
    media_type: str = "application/json"
