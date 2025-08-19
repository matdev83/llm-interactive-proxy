from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass


@dataclass
class StreamingResponseEnvelope:
    """Transport-agnostic streaming response container.
    
    Decouples backend connectors from FastAPI/Starlette StreamingResponse.
    Adapters in controller layers are responsible for mapping this to the 
    appropriate transport-specific response types.
    """
    
    content: AsyncIterator[bytes]
    media_type: str = "text/event-stream"
    headers: dict[str, str] | None = None
