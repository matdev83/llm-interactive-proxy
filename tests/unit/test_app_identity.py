from unittest.mock import AsyncMock, Mock

import pytest
from src.core.config.app_config import AppConfig, BackendConfig, BackendSettings
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.configuration.app_identity_config import AppIdentityConfig
from src.core.domain.configuration.header_config import HeaderConfig
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.interfaces.backend_lifecycle_manager_interface import (
    IBackendLifecycleManager,
)
from src.core.interfaces.backend_model_resolver_interface import (
    IBackendModelResolver,
    ResolvedTarget,
)
from src.core.interfaces.rate_limiter_interface import IRateLimiter, RateLimitInfo

from tests.mocks.backend_factory import MockBackendFactory
from tests.unit.core.test_doubles import (
    MockSessionService,  # Import the correct MockSessionService
)
from tests.unit.fixtures.backend_service_builder import (
    create_backend_service_with_mocks,
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

    async def apply_cooldown(self, key, cooldown_seconds):
        pass


def create_mock_lifecycle_manager_with_factory(factory: MockBackendFactory):
    """Create a mock lifecycle manager that properly tracks backends via factory."""
    mock_lifecycle = Mock(spec=IBackendLifecycleManager)
    mock_lifecycle.get_disabled_backends = Mock(return_value={})

    async def get_or_create_impl(backend_type, *args, **kwargs):
        """Create backend via factory for tracking."""
        backend = await factory.ensure_backend(backend_type, factory._config, None)
        return backend

    mock_lifecycle.get_or_create = AsyncMock(side_effect=get_or_create_impl)
    return mock_lifecycle


@pytest.mark.asyncio
async def test_default_identity_headers():
    """Verify that default identity headers are sent."""
    # Arrange
    app_config = AppConfig(
        identity=AppIdentityConfig(
            title=HeaderConfig(default_value="Test App", passthrough_name="x-title"),
            url=HeaderConfig(
                default_value="https://test.app", passthrough_name="http-referer"
            ),
        ),
        backends=BackendSettings(openai=BackendConfig(api_key=["test-key"])),
    )
    factory = MockBackendFactory()
    factory._config = app_config  # Set config for factory
    app_state = Mock(spec=IApplicationState)

    # Create a backend_config_provider that returns None (so it falls back to app_config.backends.get)
    from src.core.interfaces.backend_config_provider_interface import (
        IBackendConfigProvider,
    )

    backend_config_provider = Mock(spec=IBackendConfigProvider)
    backend_config_provider.get_backend_config = Mock(return_value=None)

    # Mock BackendModelResolver to return proper resolved target
    mock_resolver = Mock(spec=IBackendModelResolver)
    mock_resolver.resolve_target = AsyncMock(
        return_value=ResolvedTarget(
            backend="openai",
            model="gpt-4",
            uri_params={},
        )
    )
    mock_resolver.synchronize_request_with_target = Mock(
        side_effect=lambda request, _resolved: request
    )

    # Create lifecycle manager that tracks backends via factory
    mock_lifecycle = create_mock_lifecycle_manager_with_factory(factory)

    service = create_backend_service_with_mocks(
        factory=factory,
        rate_limiter=MockRateLimiter(),
        config=app_config,
        session_service=MockSessionService(),
        app_state=app_state,
        failover_coordinator=StubFailoverCoordinator(),
        backend_config_provider=backend_config_provider,
        backend_model_resolver=mock_resolver,
        backend_lifecycle_manager=mock_lifecycle,
        use_real_completion_flow=True,
    )
    request = ChatRequest(
        messages=[ChatMessage(role="user", content="Hello")],
        model="openai:gpt-4",
    )

    # Act
    await service.call_completion(request)

    # Assert
    backend = factory.get_backend("openai")
    # Get the identity config to resolve headers
    identity_config = app_config.identity
    resolved_headers = identity_config.get_resolved_headers(None)
    assert (
        backend.last_request_headers["HTTP-Referer"] == resolved_headers["HTTP-Referer"]
    )
    assert backend.last_request_headers["X-Title"] == resolved_headers["X-Title"]


@pytest.mark.asyncio
async def test_backend_specific_identity_headers():
    """Verify that backend-specific identity headers override defaults."""
    # Arrange
    openai_backend_config = BackendConfig(
        api_key=["test-key"],
        identity=AppIdentityConfig(
            title=HeaderConfig(
                default_value="OpenAI Title", passthrough_name="x-title"
            ),
            url=HeaderConfig(
                default_value="https://openai.url",
                passthrough_name="http-referer",
            ),
        ),
    )
    app_config = AppConfig(
        identity=AppIdentityConfig(
            title=HeaderConfig(
                default_value="Default Title", passthrough_name="x-title"
            ),
            url=HeaderConfig(
                default_value="https://default.url", passthrough_name="http-referer"
            ),
        ),
        backends=BackendSettings(openai=openai_backend_config),
    )
    factory = MockBackendFactory()
    factory._config = app_config  # Set config for factory
    app_state = Mock(spec=IApplicationState)

    # Create a backend_config_provider that returns the backend config (so it uses provider identity)
    from src.core.interfaces.backend_config_provider_interface import (
        IBackendConfigProvider,
    )

    backend_config_provider = Mock(spec=IBackendConfigProvider)
    backend_config_provider.get_backend_config = Mock(
        return_value=openai_backend_config
    )

    # Mock BackendModelResolver to return proper resolved target
    mock_resolver = Mock(spec=IBackendModelResolver)
    mock_resolver.resolve_target = AsyncMock(
        return_value=ResolvedTarget(
            backend="openai",
            model="gpt-4",
            uri_params={},
        )
    )
    mock_resolver.synchronize_request_with_target = Mock(
        side_effect=lambda request, _resolved: request
    )

    # Create lifecycle manager that tracks backends via factory
    mock_lifecycle = create_mock_lifecycle_manager_with_factory(factory)

    service = create_backend_service_with_mocks(
        factory=factory,
        rate_limiter=MockRateLimiter(),
        config=app_config,
        session_service=MockSessionService(),
        app_state=app_state,
        failover_coordinator=StubFailoverCoordinator(),
        backend_config_provider=backend_config_provider,
        backend_model_resolver=mock_resolver,
        backend_lifecycle_manager=mock_lifecycle,
        use_real_completion_flow=True,
    )
    request = ChatRequest(
        messages=[ChatMessage(role="user", content="Hello")],
        model="openai:gpt-4",
    )

    # Act
    await service.call_completion(request)

    # Assert
    backend = factory.get_backend("openai")
    # Get the backend-specific identity config to resolve headers
    backend_identity_config = app_config.backends.openai.identity
    resolved_headers = backend_identity_config.get_resolved_headers(None)
    assert (
        backend.last_request_headers["HTTP-Referer"] == resolved_headers["HTTP-Referer"]
    )
    assert backend.last_request_headers["X-Title"] == resolved_headers["X-Title"]
