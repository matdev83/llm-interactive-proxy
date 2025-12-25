from __future__ import annotations

from pydantic import BaseModel, Field


class FailoverRoute(BaseModel):
    """Failover route configuration."""

    name: str
    policy: str = "k"
    elements: list[str] = Field(default_factory=list)

    class Config:
        extra = "allow"
