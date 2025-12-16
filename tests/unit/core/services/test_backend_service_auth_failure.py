"""Tests for BackendCompletionFlow authentication failure handling."""

import time
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from fastapi import HTTPException
from src.connectors.base import LLMBackend
from src.core.common.exceptions import (
    AuthenticationError,
    BackendError,
)
from src.core.config.app_config import AppConfig
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.interfaces.backend_model_resolver_interface import ResolvedTarget

from tests.unit.core.services.backend_flow_test_helper import (
    create_test_backend_completion_flow,
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
def flow_fixture():
    backend_lifecycle_manager = MagicMock()
    backend_lifecycle_manager.get_disabled_backends.return_value = {}
    backend_lifecycle_manager.get_active_backends.return_value = {}

    backend_factory = MagicMock()

    config = MagicMock(spec=AppConfig)
    config.backends = MagicMock()
    config.backends.get.return_value = None
    config.identity = None

    deps = {
        "backend_model_resolver": MagicMock(),
        "stream_session_id_resolver": MagicMock(),
        "failover_planner": MagicMock(),
        "session_service": MagicMock(),
        "backend_lifecycle_manager": backend_lifecycle_manager,
        "backend_config_service": MagicMock(),
        "reasoning_config_applicator": MagicMock(),
        "uri_parameter_applicator": MagicMock(),
        "stream_formatting_service": MagicMock(),
        "usage_tracking_wrapper": MagicMock(),
        "exception_normalizer": MagicMock(),
        "planning_phase_manager": MagicMock(),
        "backend_factory": backend_factory,
        "config": config,
        "app_state": MagicMock(),
        "failover_coordinator": MagicMock(),
        "failure_handling_strategy": None,
    }

    # Defaults
    deps["backend_model_resolver"].resolve_target = AsyncMock(
        return_value=ResolvedTarget(backend="openai", model="gpt-4", uri_params={})
    )
    deps["backend_model_resolver"].synchronize_request_with_target = Mock(
        side_effect=lambda r, t: r
    )
    deps["reasoning_config_applicator"].apply = Mock(side_effect=lambda r, s: r)
    deps["uri_parameter_applicator"].apply = Mock(side_effect=lambda r, u, b, s: r)

    def normalize_side_effect(exc, backend_type):
        return exc

    deps["exception_normalizer"].normalize = Mock(side_effect=normalize_side_effect)

    flow = create_test_backend_completion_flow(deps)
    return flow, deps


@pytest.mark.asyncio
async def test_auth_failure_permanent_backend_disable(flow_fixture):
    """Test that AuthenticationError permanently disables the backend."""
    flow, deps = flow_fixture
    backend = MockBackend()
    backend.chat_completions = AsyncMock(
        side_effect=AuthenticationError("Invalid API Key")
    )

    deps["backend_lifecycle_manager"].get_or_create = AsyncMock(return_value=backend)

    request = ChatRequest(
        messages=[ChatMessage(role="user", content="hi")], model="gpt-4"
    )

    with pytest.raises(AuthenticationError):
        await flow.call_completion(request)

    backend.mark_auth_invalid.assert_called_once()
    deps["backend_factory"].unregister_backend.assert_called_once_with("openai")
    deps["backend_lifecycle_manager"].discard.assert_called_once()


@pytest.mark.asyncio
async def test_backend_error_401_permanent_disable(flow_fixture):
    """Test that BackendError with 401 status permanently disables the backend."""
    flow, deps = flow_fixture
    backend = MockBackend()
    backend.chat_completions = AsyncMock(
        side_effect=BackendError("Unauthorized", status_code=401)
    )

    deps["backend_lifecycle_manager"].get_or_create = AsyncMock(return_value=backend)

    request = ChatRequest(
        messages=[ChatMessage(role="user", content="hi")], model="gpt-4"
    )

    with pytest.raises(BackendError):
        await flow.call_completion(request)

    backend.mark_auth_invalid.assert_called_once()
    deps["backend_factory"].unregister_backend.assert_called_once_with("openai")
    deps["backend_lifecycle_manager"].discard.assert_called_once()


@pytest.mark.asyncio
async def test_http_exception_401_permanent_disable(flow_fixture):
    """Test that HTTPException with 401 status permanently disables the backend."""
    from src.core.common.exceptions import InvalidRequestError

    flow, deps = flow_fixture
    backend = MockBackend()
    backend.chat_completions = AsyncMock(
        side_effect=HTTPException(status_code=401, detail="Unauthorized")
    )

    deps["backend_lifecycle_manager"].get_or_create = AsyncMock(return_value=backend)

    request = ChatRequest(
        messages=[ChatMessage(role="user", content="hi")], model="gpt-4"
    )

    # The mock normalizer returns HTTPException as-is, but HTTPException is not an LLMProxyError,
    # so it falls through to outer handler which normalizes it again using the real normalizer.
    # The real normalizer converts HTTPException(401) to InvalidRequestError(status_code=401),
    # which IS an LLMProxyError, so it should be raised.
    # Accept InvalidRequestError since that's what the real normalizer produces.
    with pytest.raises(InvalidRequestError) as exc_info:
        await flow.call_completion(request)

    # Ensure status_code is 401
    assert exc_info.value.status_code == 401

    backend.mark_auth_invalid.assert_called_once()
    deps["backend_factory"].unregister_backend.assert_called_once_with("openai")
    deps["backend_lifecycle_manager"].discard.assert_called_once()


@pytest.mark.asyncio
async def test_oauth_backend_not_permanently_disabled(flow_fixture):
    """Test that OAuth backends (has_static_credentials=False) are NOT permanently disabled."""
    flow, deps = flow_fixture
    backend = MockBackend()
    backend._has_static_credentials = False  # OAuth backend
    backend.chat_completions = AsyncMock(
        side_effect=AuthenticationError("Token expired")
    )

    deps["backend_model_resolver"].resolve_target = AsyncMock(
        return_value=ResolvedTarget(
            backend="gemini-oauth", model="gemini-2.5-pro", uri_params={}
        )
    )
    deps["backend_lifecycle_manager"].get_or_create = AsyncMock(return_value=backend)

    request = ChatRequest(
        messages=[ChatMessage(role="user", content="hi")], model="gemini-2.5-pro"
    )

    with pytest.raises(AuthenticationError):
        await flow.call_completion(request)

    # OAuth backend should NOT be marked invalid or unregistered
    backend.mark_auth_invalid.assert_not_called()
    deps["backend_factory"].unregister_backend.assert_not_called()
    deps["backend_lifecycle_manager"].discard.assert_not_called()


@pytest.mark.asyncio
async def test_disabled_backend_fails_fast_without_failover(flow_fixture):
    """Request to a permanently disabled backend fails before creation when no failover exists."""
    flow, deps = flow_fixture

    deps["backend_lifecycle_manager"].get_disabled_backends.return_value = {
        "openai": {
            "reason": "invalid api key",
            "timestamp": time.time(),
        }
    }

    request = ChatRequest(
        messages=[ChatMessage(role="user", content="hi")], model="gpt-4"
    )

    with pytest.raises(BackendError) as exc_info:
        await flow.call_completion(request, allow_failover=False)

    assert "permanently disabled" in str(exc_info.value)
    # Ensure get_or_create was NOT called
    deps["backend_lifecycle_manager"].get_or_create.assert_not_called()
