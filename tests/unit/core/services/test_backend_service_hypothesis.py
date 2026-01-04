"""
Additional tests for the BackendService using Hypothesis for property-based testing.
"""

from typing import Any, cast
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

pytest.importorskip("hypothesis")

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from src.connectors.base import LLMBackend
from src.core.common.exceptions import BackendError, RateLimitExceededError
from src.core.domain.backend_type import BackendType
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.responses import ResponseEnvelope
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.interfaces.session_service_interface import ISessionService
from src.core.services.backend_factory import BackendFactory

from tests.unit.fixtures.backend_service_builder import (
    create_backend_service_with_mocks,
)


class MockBackend(LLMBackend):
    """Mock implementation of LLMBackend for testing."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        available_models: list[str] | None = None,
    ) -> None:
        # Initialize base class to ensure health attributes are present
        super().__init__(config=Mock())
        self.client = client
        self.available_models = available_models or ["model1", "model2"]
        self.initialize_called = False
        self.chat_completions_called = False
        self.chat_completions_mock = AsyncMock()

    async def initialize(self, **kwargs: Any) -> None:
        self.initialize_called = True
        self.initialize_kwargs = kwargs

    def get_available_models(self) -> list[str]:
        return self.available_models

    async def chat_completions(
        self,
        request_data: Any,
        processed_messages: list[Any],
        effective_model: str,
        identity: Any | None = None,
        **kwargs: Any,
    ) -> ResponseEnvelope:
        self.chat_completions_called = True
        self.chat_completions_args = {
            "request_data": request_data,
            "processed_messages": processed_messages,
            "effective_model": effective_model,
            "identity": identity,
            "kwargs": kwargs,
        }
        return cast(ResponseEnvelope, await self.chat_completions_mock())


@pytest.fixture(scope="session")
def http_client():
    """Session-scoped HTTP client for testing."""
    return httpx.AsyncClient()


@pytest.fixture(scope="session")
def app_config():
    """Session-scoped app config for testing."""
    from src.core.config.app_config import AppConfig

    return AppConfig()


@pytest.fixture(scope="session")
def backend_registry(app_config):
    """Session-scoped backend registry."""
    from src.core.services.backend_registry import BackendRegistry

    return BackendRegistry()


@pytest.fixture(scope="session")
def translation_service():
    """Session-scoped translation service."""
    from src.core.services.translation_service import TranslationService

    return TranslationService()


@pytest.fixture(scope="session")
def backend_factory(http_client, backend_registry, app_config, translation_service):
    """Session-scoped backend factory."""
    return BackendFactory(
        http_client, backend_registry, app_config, translation_service
    )


@pytest.fixture(scope="session")
def mock_rate_limiter():
    """Session-scoped mock rate limiter."""
    rate_limiter = Mock()
    rate_limiter.check_limit = AsyncMock(return_value=Mock(is_limited=False))
    rate_limiter.record_usage = AsyncMock()
    return rate_limiter


@pytest.fixture(scope="session")
def mock_app_config():
    """Session-scoped mock config."""
    mock_config = Mock()
    mock_config.get.return_value = None
    mock_config.backends = Mock()
    mock_config.backends.default_backend = "openai"
    return mock_config


@pytest.fixture(scope="session")
def mock_session_service():
    """Session-scoped mock session service."""
    return Mock(spec=ISessionService)


@pytest.fixture(scope="session")
def mock_app_state():
    """Session-scoped mock app state."""
    return Mock(spec=IApplicationState)


@pytest.fixture(scope="session")
def stub_failover_coordinator():
    """Session-scoped stub failover coordinator."""
    from tests.utils.failover_stub import StubFailoverCoordinator

    return StubFailoverCoordinator()


def create_backend_service(
    backend_factory,
    mock_rate_limiter,
    mock_app_config,
    mock_session_service,
    mock_app_state,
    stub_failover_coordinator,
):
    """Create a BackendService instance for testing using session-scoped fixtures."""
    # Just use the helper with minimal mocks - BackendService is now a thin facade
    return create_backend_service_with_mocks(
        factory=backend_factory,
        rate_limiter=mock_rate_limiter,
        config=mock_app_config,
        session_service=mock_session_service,
        app_state=mock_app_state,
        failover_coordinator=stub_failover_coordinator,
        use_real_completion_flow=True,
    )


# NOTE: These tests need refactoring after Phase 4 of backend-service-god-object-refactoring
# BackendService is now a thin facade, and these tests were testing internal behavior
# that has been moved to BackendCompletionFlow and other collaborators.
# TODO: Refactor these tests to either test BackendCompletionFlow directly or test
# the public contract of BackendService through integration tests.


class TestBackendServiceHypothesis:
    """Hypothesis-based tests for the BackendService class."""

    @given(
        model_name=st.from_regex(r"\A[a-zA-Z0-9]{1,20}\Z"),
        message_content=st.text(min_size=1, max_size=50),
    )
    @settings(
        suppress_health_check=[
            HealthCheck.function_scoped_fixture,
            HealthCheck.too_slow,
        ],
        max_examples=3,
        deadline=500,
    )
    @pytest.mark.asyncio
    async def test_call_completion_with_various_models_and_messages(
        self,
        model_name,
        message_content,
        backend_factory,
        mock_rate_limiter,
        mock_app_config,
        mock_session_service,
        mock_app_state,
        stub_failover_coordinator,
    ):
        """Property-based test for calling completions with various models and messages."""
        # Arrange
        service = create_backend_service(
            backend_factory,
            mock_rate_limiter,
            mock_app_config,
            mock_session_service,
            mock_app_state,
            stub_failover_coordinator,
        )
        mock_backend = MockBackend(backend_factory._client)
        mock_backend.chat_completions_mock.return_value = ResponseEnvelope(
            content={
                "id": "resp-123",
                "created": 123,
                "model": model_name,
                "choices": [],
            },
            headers={},
        )

        chat_request = ChatRequest(
            messages=[ChatMessage(role="user", content=message_content)],
            model=model_name,
            extra_body={"backend_type": BackendType.OPENAI},
        )

        # Mock target resolution at the completion-flow layer (BackendService delegates)
        from src.core.interfaces.backend_model_resolver_interface import ResolvedTarget

        service._backend_completion_flow._request_preparer._backend_model_resolver.resolve_target = AsyncMock(
            return_value=ResolvedTarget(
                backend="openai",
                model=model_name,
                uri_params={},
            )
        )

        with patch.object(
            service._backend_lifecycle_manager,
            "get_or_create",
            return_value=mock_backend,
        ):
            # Act
            response = await service.call_completion(chat_request)

            # Assert
            assert mock_backend.chat_completions_called
            assert response.content["model"] == model_name  # type: ignore
            assert "resp-123" in str(response.content)

    @given(
        backend_type=st.sampled_from(
            [BackendType.OPENAI, BackendType.ANTHROPIC, BackendType.GEMINI]
        ),
        model_name=st.from_regex(r"\A[a-zA-Z0-9]{1,20}\Z"),
    )
    @settings(
        suppress_health_check=[
            HealthCheck.function_scoped_fixture,
            HealthCheck.too_slow,
        ],
        max_examples=3,
        deadline=500,
    )
    @pytest.mark.asyncio
    async def test_validate_backend_and_model_with_various_backends(
        self,
        backend_type,
        model_name,
        backend_factory,
        mock_rate_limiter,
        mock_app_config,
        mock_session_service,
        mock_app_state,
        stub_failover_coordinator,
    ):
        """Property-based test for validating various backend and model combinations."""
        # Arrange
        service = create_backend_service(
            backend_factory,
            mock_rate_limiter,
            mock_app_config,
            mock_session_service,
            mock_app_state,
            stub_failover_coordinator,
        )
        mock_backend = MockBackend(
            backend_factory._client, available_models=[model_name, "other-model"]
        )

        with patch.object(
            service._backend_lifecycle_manager,
            "get_or_create",
            return_value=mock_backend,
        ):
            # Act
            result = await service.validate_backend_and_model(backend_type, model_name)

            # Assert
            assert result.is_valid is True
            assert result.error_message is None

    @pytest.mark.asyncio
    async def test_call_completion_rate_limited_with_hypothesis(
        self,
        backend_factory,
        mock_rate_limiter,
        mock_app_config,
        mock_session_service,
        mock_app_state,
        stub_failover_coordinator,
    ):
        """Test rate limiting via ResilienceCoordinator with various configurations.

        Note: With the new architecture, rate limiting is handled by the
        ResilienceCoordinator, not the legacy rate limiter.
        """
        from src.core.interfaces.resilience_interface import ResilienceDecision

        # Arrange
        service = create_backend_service(
            backend_factory,
            mock_rate_limiter,
            mock_app_config,
            mock_session_service,
            mock_app_state,
            stub_failover_coordinator,
        )
        chat_request = ChatRequest(
            messages=[ChatMessage(role="user", content="Hello")],
            model="test-model",
            extra_body={"backend_type": BackendType.OPENAI},
        )

        # Configure the backend model resolver to return expected backend/model
        from src.core.interfaces.backend_model_resolver_interface import ResolvedTarget

        service._backend_completion_flow._request_preparer._backend_model_resolver.resolve_target = AsyncMock(
            return_value=ResolvedTarget(
                backend="openai",
                model="test-model",
                uri_params={},
            )
        )

        # Test with different cooldown configurations
        for cooldown in [60.0, 120.0, 300.0]:
            # Create a mock ResilienceCoordinator that rejects requests
            mock_resilience = Mock()
            mock_decision = Mock(spec=ResilienceDecision)
            # Make should_proceed() return False when called
            mock_decision.should_proceed = Mock(return_value=False)
            mock_decision.reason = f"Rate limit exceeded, cooldown {cooldown}s"
            mock_decision.cooldown_remaining = cooldown
            mock_resilience.check_availability.return_value = mock_decision

            # Set resilience on the BackendCompletionFlow, not the BackendService
            service._backend_completion_flow._availability_checker._resilience = (
                mock_resilience
            )

            with pytest.raises(RateLimitExceededError):
                await service.call_completion(chat_request)

    @pytest.mark.asyncio
    async def test_call_completion_backend_error_with_hypothesis(
        self,
        backend_factory,
        mock_rate_limiter,
        mock_app_config,
        mock_session_service,
        mock_app_state,
        stub_failover_coordinator,
    ):
        """Test backend error handling with various error messages."""
        # Arrange
        service = create_backend_service(
            backend_factory,
            mock_rate_limiter,
            mock_app_config,
            mock_session_service,
            mock_app_state,
            stub_failover_coordinator,
        )
        client = backend_factory._client

        # Test with different error messages
        error_messages = [
            "API error",
            "Network timeout",
            "Invalid API key",
            "Rate limit exceeded on backend",
        ]

        for error_msg in error_messages:
            # Create a new mock for each iteration to avoid shared state
            mock_backend = MockBackend(client)
            # Ensure attributes needed for validation reporting
            mock_backend._endpoint_healthy = True
            mock_backend._last_health_change_reason = None

            # Use BackendError instead of generic Exception to match what the backend would throw
            mock_backend.chat_completions_mock.side_effect = BackendError(
                message=error_msg, backend_name="test-backend"
            )
            chat_request = ChatRequest(
                messages=[ChatMessage(role="user", content="Hello")],
                model="test-model",
                extra_body={"backend_type": BackendType.OPENAI},
            )

            # Mock target resolution at the completion-flow layer (BackendService delegates)
            from src.core.interfaces.backend_model_resolver_interface import (
                ResolvedTarget,
            )

            service._backend_completion_flow._request_preparer._backend_model_resolver.resolve_target = AsyncMock(
                return_value=ResolvedTarget(
                    backend="openai",
                    model="test-model",
                    uri_params={},
                )
            )

            with patch.object(
                service._backend_lifecycle_manager,
                "get_or_create",
                return_value=mock_backend,
            ):
                # Act & Assert
                # We need to explicitly set allow_failover=False to prevent the service from
                # attempting to use fallback backends, which would catch the exception
                with pytest.raises(BackendError) as exc_info:
                    await service.call_completion(chat_request, allow_failover=False)

                # Verify the error includes the original message
                assert error_msg in str(exc_info.value)
