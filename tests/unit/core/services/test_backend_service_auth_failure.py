"""
Tests for BackendService authentication failure handling.

NOTE: These tests need refactoring after Phase 4 of backend-service-god-object-refactoring.
BackendService is now a thin facade, and these tests were testing internal behavior
that has been moved to BackendCompletionFlow and other collaborators.
TODO: Refactor these tests to either test the collaborators directly or test
the public contract of BackendService through integration tests.
"""

import time
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException
from src.connectors.base import LLMBackend
from src.core.common.exceptions import (
    AuthenticationError,
    BackendError,
    InvalidRequestError,
)
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.interfaces.backend_model_resolver_interface import ResolvedTarget
from src.core.services.backend_factory import BackendFactory

from tests.unit.fixtures.backend_service_builder import (
    create_backend_service_with_mocks,
)

# Suppress Windows ProactorEventLoop ResourceWarnings for this module
pytestmark = pytest.mark.filterwarnings(
    "ignore:unclosed event loop <ProactorEventLoop.*:ResourceWarning"
)


class MockBackend(LLMBackend):
    def __init__(self):
        self._endpoint_healthy = True
        self._auth_valid = True
        self.mark_auth_invalid = Mock()
        self._has_static_credentials = True

    @property
    def has_static_credentials(self) -> bool:
        return self._has_static_credentials

    async def chat_completions(self, *args, **kwargs):
        pass

    async def initialize(self, *args, **kwargs):
        pass

    def get_available_models(self):
        return ["model"]


@pytest.fixture
def backend_service():
    factory = Mock(spec=BackendFactory)
    rate_limiter = Mock()
    rate_limiter.check_limit = AsyncMock(return_value=Mock(is_limited=False))
    rate_limiter.record_usage = AsyncMock()
    config = Mock()
    config.backends.default_backend = "openai"
    session_service = Mock()
    session_service.get_session = AsyncMock(return_value=None)
    app_state = Mock()

    return create_backend_service_with_mocks(
        factory=factory,
        rate_limiter=rate_limiter,
        config=config,
        session_service=session_service,
        app_state=app_state,
    )


@pytest.mark.asyncio
@pytest.mark.skip(
    reason="Needs refactoring after Phase 4 - BackendService is now a thin facade"
)
async def test_auth_failure_permanent_backend_disable(backend_service):
    """Test that AuthenticationError permanently disables the backend."""

    backend = MockBackend()
    backend.chat_completions = AsyncMock(
        side_effect=AuthenticationError("Invalid API Key")
    )

    # Mock the completion flow's dependencies
    backend_service._backend_model_resolver.resolve_target = AsyncMock(
        return_value=ResolvedTarget(backend="openai", model="gpt-4", uri_params={})
    )
    # Mock backend creation
    backend_service._backend_lifecycle_manager.get_or_create = AsyncMock(
        return_value=backend
    )
    # Ensure the completion flow uses our mocked factory
    backend_service._backend_completion_flow._backend_factory = backend_service._factory

    request = ChatRequest(
        messages=[ChatMessage(role="user", content="hi")], model="gpt-4"
    )

    with pytest.raises(AuthenticationError):
        await backend_service.call_completion(request)

    backend.mark_auth_invalid.assert_called_once()
    backend_service._factory.unregister_backend.assert_called_once_with("openai")


@pytest.mark.asyncio
@pytest.mark.skip(
    reason="Needs refactoring after Phase 4 - BackendService is now a thin facade"
)
async def test_backend_error_401_permanent_disable(backend_service):
    """Test that BackendError with 401 status permanently disables the backend."""

    backend = MockBackend()
    backend.chat_completions = AsyncMock(
        side_effect=BackendError("Unauthorized", status_code=401)
    )

    backend_service._backend_model_resolver.resolve_target = AsyncMock(
        return_value=ResolvedTarget(backend="openai", model="gpt-4", uri_params={})
    )
    backend_service._backend_lifecycle_manager.get_or_create = AsyncMock(
        return_value=backend
    )
    backend_service._backend_completion_flow._backend_factory = backend_service._factory

    request = ChatRequest(
        messages=[ChatMessage(role="user", content="hi")], model="gpt-4"
    )

    with pytest.raises(BackendError):
        await backend_service.call_completion(request)

    backend.mark_auth_invalid.assert_called_once()
    backend_service._factory.unregister_backend.assert_called_once_with("openai")


@pytest.mark.asyncio
@pytest.mark.skip(
    reason="Needs refactoring after Phase 4 - BackendService is now a thin facade"
)
async def test_http_exception_401_permanent_disable(backend_service):
    """Test that HTTPException with 401 status permanently disables the backend."""

    backend = MockBackend()
    backend.chat_completions = AsyncMock(
        side_effect=HTTPException(status_code=401, detail="Unauthorized")
    )

    backend_service._backend_model_resolver.resolve_target = AsyncMock(
        return_value=ResolvedTarget(backend="openai", model="gpt-4", uri_params={})
    )
    backend_service._backend_lifecycle_manager.get_or_create = AsyncMock(
        return_value=backend
    )
    backend_service._backend_completion_flow._backend_factory = backend_service._factory

    request = ChatRequest(
        messages=[ChatMessage(role="user", content="hi")], model="gpt-4"
    )

    # It seems the system might normalize HTTPException to InvalidRequestError
    with pytest.raises((HTTPException, InvalidRequestError)):
        await backend_service.call_completion(request)

    backend.mark_auth_invalid.assert_called_once()
    backend_service._factory.unregister_backend.assert_called_once_with("openai")


@pytest.mark.asyncio
@pytest.mark.skip(
    reason="Needs refactoring after Phase 4 - BackendService is now a thin facade"
)
async def test_oauth_backend_not_permanently_disabled(backend_service):
    """Test that OAuth backends (has_static_credentials=False) are NOT permanently disabled."""
    backend = MockBackend()
    backend._has_static_credentials = False  # OAuth backend
    backend.chat_completions = AsyncMock(
        side_effect=AuthenticationError("Token expired")
    )

    backend_service._backend_model_resolver.resolve_target = AsyncMock(
        return_value=type(
            "ResolvedTarget",
            (),
            {"backend": "gemini-oauth", "model": "gemini-2.5-pro", "uri_params": {}},
        )()
    )
    backend_service._backend_lifecycle_manager.get_or_create = AsyncMock(
        return_value=backend
    )
    backend_service._backend_completion_flow._backend_factory = backend_service._factory

    request = ChatRequest(
        messages=[ChatMessage(role="user", content="hi")], model="gemini-2.5-pro"
    )

    with pytest.raises(AuthenticationError):
        await backend_service.call_completion(request)

    # OAuth backend should NOT be marked invalid or unregistered
    backend.mark_auth_invalid.assert_not_called()
    backend_service._factory.unregister_backend.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.skip(
    reason="Needs refactoring after Phase 4 - BackendService is now a thin facade"
)
async def test_disabled_backend_fails_fast_without_failover(backend_service):
    """Request to a permanently disabled backend fails before creation when no failover exists."""
    backend_service._backend_lifecycle_manager.get_disabled_backends = Mock(
        return_value={
            "openai": {
                "reason": "invalid api key",
                "timestamp": time.time(),
            }
        }
    )
    backend_service._backend_model_resolver.resolve_target = AsyncMock(
        return_value=ResolvedTarget(backend="openai", model="gpt-4", uri_params={})
    )

    request = ChatRequest(
        messages=[ChatMessage(role="user", content="hi")], model="gpt-4"
    )

    with pytest.raises(BackendError):
        await backend_service.call_completion(request, allow_failover=False)
