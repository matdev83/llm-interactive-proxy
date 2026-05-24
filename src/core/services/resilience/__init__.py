"""
Resilience layer for backend error handling and rate limiting.

This module provides centralized handling of:
- Rate limit tracking at instance and model levels
- Error classification and handling via Chain of Responsibility
- Backend availability decisions

Components:
- RateLimitStateManager: Tracks cooldowns per instance and (instance, model)
- ResilienceCoordinator: Main entry point for pre/post call checks
- Error handlers: RateLimitErrorHandler, AuthErrorHandler
"""

from src.core.services.resilience.coordinator import ResilienceCoordinator
from src.core.services.resilience.rate_limit_state import (
    InstanceStatus,
    RateLimitStateManager,
)

__all__ = [
    "InstanceStatus",
    "RateLimitStateManager",
    "ResilienceCoordinator",
]
