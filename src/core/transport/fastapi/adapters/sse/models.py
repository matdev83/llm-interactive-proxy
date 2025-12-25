"""Models for SSE adaptation."""

from __future__ import annotations
from typing import Any
from pydantic import BaseModel

class DecodedSSE(BaseModel):
    """Result of SSE decoding."""
    content: Any
    metadata: dict[str, Any]
    is_done: bool
