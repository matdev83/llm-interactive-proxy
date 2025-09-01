"""Configuration domain package exports.

Provides canonical classes and backward-compatible aliases expected by tests.
"""

from __future__ import annotations

from .backend_config import BackendConfiguration
from .loop_detection_config import LoopDetectionConfiguration
from .reasoning_config import ReasoningConfiguration

# Backward-compatible aliases used across tests and older code
BackendConfig = BackendConfiguration
LoopDetectionConfig = LoopDetectionConfiguration
ReasoningConfig = ReasoningConfiguration

__all__ = [
    "BackendConfig",
    "BackendConfiguration",
    "LoopDetectionConfig",
    "LoopDetectionConfiguration",
    "ReasoningConfig",
    "ReasoningConfiguration",
]
