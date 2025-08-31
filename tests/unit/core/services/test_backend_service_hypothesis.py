"""
Additional tests for the BackendService using Hypothesis for property-based testing.
"""

from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest
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
from src.core.services.backend_service import BackendService


class MockBackend(LLMBackend):
    """Mock implementation of LLMBackend for testing."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        available_models: list[str] | None = None,
    ) -> None:
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
        request_data: ChatRequest,
        processed_messages: list,
        effective_model: str,
        **kwargs: Any,
    ) -> ResponseEnvelope | Any:
        self.chat_completions_called = True
        self.chat_completions_args = {
            "request_data": request_data,
            "processed_messages": processed_messages,
            "effective_model": effective_model,
            "kwargs": kwargs,
        }
        return await self.chat_completions_mock()


def create_backend_service():
    """Create a BackendService instance for testing."""
    client = httpx.AsyncClient()
    from src.core.config.app_config import AppConfig
    from src.core.services.backend_registry import BackendRegistry

    registry = BackendRegistry()
    from src.core.services.translation_service import TranslationService

    config = AppConfig()
    factory = BackendFactory(client, registry, config, TranslationService())
    rate_limiter = Mock()
    rate_limiter.check_limit = AsyncMock(return_value=Mock(is_limited=False))
    rate_limiter.record_usage = AsyncMock()

    mock_config = Mock()
    mock_config.get.return_value = None
    mock_config.backends = Mock()
    mock_config.backends.default_backend = "openai"

    session_service = Mock(spec=ISessionService)
    app_state = Mock(spec=IApplicationState)

    # Create concrete implementation
    class ConcreteBackendService(BackendService):
        async def chat_completions(
            self, request: ChatRequest, **kwargs: Any
        ) -> ResponseEnvelope:
            stream = kwargs.get("stream", False)
            from src.core.domain.responses import StreamingResponseEnvelope

            result = await self.call_completion(request, stream=stream)
            if isinstance(result, StreamingResponseEnvelope):
                async for _ in result.content:
                    pass
                return ResponseEnvelope(content={}, headers={}, usage=None)
            return result

    from tests.utils.failover_stub import StubFailoverCoordinator

    return ConcreteBackendService(
        factory,
        rate_limiter,
        mock_config,
        session_service,
        app_state,
        failover_coordinator=StubFailoverCoordinator(),
    )


class TestBackendServiceHypothesis:
    """Hypothesis-based tests for the BackendService class."""

    @given(
        model_name=st.text(min_size=1, max_size=50).filter(lambda x: x.isalnum()),
        message_content=st.text(min_size=1, max_size=100),
    )
    @settings(
        suppress_health_check=[HealthCheck.function_scoped_fixture], max_examples=5
    )
    @pytest.mark.asyncio
    async def test_call_completion_with_various_models_and_messages(
        self, model_name, message_content
    ):
        """Property-based test for calling completions with various models and messages."""
        # Arrange
        service = create_backend_service()
        client = httpx.AsyncClient()
        mock_backend = MockBackend(client)
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

        with patch.object(service, "_get_or_create_backend", return_value=mock_backend):
            # Act
            response = await service.call_completion(chat_request)

            # Assert
            assert mock_backend.chat_completions_called
            assert response.content["model"] == model_name
            assert "resp-123" in str(response.content)

    @given(
        backend_type=st.sampled_from(
            [BackendType.OPENAI, BackendType.ANTHROPIC, BackendType.GEMINI]
        ),
        model_name=st.text(min_size=1, max_size=50).filter(lambda x: x.isalnum()),
    )
    @settings(
        suppress_health_check=[HealthCheck.function_scoped_fixture], max_examples=5
    )
    @pytest.mark.asyncio
    async def test_validate_backend_and_model_with_various_backends(
        self, backend_type, model_name
    ):
        """Property-based test for validating various backend and model combinations."""
        # Arrange
        service = create_backend_service()
        client = httpx.AsyncClient()
        mock_backend = MockBackend(client, available_models=[model_name, "other-model"])

        with patch.object(service, "_get_or_create_backend", return_value=mock_backend):
            # Act
            valid, error = await service.validate_backend_and_model(
                backend_type, model_name
            )

            # Assert
            assert valid is True
            assert error is None

    @pytest.mark.asyncio
    async def test_call_completion_rate_limited_with_hypothesis(self):
        """Test rate limiting with various rate limit configurations."""
        # Arrange
        service = create_backend_service()
        chat_request = ChatRequest(
            messages=[ChatMessage(role="user", content="Hello")],
            model="test-model",
            extra_body={"backend_type": BackendType.OPENAI},
        )

        # Test with different rate limit configurations
        for remaining in [0, -1, -5]:
            with (
                patch.object(
                    service._rate_limiter,
                    "check_limit",
                    AsyncMock(
                        return_value=Mock(
                            is_limited=True, remaining=remaining, reset_at=123, limit=10
                        )
                    ),
                ),
                pytest.raises(RateLimitExceededError),
            ):
                # Act & Assert
                await service.call_completion(chat_request)

    @pytest.mark.asyncio
    async def test_call_completion_backend_error_with_hypothesis(self):
        """Test backend error handling with various error messages."""
        # Arrange
        service = create_backend_service()
        client = httpx.AsyncClient()

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
            # Use BackendError instead of generic Exception to match what the backend would throw
            mock_backend.chat_completions_mock.side_effect = BackendError(
                message=error_msg, backend_name="test-backend"
            )
            chat_request = ChatRequest(
                messages=[ChatMessage(role="user", content="Hello")],
                model="test-model",
                extra_body={"backend_type": BackendType.OPENAI},
            )

            with patch.object(
                service, "_get_or_create_backend", return_value=mock_backend
            ):
                # Act & Assert
                # We need to explicitly set allow_failover=False to prevent the service from
                # attempting to use fallback backends, which would catch the exception
                with pytest.raises(BackendError) as exc_info:
                    await service.call_completion(chat_request, allow_failover=False)

                # Verify the error includes the original message
                assert error_msg in str(exc_info.value)
