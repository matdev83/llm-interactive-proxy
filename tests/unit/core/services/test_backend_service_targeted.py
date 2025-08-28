"""
Additional targeted tests for the BackendService to improve coverage.
"""

from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest
from src.connectors.base import LLMBackend
from src.core.common.exceptions import BackendError
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
    ) -> ResponseEnvelope:  # type: ignore
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
    config = AppConfig()
    factory = BackendFactory(client, registry, config)
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
                return ResponseEnvelope(content={}, headers={})
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


class TestBackendServiceTargeted:
    """Targeted tests for specific uncovered lines in the BackendService."""

    @pytest.mark.asyncio
    async def test_call_completion_with_default_backend_parsing(self):
        """Test call_completion when backend needs to be parsed from model."""
        # Arrange
        service = create_backend_service()
        client = httpx.AsyncClient()
        mock_backend = MockBackend(client)
        mock_backend.chat_completions_mock.return_value = ResponseEnvelope(
            content={
                "id": "resp-123",
                "created": 123,
                "model": "gpt-4",
                "choices": [],
            },
            headers={},
        )

        # Create a request without backend_type in extra_body
        chat_request = ChatRequest(
            messages=[ChatMessage(role="user", content="Hello")],
            model="gpt-4",  # This should be parsed to determine backend
            extra_body={},  # No backend_type specified
        )

        with patch.object(service, "_get_or_create_backend", return_value=mock_backend):
            # Act
            response = await service.call_completion(chat_request)

            # Assert
            assert mock_backend.chat_completions_called
            assert response.content["model"] == "gpt-4"

    @pytest.mark.asyncio
    async def test_get_or_create_backend_error_handling(self):
        """Test error handling in _get_or_create_backend method."""
        # Arrange
        service = create_backend_service()

        # Mock the factory to raise an exception
        with patch.object(
            service._factory, "ensure_backend", side_effect=Exception("Factory error")
        ):
            # Act & Assert
            with pytest.raises(BackendError) as exc_info:
                await service._get_or_create_backend("nonexistent-backend")

            # Verify the error includes the original message
            assert "Failed to create backend" in str(exc_info.value)
            assert "Factory error" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_call_completion_with_session_backend(self):
        """Test call_completion when backend is determined from session."""
        # Arrange
        service = create_backend_service()
        client = httpx.AsyncClient()
        mock_backend = MockBackend(client)
        mock_backend.chat_completions_mock.return_value = ResponseEnvelope(
            content={
                "id": "resp-123",
                "created": 123,
                "model": "test-model",
                "choices": [],
            },
            headers={},
        )

        # Create a request with session_id that should have backend config
        chat_request = ChatRequest(
            messages=[ChatMessage(role="user", content="Hello")],
            model="test-model",
            extra_body={"session_id": "test-session"},
        )

        # Mock session service to return a session with backend config
        mock_session = Mock()
        mock_session.state = Mock()
        mock_session.state.backend_config = Mock()
        mock_session.state.backend_config.backend_type = BackendType.OPENAI

        with (
            patch.object(
                service._session_service, "get_session", return_value=mock_session
            ),
            patch.object(service, "_get_or_create_backend", return_value=mock_backend),
        ):
            # Act
            response = await service.call_completion(chat_request)

            # Assert
            assert mock_backend.chat_completions_called
            assert response.content["model"] == "test-model"
