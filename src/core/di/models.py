"""Models for dependency injection container."""

from __future__ import annotations
from pydantic import BaseModel

class DIContainerStats(BaseModel):
    """Dependency injection container statistics."""
    instances: int
    factories: int
    singletons: int
    cleanup_callbacks: int
    creation_stack_depth: int

class DIContainerHealth(BaseModel):
    """Dependency injection container health status."""
    stats: DIContainerStats
    issues: list[str]
    healthy: bool
