"""
Enhanced tests for the BackendService implementation.
"""

from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest
from fastapi import HTTPException

pytestmark = pytest.mark.filterwarnings(
    "ignore:unclosed event loop <ProactorEventLoop.*:ResourceWarning"
)
from src.connectors.base import LLMBackend
from src.core.common.exceptions import (
    BackendError,
    LLMProxyError,
    RateLimitExceededError,
)
from src.core.domain.backend_type import BackendType
from src.core.domain.chat import (
    ChatMessage,
    ChatRequest,
)
from src.core.domain.request_context import (
    RequestContext,
    RequestCookies,
    RequestHeaders,
)
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.interfaces.model_bases import DomainModel, InternalDTO
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.interfaces.session_service_interface import ISessionService
from src.core.services.backend_factory import BackendFactory
from src.core.services.backend_service import BackendService

# Legacy models removed; use domain ChatRequest instead when needed
from tests.unit.core.test_doubles import MockRateLimiter


# Session-scoped fixtures to optimize test performance
@pytest.fixture(scope="session")
def http_client():
    """Create a shared HTTP client for all tests."""
    return httpx.AsyncClient()


@pytest.fixture(scope="session")
def app_config():
    """Create a shared AppConfig for all tests."""
    from src.core.config.app_config import AppConfig

    return AppConfig()


@pytest.fixture(scope="session")
def backend_registry():
    """Create a shared BackendRegistry for all tests."""
    from src.core.services.backend_registry import BackendRegistry

    registry = BackendRegistry()

    # Register a mock factory for 'openai' to handle tests using it
    # The factory returns a backend instance
    mock_backend = Mock()
    mock_backend.initialize = AsyncMock()
    mock_backend.chat_completions = AsyncMock()
    mock_backend.get_available_models = Mock(return_value=["model1", "model2"])

    # Factory function returns the backend
    mock_factory = Mock(return_value=mock_backend)
    registry.register_backend("openai", mock_factory)

    return registry


@pytest.fixture(scope="session")
def translation_service():
    """Create a shared TranslationService for all tests."""
    from src.core.services.translation_service import TranslationService

    return TranslationService()


@pytest.fixture(scope="session")
def backend_factory(http_client, backend_registry, app_config, translation_service):
    """Create a shared BackendFactory for all tests."""
    from src.core.services.backend_factory import BackendFactory

    return BackendFactory(
        http_client, backend_registry, app_config, translation_service
    )


@pytest.fixture
def mock_config():
    """Create a mock configuration."""
    config = Mock()
    config.get.return_value = None
    return config


@pytest.fixture
def service_components():
    """Create common service components for testing."""
    rate_limiter = MockRateLimiter()
    session_service = Mock(spec=ISessionService)
    app_state = Mock(spec=IApplicationState)
    from tests.utils.failover_stub import StubFailoverCoordinator

    return rate_limiter, session_service, app_state, StubFailoverCoordinator()


@pytest.fixture
def backend_service(backend_factory, mock_config, service_components):
    """Create a BackendService instance for testing."""
    rate_limiter, session_service, app_state, failover_coordinator = service_components
    from tests.unit.fixtures.backend_service_builder import (
        create_backend_service_with_mocks,
    )

    return create_backend_service_with_mocks(
        factory=backend_factory,
        rate_limiter=rate_limiter,
        config=mock_config,
        session_service=session_service,
        app_state=app_state,
        failover_coordinator=failover_coordinator,
    )


