from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class StateAccessLogEntry(BaseModel):
    """Represents a single entry in the state access log."""

    operation: str
    access_type: str
    timestamp: float
    data: dict[str, Any] = Field(default_factory=dict)
