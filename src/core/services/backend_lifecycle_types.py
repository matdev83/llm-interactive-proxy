from __future__ import annotations

from pydantic import Field

from src.core.interfaces.model_bases import DomainModel


class DisabledBackendInfo(DomainModel):
    """Information about a permanently disabled backend."""

    reason: str = Field(description="The reason why the backend was disabled")
    timestamp: float = Field(description="Unix timestamp when the backend was disabled")
