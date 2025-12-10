"""Failure handling configuration models.

This module defines the Pydantic models for configuring the failure handling
strategy that manages backend errors, retries, and failovers.
"""

from __future__ import annotations

from pydantic import ConfigDict, Field

from src.core.interfaces.model_bases import DomainModel


class FailureHandlingConfig(DomainModel):
    """Configuration for failure handling behavior.

    The failure handling strategy determines how the proxy responds to backend
    failures such as rate limits (429), connection errors, and authentication
    failures. It supports silent retries for short waits, automatic failover
    to alternative backends, and streaming keep-alive during wait periods.

    Attributes:
        enabled: Master switch to enable/disable failure handling.
        max_silent_wait: Maximum seconds to wait for retry-after before failover.
            If a backend returns retry-after <= this value, the proxy waits
            silently and retries. If > this value, it attempts failover.
        total_timeout_budget: Maximum total seconds across all failover attempts.
            After this time, any remaining errors are surfaced to the client.
        keepalive_interval: Seconds between SSE keepalive comments during waits.
            Prevents client/connection timeouts during retry wait periods.
        max_failover_hops: Maximum number of backend instances to try.
            Limits the failover chain to prevent infinite loops.
        min_retry_wait: Minimum wait time even for sub-second retry-after.
            Prevents tight retry loops that could overwhelm backends.
    """

    model_config = ConfigDict(frozen=True)

    enabled: bool = Field(
        default=True,
        description="Enable failure handling strategy for automatic retry/failover",
    )
    max_silent_wait: float = Field(
        default=60.0,
        ge=0.0,
        le=300.0,
        description="Max seconds to wait before attempting failover (0-300)",
    )
    total_timeout_budget: float = Field(
        default=90.0,
        ge=0.0,
        le=600.0,
        description="Total timeout budget across all failover attempts (0-600)",
    )
    keepalive_interval: float = Field(
        default=8.0,
        ge=1.0,
        le=60.0,
        description="Seconds between SSE keepalive comments during waits (1-60)",
    )
    max_failover_hops: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Maximum backend instances to try in failover chain (1-20)",
    )
    min_retry_wait: float = Field(
        default=1.0,
        ge=0.1,
        le=30.0,
        description="Minimum retry wait even for sub-second retry-after (0.1-30)",
    )


# Default configuration instance for convenience
DEFAULT_FAILURE_HANDLING_CONFIG = FailureHandlingConfig()


__all__ = [
    "FailureHandlingConfig",
    "DEFAULT_FAILURE_HANDLING_CONFIG",
]