class MockBackend(LLMBackend):
    """Mock implementation of LLMBackend for testing."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        available_models: list[str] | None = None,
    ) -> None:
        # Initialize base class to ensure health attributes are present
        # MockBackend doesn't use real config, so pass a mock or empty config
        super().__init__(config=Mock())
        self.client = client
        self.available_models = available_models or ["model1", "model2"]
        self.initialize_called = False
        self.chat_completions_called = False
        self.chat_completions_mock: AsyncMock = AsyncMock()  # type: ignore

    async def initialize(self, **kwargs: Any) -> None:
        self.initialize_called = True
        self.initialize_kwargs = kwargs

    def get_available_models(self) -> list[str]:
        return self.available_models

    async def chat_completions(
        self,
        request_data: DomainModel | InternalDTO | dict[str, Any],
        processed_messages: list,
        effective_model: str,
        identity: Any = None,
        **kwargs: Any,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        self.chat_completions_called = True
        self.chat_completions_args = {
            "request_data": request_data,
            "processed_messages": processed_messages,
            "effective_model": effective_model,
            "identity": identity,
            "kwargs": kwargs,
        }
        return await self.chat_completions_mock()


class MockStreamingResponse:
    """Mock implementation of StreamingResponse for testing."""

    def __init__(self, content):
        self.content = content

    def __aiter__(self):
        """Make this class async iterable."""
        return self

    async def __anext__(self):
        if not hasattr(self, "_content_iter"):
            self._content_iter = iter(self.content)
        try:
            chunk = next(self._content_iter)
            return ProcessedResponse(content=chunk)
        except StopIteration:
            raise StopAsyncIteration


class TestBackendFactory:
    """Tests for the BackendFactory class."""

    @pytest.mark.asyncio
    async def test_create_backend(self, backend_factory, http_client, backend_registry):
        """Test creating a backend with the factory."""
        # Mock the backend registry instead of non-existent _backend_types
        mock_backend = MockBackend(http_client)
        with patch.object(
            backend_registry,
            "get_backend_factory",
            return_value=lambda client, config, translation_service: mock_backend,
        ):
            # Act
            backend = backend_factory.create_backend(
                "openai", {}
            )  # Used empty config for test

            # Assert
            assert isinstance(backend, MockBackend)
            assert backend.client == http_client

    @pytest.mark.no_global_mock
    @pytest.mark.asyncio
    async def test_initialize_backend(self, backend_factory, http_client):
        """Test initializing a backend with the factory."""
        backend = MockBackend(http_client)
        init_config = {"api_key": "test-key", "extra_param": "value"}

        # Act
        await backend_factory.initialize_backend(backend, init_config)

        # Assert
        assert backend.initialize_called
        assert backend.initialize_kwargs == init_config

    @pytest.mark.asyncio
    async def test_create_backend_invalid_type(self, backend_factory):
        """Test creating a backend with an invalid type."""
        # Act & Assert
        with pytest.raises(ValueError):
            backend_factory.create_backend("invalid-backend-type", {})


class ConcreteBackendService(BackendService):
    """Concrete implementation of the abstract BackendService for testing."""

    async def chat_completions(
        self, request: ChatRequest, **kwargs: Any
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """
        Implement the abstract method for testing purposes.
        This method should not be called directly in tests.
        """
        # Just pass through to the call_completion method
        stream = kwargs.get("stream", False)
        return await self.call_completion(request, stream=stream)


class TestBackendServiceBasic:
    """Basic tests for the BackendService class."""

    @pytest.fixture
    def mock_config(self):
        """Create a mock configuration."""
        config = Mock()
        config.get.return_value = None
        return config

    @pytest.fixture
    def service(self, mock_config):
        """Create a BackendService instance for testing."""
        client = httpx.AsyncClient()
        from src.core.services.backend_registry import BackendRegistry

        registry = BackendRegistry()
        mock_backend = MockBackend(client)
        mock_backend.initialize = AsyncMock()
        mock_backend.chat_completions = AsyncMock()
        mock_factory = Mock(return_value=mock_backend)
        registry.register_backend("openai", mock_factory)

        from src.core.config.app_config import AppConfig
        from src.core.services.translation_service import TranslationService

        config = AppConfig()
        factory = BackendFactory(client, registry, config, TranslationService())
        rate_limiter = MockRateLimiter()
        session_service = Mock(spec=ISessionService)
        app_state = Mock(spec=IApplicationState)
        from tests.unit.fixtures.backend_service_builder import (
            create_backend_service_with_mocks,
        )
        from tests.utils.failover_stub import StubFailoverCoordinator

        return create_backend_service_with_mocks(
            factory=factory,
            rate_limiter=rate_limiter,
            config=mock_config,
            session_service=session_service,
            app_state=app_state,
            failover_coordinator=StubFailoverCoordinator(),
        )

    def test_prepare_messages_removed(self, service):
        """BackendService no longer implements _prepare_messages; handled by backends."""
        assert not hasattr(service, "_prepare_messages")


class TestBackendServiceCompletions:
    """Tests for the BackendService's completion handling."""

    @staticmethod
    async def mock_streaming_content(
        chunks: list[str],
    ) -> AsyncIterator[ProcessedResponse]:
        for chunk in chunks:
            yield ProcessedResponse(content=chunk)

    @pytest.fixture
    def mock_config(self):
        """Create a mock configuration."""
        config = Mock()
        config.get.return_value = None
        return config

    @pytest.fixture
    def service(self, mock_config):
        """Create a BackendService instance for testing."""
        client = httpx.AsyncClient()
        from src.core.services.backend_registry import BackendRegistry

        registry = BackendRegistry()
        # Mock backend needs async methods
        mock_backend = MockBackend(client)
        mock_backend.initialize = AsyncMock()
        mock_backend.chat_completions = AsyncMock()
        mock_factory = Mock(return_value=mock_backend)
        registry.register_backend("openai", mock_factory)

        from src.core.config.app_config import AppConfig
        from src.core.services.translation_service import TranslationService

        config = AppConfig()
        factory = BackendFactory(client, registry, config, TranslationService())
        rate_limiter = MockRateLimiter()
        session_service = Mock(spec=ISessionService)
        app_state = Mock(spec=IApplicationState)
        from src.core.interfaces.backend_lifecycle_manager_interface import (
            IBackendLifecycleManager,
        )
        from src.core.interfaces.backend_model_resolver_interface import (
            IBackendModelResolver,
            ResolvedTarget,
        )

        from tests.unit.fixtures.backend_service_builder import (
            create_backend_service_with_mocks,
        )
        from tests.utils.failover_stub import StubFailoverCoordinator

        # Mock lifecycle manager
        mock_lifecycle_manager = AsyncMock(spec=IBackendLifecycleManager)
        mock_lifecycle_manager.get_disabled_backends.return_value = {}

        # Mock model resolver
        mock_model_resolver = Mock(spec=IBackendModelResolver)
        mock_model_resolver.resolve_target = AsyncMock(
            return_value=ResolvedTarget(
                backend=BackendType.OPENAI.value, model="model1", uri_params={}
            )
        )
        mock_model_resolver.synchronize_request_with_target = (
            lambda request, resolved: request
        )

        service = create_backend_service_with_mocks(
            factory=factory,
            rate_limiter=rate_limiter,
            config=mock_config,
            session_service=session_service,
            app_state=app_state,
            failover_coordinator=StubFailoverCoordinator(),
            use_real_completion_flow=True,
            backend_lifecycle_manager=mock_lifecycle_manager,
            backend_model_resolver=mock_model_resolver,
        )

        # Configure exception normalizer to return exceptions as-is by default
        # This prevents "exceptions must derive from BaseException" errors when
        # mocks return Mock objects instead of exceptions
        service._exception_normalizer.normalize.side_effect = lambda exc, *args: exc
        service._backend_completion_flow._exception_normalizer.normalize.side_effect = (
            lambda exc, *args: exc
        )

        return service

    @pytest.fixture
    def chat_request(self):
        """Create a basic chat request for testing."""
        return ChatRequest(
            messages=[ChatMessage(role="user", content="Hello")],
            model="model1",
            extra_body={"backend_type": BackendType.OPENAI},
        )

    @pytest.mark.asyncio
    async def test_call_completion_basic(self, service, chat_request):
        """Test calling a completion with the service."""
        # Arrange
        client = httpx.AsyncClient()
        mock_backend = MockBackend(client)
        mock_backend.chat_completions_mock.return_value = ResponseEnvelope(
            content={
                "id": "resp-123",
                "created": 123,
                "model": "model1",
                "choices": [],
            },
            headers={},
        )

        # Mock the lifecycle manager to return our test backend
        service._backend_lifecycle_manager.get_or_create = AsyncMock(
            return_value=mock_backend
        )

        # Act
        response = await service.call_completion(chat_request)

        # Assert
        assert mock_backend.chat_completions_called
        assert response.content["id"] == "resp-123"
        assert response.content["model"] == "model1"

    @pytest.mark.asyncio
    async def test_call_completion_streaming(self, service, chat_request):
        """Test calling a streaming completion."""
        # Arrange
        chunks = [
            'data: {"id":"chunk1","choices":[{"delta":{"content":"Hello"}}]}\n\n',
            'data: {"id":"chunk2","choices":[{"delta":{"content":" world"}}]}\n\n',
            "data: [DONE]\n\n",
        ]

        client = httpx.AsyncClient()
        mock_backend = MockBackend(client)
        mock_backend.chat_completions_mock.return_value = StreamingResponseEnvelope(
            content=self.mock_streaming_content(chunks),
            media_type="text/event-stream",
            headers={},
        )

        # Mock the lifecycle manager to return our test backend
        service._backend_lifecycle_manager.get_or_create = AsyncMock(
            return_value=mock_backend
        )

        # Act
        response = await service.call_completion(chat_request, stream=True)

        # Assert
        assert mock_backend.chat_completions_called

        # Collect chunks from the stream
        result_chunks = []
        async for chunk in response.content:
            result_chunks.append(chunk)

        # Verify chunks
        # Note: After going through stream formatting, chunks are converted to bytes
        assert len(result_chunks) == len(chunks)
        for i, chunk in enumerate(chunks):
            assert isinstance(result_chunks[i], ProcessedResponse)
            # Content is bytes after stream formatting conversion
            expected_bytes = chunk.encode("utf-8") if isinstance(chunk, str) else chunk
            assert result_chunks[i].content == expected_bytes

    @pytest.mark.asyncio
    async def test_call_completion_streaming_error(self, service, chat_request):
        """Test delegated streaming errors propagate from completion flow."""

        # Arrange
        service._backend_completion_flow.call_completion = AsyncMock(
            side_effect=ValueError("Streaming error")
        )

        # Act & Assert
        with pytest.raises(ValueError) as exc_info:
            await service.call_completion(
                chat_request, stream=True, allow_failover=False
            )

        assert "Streaming error" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_call_completion_rate_limited(self, service, chat_request):
        """Test rate limiting via ResilienceCoordinator in the backend service.

        Note: Legacy rate limiter checks have been removed from call_completion.
        Rate limiting is now handled by the ResilienceCoordinator.
        """
        from unittest.mock import MagicMock

        from src.core.interfaces.resilience_interface import ResilienceDecision

        # Create a mock ResilienceCoordinator that returns rate limited decision
        mock_resilience = MagicMock()
        mock_decision = MagicMock(spec=ResilienceDecision)
        mock_decision.should_proceed.return_value = False
        mock_decision.reason = "Rate limit exceeded for test"
        mock_decision.cooldown_remaining = 60.0
        mock_resilience.check_availability.return_value = mock_decision

        # Set the mock resilience coordinator on both service and completion flow
        service._resilience = mock_resilience
        service._backend_completion_flow._resilience = mock_resilience
        # Also set it on the availability checker which performs the actual check
        service._backend_completion_flow._availability_checker._resilience = (
            mock_resilience
        )

        # Act & Assert
        with pytest.raises(RateLimitExceededError) as exc_info:
            await service.call_completion(chat_request)

        # Verify exception details - only check the basic message
        assert "Rate limit exceeded" in str(exc_info.value) or "test" in str(
            exc_info.value
        )
        # Verify resilience coordinator was consulted
        mock_resilience.check_availability.assert_called_once()

    @pytest.mark.asyncio
    async def test_retry_429_preserves_backend_kwargs(
        self, service, chat_request
    ) -> None:
        """Test that 429 errors with allow_failover=False raise immediately.

        Note: With the new failure handling architecture, when allow_failover=False,
        the backend service does NOT retry on 429 errors. The error is raised
        immediately to the caller. Automatic retry behavior requires allow_failover=True
        and is managed by the IFailureHandlingStrategy.
        """
        session_state = SimpleNamespace(project="proj-alpha", project_dir="/tmp/proj")
        session_obj = SimpleNamespace(state=session_state)
        service._session_service.get_session = AsyncMock(return_value=session_obj)

        context = RequestContext(
            headers=RequestHeaders(raw={"x-session-id": "session-123"}),
            cookies=RequestCookies(raw={}),
            state={},
            app_state={},
            session_id="session-123",
        )

        class RecordingBackend(MockBackend):
            def __init__(self) -> None:
                super().__init__(httpx.AsyncClient())
                self.calls: list[dict[str, Any]] = []

            async def chat_completions(
                self,
                request_data: DomainModel | InternalDTO | dict[str, Any],
                processed_messages: list,
                effective_model: str,
                identity: Any = None,
                **kwargs: Any,
            ) -> ResponseEnvelope | StreamingResponseEnvelope:
                self.calls.append(
                    {
                        "kwargs": dict(kwargs),
                        "identity": identity,
                        "processed_messages": list(processed_messages),
                    }
                )
                if len(self.calls) == 1:
                    raise BackendError(
                        message="rate limited",
                        backend_name=BackendType.OPENAI.value,
                        status_code=429,
                    )
                return ResponseEnvelope(
                    content={"id": "retry", "choices": []}, headers={}
                )

        backend = RecordingBackend()

        # Mock the lifecycle manager to return our test backend
        service._backend_lifecycle_manager.get_or_create = AsyncMock(
            return_value=backend
        )

        # Mock exception normalizer to convert BackendError with status_code=429 to RateLimitExceededError
        rate_limit_error = RateLimitExceededError(
            message="rate limited",
            details={"backend": BackendType.OPENAI},
        )
        service._exception_normalizer.normalize = Mock(return_value=rate_limit_error)
        service._backend_completion_flow._exception_normalizer.normalize = Mock(
            return_value=rate_limit_error
        )

        # With allow_failover=False, 429 errors should raise immediately
        with pytest.raises(RateLimitExceededError) as exc_info:
            await service.call_completion(
                chat_request,
                allow_failover=False,
                context=context,
            )

        assert exc_info.value.status_code == 429

        # Only one call should have been made (no retry with allow_failover=False)
        assert len(backend.calls) == 1
        actual_kwargs = backend.calls[0]["kwargs"]
        # Check that expected kwargs are present (allow for additional kwargs like cancellation_coordinator, cancellation_token)
        assert actual_kwargs["session_id"] == "session-123"
        assert actual_kwargs["project"] == "proj-alpha"
        assert actual_kwargs["project_dir"] == "/tmp/proj"

    @pytest.mark.asyncio
    async def test_call_completion_backend_error(self, service, chat_request):
        """Test error handling when backend calls fail."""
        # Arrange
        client = httpx.AsyncClient()
        mock_backend = MockBackend(client)
        mock_backend.chat_completions_mock.side_effect = ValueError("API error")

        # Mock the lifecycle manager to return our test backend
        service._backend_lifecycle_manager.get_or_create = AsyncMock(
            return_value=mock_backend
        )

        # Act & Assert
        with pytest.raises(BackendError) as exc_info:
            await service.call_completion(chat_request, allow_failover=False)

        # Verify exception details
        assert "Backend call failed" in str(exc_info.value)
        assert "API error" in str(exc_info.value)
        # Note: The backend type may not be included in the error message in all implementations

    @pytest.mark.asyncio
    async def test_retry_429_preserves_backend_kwargs_alt(
        self, service, chat_request
    ) -> None:
        """Test that 429 errors with allow_failover=False raise immediately (alternative).

        Note: With the new failure handling architecture, when allow_failover=False,
        the backend service does NOT retry on 429 errors. The error is raised
        immediately to the caller. Automatic retry behavior requires allow_failover=True
        and is managed by the IFailureHandlingStrategy.
        """

        class TrackingBackend(LLMBackend):
            def __init__(self) -> None:
                # Initialize base class to ensure health attributes are present
                super().__init__(config=Mock())
                self.calls: list[dict[str, Any]] = []
                self._responses: list[object] = [
                    BackendError(
                        "Rate limited",
                        backend_name=BackendType.OPENAI,
                        status_code=429,
                        details={"error": {"message": "Too Many Requests"}},
                    ),
                    ResponseEnvelope(content={"ok": True}, headers={}),
                ]

            async def initialize(
                self, **kwargs: Any
            ) -> None:  # pragma: no cover - unused in test
                return None

            def get_available_models(self) -> list[str]:
                return ["model1"]

            async def chat_completions(
                self,
                request_data: DomainModel | InternalDTO | dict[str, Any],
                processed_messages: list,
                effective_model: str,
                identity: Any = None,
                **kwargs: Any,
            ) -> ResponseEnvelope | StreamingResponseEnvelope:
                self.calls.append(dict(kwargs))
                next_response = self._responses.pop(0)
                if isinstance(next_response, Exception):
                    raise next_response
                return next_response  # type: ignore[return-value]

        backend = TrackingBackend()
        service._backend_lifecycle_manager.get_or_create = AsyncMock(
            return_value=backend
        )

        session = SimpleNamespace(
            state=SimpleNamespace(
                project="proj-alpha",
                project_dir="/tmp/proj",
                backend_config=None,
            )
        )
        service._session_service.get_session = AsyncMock(return_value=session)

        context = RequestContext(
            headers=RequestHeaders(raw={"x-session-id": "session-123"}),
            cookies=RequestCookies(raw={}),
            state={},
            app_state={},
        )

        request_with_session = chat_request.model_copy(
            update={
                "extra_body": {
                    "backend_type": BackendType.OPENAI,
                    "session_id": "sess-123",
                }
            }
        )

        # Mock exception normalizer to convert BackendError with status_code=429 to RateLimitExceededError
        rate_limit_error = RateLimitExceededError(
            message="Rate limited",
        )
        service._exception_normalizer.normalize = Mock(return_value=rate_limit_error)
        service._backend_completion_flow._exception_normalizer.normalize = Mock(
            return_value=rate_limit_error
        )

        # With allow_failover=False, 429 errors should raise immediately
        with pytest.raises(RateLimitExceededError) as exc_info:
            await service.call_completion(
                request_with_session, context=context, allow_failover=False
            )

        assert exc_info.value.status_code == 429

        # Only one call should have been made (no retry with allow_failover=False)
        assert len(backend.calls) == 1
        first_call = backend.calls[0]
        assert first_call.get("session_id") == "sess-123"
        assert first_call.get("project") == "proj-alpha"
        assert first_call.get("project_dir") == "/tmp/proj"

    @pytest.mark.asyncio
    async def test_call_completion_invalid_response(self, service, chat_request):
        """Test error handling for invalid response format."""
        # Arrange
        client = httpx.AsyncClient()
        mock_backend = MockBackend(client)
        # Return invalid response format (not a tuple)
        mock_backend.chat_completions_mock.side_effect = Exception(
            "Invalid response format"
        )

        # Mock the lifecycle manager to return our test backend
        service._backend_lifecycle_manager.get_or_create = AsyncMock(
            return_value=mock_backend
        )

        # Act & Assert
        with pytest.raises(BackendError) as exc_info:
            await service.call_completion(chat_request)

        # Don't check for specific error message as it may vary across implementations
        assert (
            "Invalid response format" in str(exc_info.value)
            or "Backend call failed" in str(exc_info.value)
            or "unexpected error" in str(exc_info.value).lower()
        )

    @pytest.mark.asyncio
    async def test_call_completion_http_429_raises_rate_limit(
        self, service, chat_request
    ):
        """Ensure HTTP 429 from backend surfaces as RateLimitExceededError."""
        client = httpx.AsyncClient()
        mock_backend = MockBackend(client)
        http_exc = HTTPException(
            status_code=429,
            detail={"error": {"message": "Too Many Requests", "type": "rate_limit"}},
            headers={"Retry-After": "5"},
        )
        mock_backend.chat_completions_mock.side_effect = http_exc

        # Mock the exception normalizer to convert HTTPException 429 to RateLimitExceededError
        rate_limit_error = RateLimitExceededError(
            message="Too Many Requests",
            details={"backend": BackendType.OPENAI},
        )
        service._exception_normalizer.normalize = Mock(return_value=rate_limit_error)

        # Mock the lifecycle manager to return our test backend
        service._backend_lifecycle_manager.get_or_create = AsyncMock(
            return_value=mock_backend
        )
        # Also set on completion flow
        service._backend_completion_flow._exception_normalizer.normalize = Mock(
            return_value=rate_limit_error
        )

        with pytest.raises(RateLimitExceededError) as exc_info:
            await service.call_completion(chat_request, allow_failover=False)

        error = exc_info.value
        assert error.status_code == 429
        assert "Too Many Requests" in error.message
        assert error.details.get("backend") == BackendType.OPENAI

    @pytest.mark.asyncio
    async def test_call_completion_http_429_no_failover_routes(
        self, service, chat_request
    ):
        """Verify default failover path also surfaces RateLimitExceededError."""
        client = httpx.AsyncClient()
        mock_backend = MockBackend(client)
        http_exc = HTTPException(
            status_code=429,
            detail="Rate limited",
        )
        mock_backend.chat_completions_mock.side_effect = http_exc

        # Mock the exception normalizer to convert HTTPException 429 to RateLimitExceededError
        rate_limit_error = RateLimitExceededError(
            message="Rate limited",
        )
        service._exception_normalizer.normalize = Mock(return_value=rate_limit_error)
        # Also set on completion flow
        service._backend_completion_flow._exception_normalizer.normalize = Mock(
            return_value=rate_limit_error
        )

        # Mock the lifecycle manager to return our test backend
        service._backend_lifecycle_manager.get_or_create = AsyncMock(
            return_value=mock_backend
        )

        with pytest.raises(RateLimitExceededError) as exc_info:
            await service.call_completion(chat_request)

        assert exc_info.value.status_code == 429

    @pytest.mark.asyncio
    async def test_call_completion_invalid_streaming_response(
        self,
        service,
        chat_request,
    ):
        """Test delegated errors for invalid streaming response format."""
        service._backend_completion_flow.call_completion = AsyncMock(
            side_effect=Exception("Invalid streaming response format")
        )

        # Act & Assert
        with pytest.raises(Exception) as exc_info:
            await service.call_completion(
                chat_request, stream=True, allow_failover=False
            )

        assert "Invalid streaming response" in str(exc_info.value)


