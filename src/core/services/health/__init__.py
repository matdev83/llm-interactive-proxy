"""Health check services.

This module provides services for monitoring the health of backend API endpoints.
The system follows an event-driven architecture with decoupled components:

- EndpointRegistry: Maps API URLs to backend instances
- ICMPHealthChecker: Performs ping checks
- HTTPHealthChecker: Performs HTTP probe checks
- HealthStateManager: Tracks state and emits transitions
- HealthCheckScheduler: Runs periodic checks in background
- HealthLoggingHandler: Logs state transitions
- BackendHealthNotifier: Routes health events to backend connectors

Usage:
    The health check system is initialized during application startup
    via the HealthCheckStage.
"""

from __future__ import annotations

from src.core.services.health.backend_notifier import BackendHealthNotifier
from src.core.services.health.endpoint_registry import EndpointRegistry
from src.core.services.health.health_check_scheduler import HealthCheckScheduler
from src.core.services.health.http_checker import HTTPHealthChecker
from src.core.services.health.icmp_checker import ICMPHealthChecker
from src.core.services.health.logging_handler import HealthLoggingHandler
from src.core.services.health.state_manager import HealthStateManager

__all__ = [
    "EndpointRegistry",
    "ICMPHealthChecker",
    "HTTPHealthChecker",
    "HealthStateManager",
    "HealthCheckScheduler",
    "HealthLoggingHandler",
    "BackendHealthNotifier",
]
