"""
Additional targeted tests for the BackendService to improve coverage.
"""

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest
from src.connectors.base import LLMBackend
from src.core.common.exceptions import BackendError
from src.core.config.app_config import AppConfig, BackendConfig
from src.core.domain.backend_type import BackendType
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.configuration.app_identity_config import AppIdentityConfig
from src.core.domain.configuration.header_config import (
    HeaderConfig,
    HeaderOverrideMode,
)
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.interfaces.session_service_interface import ISessionService
from src.core.services.backend_factory import BackendFactory
from src.core.services.backend_service import BackendService

# Suppress Windows ProactorEventLoop ResourceWarnings for this module
pytestmark = pytest.mark.filterwarnings(
    "ignore:unclosed event loop <ProactorEventLoop.*:ResourceWarning"
)


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
    ) -> ResponseEnvelope:
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
            self,
            request: ChatRequest,
            *,
            stream: bool = False,
            allow_failover: bool = True,
            context: RequestContext | None = None,
            **kwargs: Any,
        ) -> ResponseEnvelope:
            from src.core.domain.responses import StreamingResponseEnvelope

            result = await self.call_completion(
                request,
                stream=stream,
                allow_failover=allow_failover,
                context=context,
            )
            if isinstance(result, StreamingResponseEnvelope):
                # In a real scenario, you'd handle the stream. For this test, we just consume it.
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

    @pytest.mark.asyncio
    async def test_chat_completions_forwards_control_flags(self):
        """Ensure chat_completions forwards failover and context to call_completion."""

        service = BackendService(
            factory=Mock(spec=BackendFactory),
            rate_limiter=Mock(),
            config=Mock(),
            session_service=Mock(spec=ISessionService),
            app_state=Mock(spec=IApplicationState),
        )

        chat_request = ChatRequest(
            messages=[ChatMessage(role="user", content="Hello")],
            model="test-model",
            extra_body={},
        )
        context = Mock(spec=RequestContext)

        expected_response = ResponseEnvelope(content={}, headers={})

        with patch.object(
            service,
            "call_completion",
            AsyncMock(return_value=expected_response),
        ) as call_completion_mock:
            result = await service.chat_completions(
                chat_request,
                stream=True,
                allow_failover=False,
                context=context,
            )

        assert result is expected_response
        call_completion_mock.assert_awaited_once_with(
            chat_request,
            stream=True,
            allow_failover=False,
            context=context,
        )

    @pytest.mark.asyncio
    async def test_call_completion_raises_when_backend_not_functional(self):
        """Ensure non-functional backends trigger an immediate error."""
        service = create_backend_service()
        client = httpx.AsyncClient()
        mock_backend = MockBackend(client)
        mock_backend.chat_completions_mock.return_value = ResponseEnvelope(
            content={"id": "resp", "choices": []},
            headers={},
        )
        mock_backend.is_backend_functional = Mock(return_value=False)

        chat_request = ChatRequest(
            messages=[ChatMessage(role="user", content="Hello")],
            model="test-model",
            extra_body={},
        )

        with (
            patch.object(service, "_get_or_create_backend", return_value=mock_backend),
            pytest.raises(BackendError) as exc_info,
        ):
            await service.call_completion(chat_request, allow_failover=False)

        assert "not functional" in str(exc_info.value).lower()
        assert not mock_backend.chat_completions_called

    def test_provider_identity_precedence(self):
        """Provider-supplied backend identity should override global defaults."""

        provider_identity = AppIdentityConfig(
            title=HeaderConfig(
                mode=HeaderOverrideMode.DEFAULT,
                default_value="ProviderTitle",
            ),
            url=HeaderConfig(
                mode=HeaderOverrideMode.DEFAULT,
                default_value="https://provider.example",
            ),
        )
        provider_backend_config = BackendConfig(
            api_key=["provider-key"],
            identity=provider_identity,
        )

        global_identity = AppIdentityConfig(
            title=HeaderConfig(
                mode=HeaderOverrideMode.DEFAULT,
                default_value="GlobalTitle",
            ),
            url=HeaderConfig(
                mode=HeaderOverrideMode.DEFAULT,
                default_value="https://global.example",
            ),
        )
        app_config = AppConfig(identity=global_identity)

        class IdentityBackend(LLMBackend):
            backend_type = "openai"

            def __init__(self) -> None:
                self.recorded_identity = None

            async def initialize(self, **kwargs: Any) -> None:  # pragma: no cover - noop
                return None

            def get_available_models(self) -> list[str]:
                return ["gpt-4"]

            async def chat_completions(
                self,
                request_data: ChatRequest,
                processed_messages: list,
                effective_model: str,
                identity: Any = None,
                **kwargs: Any,
            ) -> ResponseEnvelope:
                self.recorded_identity = identity
                return ResponseEnvelope(content={}, headers={})

        backend_instance = IdentityBackend()

        class StubProvider:
            def __init__(self, backend_config: BackendConfig) -> None:
                self._backend_config = backend_config

            def get_backend_config(self, name: str) -> BackendConfig | None:
                if name == "openai":
                    return self._backend_config
                return None

            def iter_backend_names(self) -> list[str]:  # pragma: no cover - not used
                return ["openai"]

            def get_default_backend(self) -> str:  # pragma: no cover - not used
                return "openai"

            def get_functional_backends(self) -> set[str]:  # pragma: no cover - not used
                return {"openai"}

            def apply_backend_config(
                self, request: ChatRequest, backend_type: str, config: AppConfig
            ) -> ChatRequest:
                return request

        factory = Mock(spec=BackendFactory)
        factory.ensure_backend = AsyncMock(return_value=backend_instance)

        rate_limiter = Mock()
        rate_limiter.check_limit = AsyncMock(
            return_value=SimpleNamespace(is_limited=False)
        )
        rate_limiter.record_usage = AsyncMock()

        session_service = Mock(spec=ISessionService)
        session_service.get_session = AsyncMock(return_value=None)

        app_state = Mock(spec=IApplicationState)

        service = BackendService(
            factory,
            rate_limiter,
            app_config,
            session_service,
            app_state,
            backend_config_provider=StubProvider(provider_backend_config),
        )

        chat_request = ChatRequest(
            messages=[ChatMessage(role="user", content="Hello")],
            model="openai:gpt-4",
            stream=False,
        )

        async def _invoke() -> None:
            await service.call_completion(chat_request, stream=False)

        asyncio.run(_invoke())

        assert backend_instance.recorded_identity is not None
        assert (
            backend_instance.recorded_identity.title.default_value
            == "ProviderTitle"
        )
        assert (
            backend_instance.recorded_identity.url.default_value
            == "https://provider.example"
        )
        factory.ensure_backend.assert_awaited_once_with(
            "openai", app_config, provider_backend_config
        )
