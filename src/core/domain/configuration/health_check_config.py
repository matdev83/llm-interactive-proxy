"""Health check configuration models.

This module defines the Pydantic models for configuring health checks
on backend API endpoints.
"""

from __future__ import annotations

from pydantic import ConfigDict, Field

from src.core.interfaces.model_bases import DomainModel


class PingCheckConfig(DomainModel):
    """Configuration for ICMP ping health checks.

    Attributes:
        enabled: Whether ping checks are enabled.
        interval_seconds: How often to run ping checks.
        timeout_seconds: Timeout for each ping attempt.
        failure_threshold: Number of consecutive failures before marking unhealthy.
        count: Number of ping packets to send per check.
    """

    model_config = ConfigDict(frozen=True)

    enabled: bool = True
    interval_seconds: int = Field(default=30, ge=5, le=3600)
    timeout_seconds: int = Field(default=5, ge=1, le=60)
    failure_threshold: int = Field(default=3, ge=1, le=100)
    count: int = Field(default=1, ge=1, le=10)


class HttpCheckConfig(DomainModel):
    """Configuration for HTTP health checks.

    Attributes:
        enabled: Whether HTTP checks are enabled.
        interval_seconds: How often to run HTTP checks.
        timeout_seconds: Timeout for each HTTP request.
        failure_threshold: Number of consecutive failures before marking unhealthy.
        method: HTTP method to use for health checks (GET or HEAD).
        path: Path to probe (appended to API URL). Empty means probe base URL.
        accept_any_response: If True, any HTTP response (even 4xx/5xx) is considered success.
    """

    model_config = ConfigDict(frozen=True)

    enabled: bool = True
    interval_seconds: int = Field(default=60, ge=5, le=3600)
    timeout_seconds: int = Field(default=10, ge=1, le=120)
    failure_threshold: int = Field(default=2, ge=1, le=100)
    method: str = Field(default="HEAD", pattern="^(GET|HEAD)$")
    path: str = Field(default="")
    accept_any_response: bool = Field(
        default=True,
        description="If True, any valid HTTP response is considered a success",
    )


class HealthCheckConfig(DomainModel):
    """Top-level health check configuration.

    Attributes:
        enabled: Master switch to enable/disable all health checks.
        ping: Configuration for ICMP ping checks.
        http: Configuration for HTTP checks.
        log_healthy_checks: Whether to log successful health checks (verbose).
        notify_backends: Whether to notify backends about health state changes.
        circuit_breaker_enabled: Whether to auto-disable backends when unhealthy.
    """

    model_config = ConfigDict(frozen=True)

    enabled: bool = True
    ping: PingCheckConfig = Field(default_factory=PingCheckConfig)
    http: HttpCheckConfig = Field(default_factory=HttpCheckConfig)
    log_healthy_checks: bool = Field(
        default=False,
        description="Log successful health checks (can be verbose)",
    )
    notify_backends: bool = Field(
        default=True,
        description="Notify backend connectors about health state changes",
    )
    circuit_breaker_enabled: bool = Field(
        default=True,
        description="Auto-disable backends when their API endpoint is unhealthy",
    )


# Default configuration instance for convenience
DEFAULT_HEALTH_CHECK_CONFIG = HealthCheckConfig()


__all__ = [
    "PingCheckConfig",
    "HttpCheckConfig",
    "HealthCheckConfig",
    "DEFAULT_HEALTH_CHECK_CONFIG",
]
