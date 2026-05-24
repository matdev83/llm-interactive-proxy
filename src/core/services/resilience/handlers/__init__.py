"""
Error handlers for the resilience layer.

This module provides Chain of Responsibility handlers for different
error types:
- RateLimitErrorHandler: Handles 429 errors with retry-after support
- AuthErrorHandler: Handles 401/403 errors by disabling instances
"""

from src.core.services.resilience.handlers.auth_error_handler import AuthErrorHandler
from src.core.services.resilience.handlers.base_handler import BaseErrorHandler
from src.core.services.resilience.handlers.circuit_breaker_handler import (
    CircuitBreakerErrorHandler,
)
from src.core.services.resilience.handlers.rate_limit_handler import (
    RateLimitErrorHandler,
)

__all__ = [
    "AuthErrorHandler",
    "BaseErrorHandler",
    "CircuitBreakerErrorHandler",
    "RateLimitErrorHandler",
]
