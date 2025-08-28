from unittest.mock import Mock

import pytest
from src.core.config.app_config import AppConfig, BackendConfig, BackendSettings
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.configuration.app_identity_config import AppIdentityConfig
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.interfaces.rate_limiter_interface import IRateLimiter, RateLimitInfo
from src.core.services.backend_service import BackendService

from tests.mocks.backend_factory import MockBackendFactory
from tests.unit.core.test_doubles import (
    MockSessionService,  # Import the correct MockSessionService
)
from tests.utils.failover_stub import StubFailoverCoordinator


class MockRateLimiter(IRateLimiter):
    async def check_limit(self, key):
        return RateLimitInfo(is_limited=False, reset_at=0, limit=0, remaining=0)

    async def record_usage(self, key, cost=0):
        pass

    async def reset(self, key):
        pass

    async def set_limit(self, key, limit, time_window):
        pass


@pytest.mark.asyncio
async def test_default_identity_headers():
    """Verify that default identity headers are sent."""
    # Arrange
    app_config = AppConfig(
        identity=AppIdentityConfig(title="Test App", url="https://test.app"),
        backends=BackendSettings(openai=BackendConfig(api_key=["test-key"])),
    )
    factory = MockBackendFactory()
    app_state = Mock(spec=IApplicationState)
    service = BackendService(
        factory=factory,
        rate_limiter=MockRateLimiter(),
        config=app_config,
        session_service=MockSessionService(),
        app_state=app_state,
        failover_coordinator=StubFailoverCoordinator(),
    )
    request = ChatRequest(
        messages=[ChatMessage(role="user", content="Hello")],
        model="openai:gpt-4",
    )

    # Act
    await service.call_completion(request)

    # Assert
    backend = factory.get_backend("openai")
    assert backend.last_request_headers["HTTP-Referer"] == "https://test.app"
    assert backend.last_request_headers["X-Title"] == "Test App"


@pytest.mark.asyncio
async def test_backend_specific_identity_headers():
    """Verify that backend-specific identity headers override defaults."""
    # Arrange
    app_config = AppConfig(
        identity=AppIdentityConfig(title="Default Title", url="https://default.url"),
        backends=BackendSettings(
            openai=BackendConfig(
                api_key=["test-key"],
                identity=AppIdentityConfig(
                    title="OpenAI Title", url="https://openai.url"
                ),
            )
        ),
    )
    factory = MockBackendFactory()
    app_state = Mock(spec=IApplicationState)
    service = BackendService(
        factory=factory,
        rate_limiter=MockRateLimiter(),
        config=app_config,
        session_service=MockSessionService(),
        app_state=app_state,
        failover_coordinator=StubFailoverCoordinator(),
    )
    request = ChatRequest(
        messages=[ChatMessage(role="user", content="Hello")],
        model="openai:gpt-4",
    )

    # Act
    await service.call_completion(request)

    # Assert
    backend = factory.get_backend("openai")
    assert backend.last_request_headers["HTTP-Referer"] == "https://openai.url"
    assert backend.last_request_headers["X-Title"] == "OpenAI Title"
