from __future__ import annotations

from pydantic import Field

from src.core.interfaces.model_bases import DomainModel


class FailoverRoute(DomainModel):
    """Failover route configuration."""

    name: str
    policy: str = "k"
    elements: list[str] = Field(default_factory=list)

    class Config:
        extra = "allow"
