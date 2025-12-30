"""
Failure handling strategy resolution helper.

Provides stable helper for resolving failure handling strategy from DI or config.
This helper is used by both the resilience registrar and BackendStage to avoid
duplication and ensure consistent behavior.
"""

from __future__ import annotations

from typing import Any, cast

from src.core.interfaces.configuration_interface import IConfig
from src.core.interfaces.di_interface import IServiceProvider
from src.core.interfaces.failure_strategy_interface import (
    IFailureHandlingStrategy,
)


def resolve_failure_strategy(
    provider: IServiceProvider,
    config: IConfig,
    routing_service: Any = None,
) -> IFailureHandlingStrategy | None:
    """Resolve failure handling strategy from DI or construct from config.

    This helper encapsulates the conditional logic for resolving failure handling
    strategy. It first checks if a strategy is pre-registered in DI, then falls
    back to constructing one from config if enabled.

    Args:
        provider: DI service provider
        config: Application configuration
        routing_service: Optional routing service for backend discovery

    Returns:
        IFailureHandlingStrategy instance or None if disabled
    """
    # Try to get pre-registered strategy from DI first
    # Optional service - handle RuntimeError when not registered
    failure_handling_strategy = None
    try:
        failure_handling_strategy = provider.get_service(
            cast(type, IFailureHandlingStrategy)
        )
    except RuntimeError:
        # Service not registered - this is expected for optional services
        pass
    if failure_handling_strategy is not None:
        return failure_handling_strategy

    # No pre-registered strategy; check config to determine if we should construct one
    failure_handling_settings = getattr(config, "failure_handling", None)
    if failure_handling_settings is None:
        # Config doesn't have failure_handling section
        return None

    enabled_setting = getattr(failure_handling_settings, "enabled", None)
    if not isinstance(enabled_setting, bool):
        # Invalid or missing enabled setting
        return None

    if not enabled_setting:
        # Explicitly disabled
        return None

    # Construct strategy from config
    from src.core.interfaces.failure_strategy_interface import FailureHandlingConfig
    from src.core.services.failure_handling_strategy import (
        DefaultFailureHandlingStrategy,
    )

    def _coerce_float(name: str, default: float) -> float:
        value = getattr(failure_handling_settings, name, default)
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _coerce_int(name: str, default: int) -> int:
        value = getattr(failure_handling_settings, name, default)
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    return DefaultFailureHandlingStrategy(
        config=FailureHandlingConfig(
            max_silent_wait=_coerce_float("max_silent_wait", 60.0),
            total_timeout_budget=_coerce_float("total_timeout_budget", 90.0),
            keepalive_interval=_coerce_float("keepalive_interval", 8.0),
            max_failover_hops=_coerce_int("max_failover_hops", 5),
            min_retry_wait=_coerce_float("min_retry_wait", 1.0),
        ),
        backend_discovery=routing_service,
    )