class TestBackendServiceValidation:
    """Tests for the BackendService's validation capabilities."""

    @pytest.mark.asyncio
    async def test_validate_backend_and_model_valid(self, backend_service, http_client):
        """Test validating a valid backend and model."""
        # Arrange
        mock_backend = MockBackend(
            http_client, available_models=["valid-model", "other-model"]
        )

        with patch.object(
            backend_service._backend_lifecycle_manager,
            "get_or_create",
            return_value=mock_backend,
        ):
            # Act
            result = await backend_service.validate_backend_and_model(
                BackendType.OPENAI, "valid-model"
            )

            # Assert
            assert result.is_valid is True
            assert result.error_message is None

    @pytest.mark.asyncio
    async def test_validate_backend_and_model_invalid_model(
        self, backend_service, http_client
    ):
        """Test validating an invalid model."""
        # Arrange
        mock_backend = MockBackend(http_client, available_models=["valid-model"])

        with patch.object(
            backend_service._backend_lifecycle_manager,
            "get_or_create",
            return_value=mock_backend,
        ):
            # Act
            result = await backend_service.validate_backend_and_model(
                BackendType.OPENAI, "invalid-model"
            )

            # Assert
            assert result.is_valid is False
            assert "not available" in result.error_message

    @pytest.mark.asyncio
    async def test_validate_backend_and_model_backend_error(self, backend_service):
        """Test validating with a backend error."""
        # Arrange
        with patch.object(
            backend_service._backend_lifecycle_manager,
            "get_or_create",
            side_effect=ValueError("Backend error"),
        ):
            # Act
            result = await backend_service.validate_backend_and_model(
                BackendType.OPENAI, "model"
            )

            # Assert
            assert result.is_valid is False
            assert "Backend validation failed" in result.error_message
            assert "Backend error" in result.error_message

    @pytest.mark.asyncio
    async def test_validate_backend_and_model_backend_error_object(
        self, backend_service
    ):
        """Test validating when backend creation raises BackendError."""
        backend_error = BackendError(message="boom", backend_name="test")

        with patch.object(
            backend_service._backend_lifecycle_manager,
            "get_or_create",
            side_effect=backend_error,
        ):
            result = await backend_service.validate_backend_and_model(
                BackendType.OPENAI, "model"
            )

        assert result.is_valid is False
        assert result.error_message is not None
        assert "Backend validation failed" in result.error_message
        assert "boom" in result.error_message


