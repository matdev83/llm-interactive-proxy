"""Hybrid backend connector package."""

from __future__ import annotations

from src.core.services.backend_registry import backend_registry

from .connector import HybridConnector, logger
from .types import ReasoningPhaseResult

backend_registry.register_backend("hybrid", HybridConnector)

__all__ = ["HybridConnector", "ReasoningPhaseResult", "logger"]
