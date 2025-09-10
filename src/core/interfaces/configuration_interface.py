"""
Configuration interfaces - compatibility shim.

This module re-exports interfaces from the canonical configuration.py module.
"""

from src.core.interfaces.configuration import (
    IAppIdentityConfig,
    IBackendConfig,
    IBackendSpecificConfig,
    IConfig,
    ILoopDetectionConfig,
    IReasoningConfig,
)

__all__ = [
    "IAppIdentityConfig",
    "IBackendConfig",
    "IBackendSpecificConfig",
    "IConfig",
    "ILoopDetectionConfig",
    "IReasoningConfig",
]