class TestBackendServiceFailover:
    """Tests for the BackendService's failover capabilities."""

    @pytest.fixture
    def mock_config(self):
        """Create a mock configuration."""
        config = Mock()
        config.get.return_value = None
        return config

    @pytest.fixture
    def service_with_simple_failover(self, mock_config):
        """Create a BackendService instance with simple failover routes."""
        client = httpx.AsyncClient()
        from src.core.services.backend_registry import BackendRegistry

        registry = BackendRegistry()
        mock_backend = MockBackend(client)
        mock_backend.initialize = AsyncMock()
        mock_backend.chat_completions = AsyncMock()
        mock_factory = Mock(return_value=mock_backend)
        registry.register_backend("openai", mock_factory)
        registry.register_backend("openrouter", mock_factory)

        from src.core.config.app_config import AppConfig
        from src.core.services.translation_service import TranslationService

        config = AppConfig()
        factory = BackendFactory(client, registry, config, TranslationService())
        rate_limiter = MockRateLimiter()
        session_service = Mock(spec=ISessionService)
        app_state = Mock(spec=IApplicationState)

        # Configure failover routes
        failover_routes: dict[str, dict[str, Any]] = {
            BackendType.OPENAI.value: {
                "backend": BackendType.OPENROUTER.value,
                "model": "fallback-model",
            }
        }

        from src.core.interfaces.backend_lifecycle_manager_interface import (
            IBackendLifecycleManager,
        )
        from src.core.interfaces.backend_model_resolver_interface import (
            IBackendModelResolver,
            ResolvedTarget,
        )

        from tests.unit.fixtures.backend_service_builder import (
            create_backend_service_with_mocks,
        )
        from tests.utils.failover_stub import StubFailoverCoordinator

        # Mock lifecycle manager
        mock_lifecycle_manager = AsyncMock(spec=IBackendLifecycleManager)
        mock_lifecycle_manager.get_disabled_backends.return_value = {}

        # Mock model resolver
        mock_model_resolver = Mock(spec=IBackendModelResolver)
        mock_model_resolver.resolve_target = AsyncMock(
            return_value=ResolvedTarget(
                backend=BackendType.OPENAI.value, model="model1", uri_params={}
            )
        )
        mock_model_resolver.synchronize_request_with_target = (
            lambda request, resolved: request
        )

        return create_backend_service_with_mocks(
            factory=factory,
            rate_limiter=rate_limiter,
            config=mock_config,
            session_service=session_service,
            app_state=app_state,
            failover_routes=failover_routes,
            failover_coordinator=StubFailoverCoordinator(),
            use_real_completion_flow=True,
            backend_lifecycle_manager=mock_lifecycle_manager,
            backend_model_resolver=mock_model_resolver,
        )

    @pytest.fixture
    def service_with_complex_failover(self, mock_config):
        """Create a BackendService instance with complex failover routes."""
        client = httpx.AsyncClient()
        from src.core.services.backend_registry import BackendRegistry

        registry = BackendRegistry()
        mock_backend = MockBackend(client)
        mock_backend.initialize = AsyncMock()
        mock_backend.chat_completions = AsyncMock()
        mock_factory = Mock(return_value=mock_backend)
        registry.register_backend("openai", mock_factory)
        registry.register_backend("openrouter", mock_factory)

        from src.core.config.app_config import AppConfig
        from src.core.services.translation_service import TranslationService

        config = AppConfig()
        # Ensure static_route is not set to avoid interference
        if hasattr(config, "backends") and hasattr(config.backends, "static_route"):
            config = config.model_copy(
                update={
                    "backends": config.backends.model_copy(
                        update={"static_route": None}
                    )
                }
            )

        factory = BackendFactory(client, registry, config, TranslationService())
        rate_limiter = MockRateLimiter()
        session_service = Mock(spec=ISessionService)
        app_state = Mock(spec=IApplicationState)

        # Configure complex failover routes by model
        failover_routes: dict[str, dict[str, Any]] = {
            "complex-model": {
                "attempts": [
                    {"backend": BackendType.ANTHROPIC.value, "model": "claude-2"},
                    {
                        "backend": BackendType.OPENROUTER.value,
                        "model": "last-resort-model",
                    },
                ]
            }
        }

        from src.core.interfaces.backend_lifecycle_manager_interface import (
            IBackendLifecycleManager,
        )
        from src.core.interfaces.backend_model_resolver_interface import (
            IBackendModelResolver,
            ResolvedTarget,
        )

        from tests.unit.fixtures.backend_service_builder import (
            create_backend_service_with_mocks,
        )
        from tests.utils.failover_stub import StubFailoverCoordinator

        # Mock lifecycle manager
        mock_lifecycle_manager = AsyncMock(spec=IBackendLifecycleManager)
        mock_lifecycle_manager.get_disabled_backends.return_value = {}

        # Mock model resolver - return appropriate backend based on model
        mock_model_resolver = Mock(spec=IBackendModelResolver)

        async def resolve_target(request, context=None):
            model = request.model
            # Check extra_body first for backend_type (used by failover attempts)
            if request.extra_body and "backend_type" in request.extra_body:
                backend_type = request.extra_body["backend_type"]
                if isinstance(backend_type, BackendType):
                    backend = backend_type.value
                else:
                    backend = backend_type
            elif model == "complex-model":
                backend = BackendType.OPENAI.value
            elif model == "claude-2":
                backend = BackendType.ANTHROPIC.value
            elif model == "last-resort-model":
                backend = BackendType.OPENROUTER.value
            else:
                backend = BackendType.OPENAI.value
            return ResolvedTarget(backend=backend, model=model, uri_params={})

        mock_model_resolver.resolve_target = AsyncMock(side_effect=resolve_target)
        mock_model_resolver.synchronize_request_with_target = (
            lambda request, resolved: request
        )

        return create_backend_service_with_mocks(
            factory=factory,
            rate_limiter=rate_limiter,
            config=config,  # Use the real config instead of mock_config
            session_service=session_service,
            app_state=app_state,
            failover_routes=failover_routes,
            failover_coordinator=StubFailoverCoordinator(),
            use_real_completion_flow=True,
            backend_lifecycle_manager=mock_lifecycle_manager,
            backend_model_resolver=mock_model_resolver,
        )

    @pytest.fixture
    def chat_request(self):
        """Create a basic chat request for testing."""
        return ChatRequest(
            messages=[ChatMessage(role="user", content="Hello")],
            model="model1",
            extra_body={"backend_type": BackendType.OPENAI},
        )

    @pytest.fixture
    def chat_request_complex(self):
        """Create a request with complex failover model."""
        return ChatRequest(
            messages=[ChatMessage(role="user", content="Hello")],
            model="complex-model",
            extra_body={"backend_type": BackendType.OPENAI},
        )

    @pytest.mark.asyncio
    async def test_simple_failover(self, service_with_simple_failover, chat_request):
        """Test that backend failures are surfaced when no failure strategy is configured.

        Note: With the new architecture, backend-level failover routes (e.g., openai -> openrouter)
        are no longer supported via _failover_routes. Failover is now managed by the
        IFailureHandlingStrategy which finds alternative backend INSTANCES for the same MODEL.

        This test verifies that without a failure strategy, backend failures are surfaced.
        """
        # Arrange
        # Create primary backend that fails
        client1 = httpx.AsyncClient()
        primary_backend = MockBackend(client1)
        primary_backend.initialize = AsyncMock()  # Ensure initialize is mocked
        primary_backend.chat_completions_mock.side_effect = BackendError(
            message="Primary backend error",
            backend_name=BackendType.OPENAI.value,
        )

        # Mock the lifecycle manager to return the primary backend
        # Ensure backend is initialized before returning
        async def mock_get_or_create(backend_type, session_id=None):
            if backend_type == BackendType.OPENAI.value:
                # Initialize the backend if not already initialized
                if not primary_backend.initialize_called:
                    await primary_backend.initialize()
                return primary_backend
            else:
                raise ValueError(f"Unexpected backend type: {backend_type}")

        service_with_simple_failover._backend_lifecycle_manager.get_or_create = (
            AsyncMock(side_effect=mock_get_or_create)
        )

        # Mock exception normalizer to return BackendError as-is
        def mock_normalize(exc, backend_type):
            if isinstance(exc, BackendError):
                return exc
            return BackendError(
                message=str(exc),
                backend_name=backend_type,
            )

        service_with_simple_failover._exception_normalizer.normalize = Mock(
            side_effect=mock_normalize
        )
        service_with_simple_failover._backend_completion_flow._exception_normalizer.normalize = Mock(
            side_effect=mock_normalize
        )

        # Act & Assert
        # Without a failure strategy, the error should be surfaced
        with pytest.raises(BackendError) as exc_info:
            await service_with_simple_failover.call_completion(chat_request)

        assert "Primary backend error" in str(exc_info.value)

        # Only the primary backend should have been called
        assert primary_backend.chat_completions_called

    @pytest.mark.asyncio
    async def test_complex_failover_first_attempt(
        self,
        service_with_complex_failover,
        chat_request_complex,
    ):
        """Test complex model-specific failover, first attempt succeeds."""
        # Arrange
        from src.core.services.failover_service import FailoverAttempt

        # Configure the stub coordinator with failover attempts for complex-model
        service_with_complex_failover._failover_coordinator.configure_attempts(
            "complex-model",
            [
                FailoverAttempt(backend=BackendType.ANTHROPIC.value, model="claude-2"),
                FailoverAttempt(
                    backend=BackendType.OPENROUTER.value, model="last-resort-model"
                ),
            ],
        )

        # Primary backend fails
        client1 = httpx.AsyncClient()
        primary_backend = MockBackend(client1)
        primary_backend.initialize = AsyncMock()
        primary_backend.chat_completions_mock.side_effect = BackendError(
            message="Primary backend error",
            backend_name=BackendType.OPENAI.value,
        )

        # First failover attempt succeeds
        client2 = httpx.AsyncClient()
        first_fallback = MockBackend(client2)
        first_fallback.initialize = AsyncMock()
        first_fallback.chat_completions_mock.return_value = ResponseEnvelope(
            content={
                "id": "claude-resp",
                "created": 123,
                "model": "claude-2",
                "choices": [],
            },
            headers={},
        )

        # Second failover never called
        client3 = httpx.AsyncClient()
        second_fallback = MockBackend(client3)
        second_fallback.initialize = AsyncMock()

        # Mock the lifecycle manager to return the appropriate backend
        async def mock_get_or_create(backend_type, session_id=None):
            if backend_type == BackendType.OPENAI.value:
                if not primary_backend.initialize_called:
                    await primary_backend.initialize()
                return primary_backend
            elif backend_type == BackendType.ANTHROPIC.value:
                if not first_fallback.initialize_called:
                    await first_fallback.initialize()
                return first_fallback
            elif backend_type == BackendType.OPENROUTER.value:
                if not second_fallback.initialize_called:
                    await second_fallback.initialize()
                return second_fallback
            else:
                raise ValueError(f"Unexpected backend type: {backend_type}")

        service_with_complex_failover._backend_lifecycle_manager.get_or_create = (
            AsyncMock(side_effect=mock_get_or_create)
        )

        # Mock exception normalizer to return exceptions as-is
        def mock_normalize(exc, backend_type):
            if isinstance(exc, BackendError | RateLimitExceededError | LLMProxyError):
                return exc
            return BackendError(
                message=str(exc),
                backend_name=backend_type,
            )

        service_with_complex_failover._exception_normalizer.normalize = Mock(
            side_effect=mock_normalize
        )
        service_with_complex_failover._backend_completion_flow._exception_normalizer.normalize = Mock(
            side_effect=mock_normalize
        )
        # Ensure the completion flow uses the mocked lifecycle manager
        service_with_complex_failover._backend_completion_flow._backend_invoker._backend_lifecycle_manager.get_or_create = AsyncMock(
            side_effect=mock_get_or_create
        )
        # Use the same model resolver mock from the fixture
        service_with_complex_failover._backend_completion_flow._request_preparer._backend_model_resolver = (
            service_with_complex_failover._backend_model_resolver
        )

        # Act
        response = await service_with_complex_failover.call_completion(
            chat_request_complex
        )

        # Assert
        # Complex failover goes directly to the configured attempts, skipping the primary backend
        assert first_fallback.chat_completions_called
        assert not second_fallback.chat_completions_called
        assert response.content["id"] == "claude-resp"
        assert response.content["model"] == "claude-2"

    @pytest.mark.asyncio
    async def test_complex_failover_second_attempt(
        self,
        service_with_complex_failover,
        chat_request_complex,
    ):
        """Test complex model-specific failover, second attempt succeeds after first fails."""
        # Arrange
        from src.core.services.failover_service import FailoverAttempt

        # Configure the stub coordinator with failover attempts for complex-model
        service_with_complex_failover._failover_coordinator.configure_attempts(
            "complex-model",
            [
                FailoverAttempt(backend=BackendType.ANTHROPIC.value, model="claude-2"),
                FailoverAttempt(
                    backend=BackendType.OPENROUTER.value, model="last-resort-model"
                ),
            ],
        )

        # Primary backend fails
        client1 = httpx.AsyncClient()
        primary_backend = MockBackend(client1)
        primary_backend.initialize = AsyncMock()
        primary_backend.chat_completions_mock.side_effect = ValueError(
            "Primary backend error"
        )

        # First failover attempt fails
        client2 = httpx.AsyncClient()
        first_fallback = MockBackend(client2)
        first_fallback.initialize = AsyncMock()
        first_fallback.chat_completions_mock.side_effect = ValueError(
            "First failover error"
        )

        # Second failover succeeds
        client3 = httpx.AsyncClient()
        second_fallback = MockBackend(client3)
        second_fallback.initialize = AsyncMock()
        second_fallback.chat_completions_mock.return_value = ResponseEnvelope(
            content={
                "id": "last-resort",
                "created": 123,
                "model": "last-resort-model",
                "choices": [],
            },
            headers={},
        )

        # Mock the lifecycle manager to return the appropriate backend
        async def mock_get_or_create(backend_type, session_id=None):
            if backend_type == BackendType.OPENAI.value:
                if not primary_backend.initialize_called:
                    await primary_backend.initialize()
                return primary_backend
            elif backend_type == BackendType.ANTHROPIC.value:
                if not first_fallback.initialize_called:
                    await first_fallback.initialize()
                return first_fallback
            elif backend_type == BackendType.OPENROUTER.value:
                if not second_fallback.initialize_called:
                    await second_fallback.initialize()
                return second_fallback
            else:
                raise ValueError(f"Unexpected backend type: {backend_type}")

        service_with_complex_failover._backend_lifecycle_manager.get_or_create = (
            AsyncMock(side_effect=mock_get_or_create)
        )

        # Mock exception normalizer to return exceptions as-is
        def mock_normalize(exc, backend_type):
            if isinstance(exc, BackendError | RateLimitExceededError | LLMProxyError):
                return exc
            return BackendError(
                message=str(exc),
                backend_name=backend_type,
            )

        service_with_complex_failover._exception_normalizer.normalize = Mock(
            side_effect=mock_normalize
        )
        service_with_complex_failover._backend_completion_flow._exception_normalizer.normalize = Mock(
            side_effect=mock_normalize
        )
        # Ensure the completion flow uses the mocked lifecycle manager
        service_with_complex_failover._backend_completion_flow._backend_invoker._backend_lifecycle_manager.get_or_create = AsyncMock(
            side_effect=mock_get_or_create
        )
        # Use the same model resolver mock from the fixture
        service_with_complex_failover._backend_completion_flow._request_preparer._backend_model_resolver = (
            service_with_complex_failover._backend_model_resolver
        )

        # Act
        response = await service_with_complex_failover.call_completion(
            chat_request_complex
        )

        # Assert
        # Complex failover goes directly to the configured attempts
        assert first_fallback.chat_completions_called
        assert second_fallback.chat_completions_called
        assert response.content["id"] == "last-resort"
        assert response.content["model"] == "last-resort-model"

    @pytest.mark.asyncio
    async def test_complex_failover_all_fail(
        self,
        service_with_complex_failover,
        chat_request_complex,
    ):
        """Test complex model-specific failover when all attempts fail."""
        # Arrange
        # Primary backend fails
        client1 = httpx.AsyncClient()
        primary_backend = MockBackend(client1)
        primary_backend.initialize = AsyncMock()
        primary_backend.chat_completions_mock.side_effect = ValueError(
            "Primary backend error"
        )

        # First failover attempt fails
        client2 = httpx.AsyncClient()
        first_fallback = MockBackend(client2)
        first_fallback.initialize = AsyncMock()
        first_fallback.chat_completions_mock.side_effect = ValueError(
            "First failover error"
        )

        # Second failover fails
        client3 = httpx.AsyncClient()
        second_fallback = MockBackend(client3)
        second_fallback.initialize = AsyncMock()
        second_fallback.chat_completions_mock.side_effect = ValueError(
            "Second failover error"
        )

        # Configure the stub coordinator with failover attempts for complex-model
        from src.core.services.failover_service import FailoverAttempt

        service_with_complex_failover._failover_coordinator.configure_attempts(
            "complex-model",
            [
                FailoverAttempt(backend=BackendType.ANTHROPIC.value, model="claude-2"),
                FailoverAttempt(
                    backend=BackendType.OPENROUTER.value, model="last-resort-model"
                ),
            ],
        )

        # Mock the lifecycle manager to return the appropriate backend
        async def mock_get_or_create(backend_type, session_id=None):
            if backend_type == BackendType.OPENAI.value:
                if not primary_backend.initialize_called:
                    await primary_backend.initialize()
                return primary_backend
            elif backend_type == BackendType.ANTHROPIC.value:
                if not first_fallback.initialize_called:
                    await first_fallback.initialize()
                return first_fallback
            elif backend_type == BackendType.OPENROUTER.value:
                if not second_fallback.initialize_called:
                    await second_fallback.initialize()
                return second_fallback
            else:
                raise ValueError(f"Unexpected backend type: {backend_type}")

        service_with_complex_failover._backend_lifecycle_manager.get_or_create = (
            AsyncMock(side_effect=mock_get_or_create)
        )

        # Mock exception normalizer to return exceptions as-is
        def mock_normalize(exc, backend_type):
            if isinstance(exc, BackendError | RateLimitExceededError | LLMProxyError):
                return exc
            return BackendError(
                message=str(exc),
                backend_name=backend_type,
            )

        service_with_complex_failover._exception_normalizer.normalize = Mock(
            side_effect=mock_normalize
        )
        service_with_complex_failover._backend_completion_flow._exception_normalizer.normalize = Mock(
            side_effect=mock_normalize
        )
        # Ensure the completion flow uses the mocked lifecycle manager
        service_with_complex_failover._backend_completion_flow._backend_invoker._backend_lifecycle_manager.get_or_create = AsyncMock(
            side_effect=mock_get_or_create
        )
        # Use the same model resolver mock from the fixture
        service_with_complex_failover._backend_completion_flow._request_preparer._backend_model_resolver = (
            service_with_complex_failover._backend_model_resolver
        )

        # Act & Assert
        with pytest.raises(BackendError) as exc_info:
            await service_with_complex_failover.call_completion(chat_request_complex)

        # Verify that all failover attempts were called
        assert first_fallback.chat_completions_called
        assert second_fallback.chat_completions_called
        # The error message should indicate backend failure
        assert (
            "backend" in str(exc_info.value).lower()
            or "fail" in str(exc_info.value).lower()
        )
