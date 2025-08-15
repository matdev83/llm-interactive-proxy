"""
Pytest configuration file for unit tests.

This file contains shared fixtures and configuration for the unit tests.
"""

import pytest
from src.core.di.container import ServiceCollection
from src.core.interfaces.backend_service import IBackendService
from src.core.interfaces.command_service import ICommandService
from src.core.interfaces.di import IServiceProvider
from src.core.interfaces.loop_detector import ILoopDetector
from src.core.interfaces.rate_limiter import IRateLimiter
from src.core.interfaces.repositories import ISessionRepository
from src.core.interfaces.response_processor import IResponseProcessor
from src.core.interfaces.session_service import ISessionService

from tests.unit.core.test_doubles import (
    MockBackendService,
    MockCommandService,
    MockLoopDetector,
    MockRateLimiter,
    MockResponseProcessor,
    MockSessionRepository,
    MockSessionService,
)


@pytest.fixture
def services() -> ServiceCollection:
    """Fixture for a service collection with mock services registered."""
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
    """Fixture for a service provider with mock services registered."""
    return services.build_service_provider()


@pytest.fixture
def backend_service(service_provider: IServiceProvider) -> MockBackendService:
    """Fixture for a mock backend service."""
    return service_provider.get_required_service(IBackendService)  # type: ignore


@pytest.fixture
def session_service(service_provider: IServiceProvider) -> MockSessionService:
    """Fixture for a mock session service."""
    return service_provider.get_required_service(ISessionService)  # type: ignore


@pytest.fixture
def command_service(service_provider: IServiceProvider) -> MockCommandService:
    """Fixture for a mock command service."""
    return service_provider.get_required_service(ICommandService)  # type: ignore


@pytest.fixture
def rate_limiter(service_provider: IServiceProvider) -> MockRateLimiter:
    """Fixture for a mock rate limiter."""
    return service_provider.get_required_service(IRateLimiter)  # type: ignore


@pytest.fixture
def loop_detector(service_provider: IServiceProvider) -> MockLoopDetector:
    """Fixture for a mock loop detector."""
    return service_provider.get_required_service(ILoopDetector)  # type: ignore


@pytest.fixture
def response_processor(service_provider: IServiceProvider) -> MockResponseProcessor:
    """Fixture for a mock response processor."""
    return service_provider.get_required_service(IResponseProcessor)  # type: ignore


@pytest.fixture
def session_repository(service_provider: IServiceProvider) -> MockSessionRepository:
    """Fixture for a mock session repository."""
    return service_provider.get_required_service(ISessionRepository)  # type: ignore
