"""
Pytest configuration file for unit tests.

This file contains shared fixtures and configuration for the unit tests.
"""

import pytest
from src.core.di.container import ServiceCollection
from src.core.interfaces.di import IServiceProvider
from src.core.interfaces.backend_service import IBackendService
from src.core.interfaces.command_service import ICommandService
from src.core.interfaces.loop_detector import ILoopDetector
from src.core.interfaces.rate_limiter import IRateLimiter
from src.core.interfaces.response_processor import IResponseProcessor
from src.core.interfaces.session_service import ISessionService
from src.core.interfaces.repositories import ISessionRepository

from tests.unit.core.test_doubles import (
    MockBackendService,
    MockCommandService,
    MockLoopDetector,
    MockRateLimiter,
    MockResponseProcessor,
    MockSessionService,
    MockSessionRepository,
)


@pytest.fixture
def services() -> ServiceCollection:
    """Create a service collection with mock services."""
    services = ServiceCollection()
    
    # Register mock services
    services.add_singleton(IBackendService, implementation_factory=lambda _: MockBackendService())  # type: ignore
    services.add_singleton(ISessionService, implementation_factory=lambda _: MockSessionService())  # type: ignore
    services.add_singleton(ICommandService, implementation_factory=lambda _: MockCommandService())  # type: ignore
    services.add_singleton(IRateLimiter, implementation_factory=lambda _: MockRateLimiter())  # type: ignore
    services.add_singleton(ILoopDetector, implementation_factory=lambda _: MockLoopDetector())  # type: ignore
    services.add_singleton(IResponseProcessor, implementation_factory=lambda _: MockResponseProcessor())  # type: ignore
    services.add_singleton(ISessionRepository, implementation_factory=lambda _: MockSessionRepository())  # type: ignore
    
    return services


@pytest.fixture
def service_provider(services: ServiceCollection) -> IServiceProvider:
    """Create a service provider from the service collection."""
    return services.build_provider()