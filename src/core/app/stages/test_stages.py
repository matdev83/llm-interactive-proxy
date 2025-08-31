"""
Test-specific initialization stages.

This module provides stages that are specifically designed for testing,
replacing production services with mocks and test doubles.
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.interfaces.di_interface import IServiceProvider

from .base import InitializationStage

logger = logging.getLogger(__name__)


class MockBackendStage(InitializationStage):
    """
    Test stage that provides mock backend services.

    This stage replaces real backend services with mocks that return
    predictable responses for testing.
    """

    @property
    def name(self) -> str:
        return "backends"

    def get_dependencies(self) -> list[str]:
        return ["infrastructure"]

    def get_description(self) -> str:
        return "Register mock backend services for testing"

    async def execute(self, services: ServiceCollection, config: AppConfig) -> None:
        """Register mock backend services."""
        logger.info("Initializing mock backend services...")

        # Register mock backend config provider first
        self._register_backend_config_provider(services)

        # Import required classes for service checks

        # Always register mock services for test environments, overwriting real ones
        self._register_mock_backend_factory(services)
        logger.debug("Registered mock backend factory")

        self._register_mock_backend_service(services)
        logger.debug("Registered mock backend service")

        # Override session service to ensure real sessions instead of mocks
        self._override_session_service_for_test_compatibility(services)

        # Skip real backend service registration in test environment
        # The mock backend service should be sufficient for testing

        # Override session service to ensure real sessions instead of mocks
        self._override_session_service_for_test_compatibility(services)

        logger.info("Mock backend services initialized successfully")

    def _register_backend_config_provider(self, services: ServiceCollection) -> None:
        """Register a mock backend configuration provider."""
        try:
            from typing import cast

            from src.core.interfaces.backend_config_provider_interface import (
                IBackendConfigProvider,
            )
            from src.core.services.backend_config_provider import BackendConfigProvider

            # Create a mock backend config provider that returns the configuration
            # from the app_config
            def backend_config_provider_factory(
                provider: IServiceProvider,
            ) -> BackendConfigProvider:
                """Factory function for creating BackendConfigProvider."""
                app_config = provider.get_required_service(AppConfig)
                return BackendConfigProvider(app_config)

            # Register interface with factory
            services.add_singleton(
                cast(type, IBackendConfigProvider),
                implementation_factory=backend_config_provider_factory,
            )

            logger.debug("Registered mock backend config provider")
        except ImportError as e:
            logger.warning(f"Could not register mock backend config provider: {e}")

    def _register_mock_backend_service(self, services: ServiceCollection) -> None:
        """Register a comprehensive mock backend service."""
        try:
            from src.core.domain.responses import (
                ResponseEnvelope,
                StreamingResponseEnvelope,
            )
            from src.core.interfaces.backend_service_interface import IBackendService

            # Create mock backend service
            mock_backend_service = MagicMock(spec=IBackendService)

            # Mock chat completion method
            async def mock_chat_completions(
                *args: Any, **kwargs: Any
            ) -> ResponseEnvelope | StreamingResponseEnvelope:
                """Mock chat completions that returns a standard response."""
                request = kwargs.get("request_data") or (args[0] if args else None)

                response_data = {
                    "id": "mock-response-1",
                    "object": "chat.completion",
                    "created": 1234567890,
                    "model": (
                        getattr(request, "model", "mock-model")
                        if request
                        else "mock-model"
                    ),
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": "Mock response from test backend",
                                "tool_calls": [
                                    {
                                        "id": "call_mock_123",
                                        "type": "function",
                                        "function": {
                                            "name": "get_weather",
                                            "arguments": '{"location": "New York"}',
                                        },
                                    }
                                ],
                            },
                            "finish_reason": "tool_calls",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 15,
                        "total_tokens": 25,
                    },
                }

                # Handle streaming requests
                if request and getattr(request, "stream", False):
                    logger.info(
                        f"Mock backend returning streaming response for model: {response_data['model']}"
                    )
                    from src.core.domain.streaming_test_helpers import (
                        create_streaming_generator,
                    )

                    # Define what to return from the mock stream
                    chunks = ["Mock ", "streaming ", "response"]

                    # Use the helper function that properly creates a streaming generator
                    content_generator = create_streaming_generator(
                        model=str(response_data["model"]),
                        content=chunks,
                        chunk_delay_seconds=0.01,
                    )

                    streaming_envelope = StreamingResponseEnvelope(
                        content=content_generator,  # type: ignore[arg-type]
                        media_type="text/event-stream",
                        headers={"content-type": "text/event-stream"},
                    )
                    logger.info(f"Created streaming envelope: {streaming_envelope}")
                    return streaming_envelope
                else:
                    logger.info(
                        f"Mock backend returning JSON response for model: {response_data['model']}"
                    )

                return ResponseEnvelope(
                    content=response_data,
                    headers={"content-type": "application/json"},
                    status_code=200,
                )

            # Configure mock methods
            mock_backend_service.process_request = AsyncMock(
                side_effect=mock_chat_completions
            )

            async def _call_completion_delegate(*args: Any, **kwargs: Any) -> Any:
                # Try to delegate to a real Anthropic connector if available and
                # possibly patched by tests (so patching class methods will be
                # observed). If that fails, fall back to the canned mock behavior.
                request = (
                    kwargs.get("request")
                    or kwargs.get("request_data")
                    or (args[0] if args else None)
                )

                try:
                    # Attempt to import Anthropic connector and call its method.
                    # If tests patched AnthropicBackend.chat_completions, their
                    # AsyncMock will be invoked here and awaited.
                    import httpx

                    from src.connectors.anthropic import AnthropicBackend
                    from src.core.config.app_config import AppConfig
                    from src.core.services.translation_service import TranslationService

                    # Try to get existing translation service from services
                    translation_service = None
                    try:
                        # Build a service provider to get the translation service
                        provider = services.build_service_provider()
                        translation_service = provider.get_required_service(
                            TranslationService
                        )
                    except Exception:
                        translation_service = TranslationService()

                    real_backend = AnthropicBackend(
                        httpx.AsyncClient(), AppConfig(), translation_service
                    )
                    # Call connector using a minimal processed_messages list and
                    # the request.model as effective_model when available.
                    processed_messages: list[dict[str, str]] = []
                    effective_model = (
                        getattr(request, "model", "mock-model")
                        if request
                        else "mock-model"
                    )
                    # Ensure request is not None before passing to chat_completions
                    if request is not None:
                        return await real_backend.chat_completions(
                            request, processed_messages, effective_model
                        )
                    else:
                        # Fall back to global mock behavior if request is None
                        return await mock_chat_completions(*args, **kwargs)
                except Exception:
                    # Fall back to global mock behavior
                    return await mock_chat_completions(*args, **kwargs)

            mock_backend_service.call_completion = AsyncMock(
                side_effect=_call_completion_delegate
            )
            mock_backend_service.chat_completions = AsyncMock(
                side_effect=mock_chat_completions
            )
            mock_backend_service.get_available_models = AsyncMock(
                return_value=[
                    "mock-model-1",
                    "mock-model-2",
                    "mock-gpt-4",
                    "mock-claude-3",
                ]
            )
            mock_backend_service.validate_backend = AsyncMock(return_value=(True, None))
            mock_backend_service.validate_backend_and_model = AsyncMock(
                return_value=(True, None)
            )
            mock_backend_service.get_backend_status = AsyncMock(
                return_value={"status": "healthy"}
            )

            # Add _backends attribute for caching
            mock_backend_service._backends = {}

            # Add _get_or_create_backend method that respects test-specific mocks
            async def mock_get_or_create_backend(backend_type: str) -> Any:
                from src.connectors.base import LLMBackend

                # First check if a test has injected a specific backend implementation
                # This allows tests to override specific backends while using global mocks for others
                if (
                    hasattr(mock_backend_service, "_backends")
                    and backend_type in mock_backend_service._backends
                ):
                    # Test has provided a specific backend - use it
                    return mock_backend_service._backends[backend_type]

                # Check if backend was already created and cached
                if not hasattr(mock_backend_service, "_backend_cache"):
                    mock_backend_service._backend_cache = {}

                if backend_type in mock_backend_service._backend_cache:
                    return mock_backend_service._backend_cache[backend_type]

                # Try to create a real backend instance when possible (helps tests
                # that patch connector implementations, e.g. patching
                # src.connectors.anthropic.AnthropicBackend.chat_completions).
                try:
                    if backend_type == "anthropic":
                        import httpx

                        from src.connectors.anthropic import AnthropicBackend
                        from src.core.config.app_config import AppConfig
                        from src.core.services.translation_service import (
                            TranslationService,
                        )

                        # Try to get existing translation service from services
                        translation_service = None
                        try:
                            # Build a service provider to get the translation service
                            provider = services.build_service_provider()
                            translation_service = provider.get_required_service(
                                TranslationService
                            )
                        except Exception:
                            translation_service = TranslationService()

                        real_backend = AnthropicBackend(
                            httpx.AsyncClient(), AppConfig(), translation_service
                        )
                        # If the connector was patched in tests, its methods will
                        # already reflect the patch. Cache and return the real
                        # backend so tests that patch connector class methods
                        # observe calls.
                        mock_backend_service._backend_cache[backend_type] = real_backend
                        return real_backend
                except Exception:
                    # Fall back to mock backend when real instantiation fails
                    pass

                # Create new mock backend with the global mock behavior
                mock_backend = MagicMock(spec=LLMBackend)
                mock_backend.chat_completions = AsyncMock(
                    side_effect=mock_chat_completions
                )
                mock_backend.validate = AsyncMock(return_value=(True, None))
                mock_backend.get_available_models = AsyncMock(
                    return_value=["mock-model"]
                )
                mock_backend.available_models = ["mock-model"]

                # Cache in our internal cache (not _backends which tests use)
                mock_backend_service._backend_cache[backend_type] = mock_backend
                return mock_backend

            mock_backend_service._get_or_create_backend = AsyncMock(
                side_effect=mock_get_or_create_backend
            )

            # Always register the mock service instance to ensure it overrides any
            # previously registered real service.
            services.add_instance(IBackendService, mock_backend_service)
            logger.debug("Registered mock backend service with full method coverage")
        except ImportError as e:
            logger.warning(f"Could not register mock backend service: {e}")

    def _register_mock_backend_factory(self, services: ServiceCollection) -> None:
        """Register a mock backend factory."""
        try:
            from src.connectors.base import LLMBackend
            from src.core.services.backend_factory import BackendFactory

            # Create mock backend factory
            from src.core.services.translation_service import TranslationService

            # Try to get existing translation service or create a new one
            translation_service = TranslationService()

            mock_factory = MagicMock(spec=BackendFactory)
            mock_factory.translation_service = translation_service or MagicMock(
                spec=TranslationService
            )

            # Create mock backend instance
            mock_backend = MagicMock(spec=LLMBackend)
            mock_backend.chat_completions = AsyncMock()
            mock_backend.validate = AsyncMock(return_value=(True, None))
            mock_backend.get_available_models = AsyncMock(return_value=["mock-model"])
            mock_backend.available_models = ["mock-model"]

            # Configure factory methods and properties
            mock_factory.create_backend = MagicMock(return_value=mock_backend)
            mock_factory.ensure_backend = AsyncMock(return_value=mock_backend)
            mock_factory.initialize_backend = AsyncMock()

            # Add _client attribute to match real BackendFactory for tests
            # that directly access this attribute
            import httpx

            httpx_client = httpx.AsyncClient()
            mock_factory._client = httpx_client

            # Always register the mock factory instance to ensure it overrides any
            # previously registered real factory.
            services.add_instance(BackendFactory, mock_factory)
            logger.debug("Registered mock backend factory")
        except ImportError as e:
            logger.warning(f"Could not register mock backend factory: {e}")

    def _register_backend_service(self, services: ServiceCollection) -> None:
        """Register BackendService with the proper dependencies."""
        try:
            from typing import cast

            from src.core.interfaces.backend_config_provider_interface import (
                IBackendConfigProvider,
            )
            from src.core.interfaces.backend_service_interface import IBackendService
            from src.core.services.backend_service import BackendService
            from src.core.services.rate_limiter_service import RateLimiter

            # Create a rate limiter instance directly for the factory
            # (will be retrieved via service provider)

            # Function to create BackendService instance
            def backend_service_factory(provider: IServiceProvider) -> BackendService:
                from src.core.services.backend_factory import BackendFactory
                from src.core.services.session_service_impl import (
                    SessionService,  # Added import
                )

                backend_factory = provider.get_required_service(BackendFactory)
                app_config = provider.get_required_service(AppConfig)
                backend_config_provider: IBackendConfigProvider = (
                    provider.get_required_service(cast(type, IBackendConfigProvider))
                )
                rate_limiter = provider.get_required_service(RateLimiter)
                app_state: IApplicationState = provider.get_required_service(
                    cast(type, IApplicationState)
                )

                return BackendService(
                    backend_factory,
                    rate_limiter,
                    app_config,
                    provider.get_required_service(SessionService),
                    app_state,
                    backend_config_provider=backend_config_provider,
                )

            # Register BackendService with factory
            services.add_singleton(
                BackendService, implementation_factory=backend_service_factory
            )

            # Register interface binding
            services.add_singleton(
                cast(type, IBackendService),
                implementation_factory=backend_service_factory,
            )

            logger.debug("Registered BackendService with all dependencies")
        except ImportError as e:
            logger.warning(f"Could not register mock backend factory: {e}")

    def _override_session_service_for_test_compatibility(
        self, services: ServiceCollection
    ) -> None:
        """Override session service to ensure it returns real Session objects instead of mocks.

        This prevents the 'coroutine was never awaited' warnings that occur when
        session service methods return AsyncMock instead of real Session objects.
        """
        try:
            from typing import cast

            from src.core.interfaces.repositories_interface import ISessionRepository
            from src.core.interfaces.session_service_interface import ISessionService
            from src.core.services.session_service_impl import SessionService

            def session_service_factory(provider: IServiceProvider) -> SessionService:
                """Factory function for creating SessionService with real session repository."""
                repo: ISessionRepository = provider.get_required_service(
                    cast(type, ISessionRepository)
                )
                return SessionService(repo)

            # Override the session service registration to ensure it returns real Session objects
            services.add_singleton(
                SessionService, implementation_factory=session_service_factory
            )
            services.add_singleton(
                cast(type, ISessionService),
                implementation_factory=session_service_factory,
            )

            logger.debug("Overrode session service to ensure real Session objects")
        except ImportError as e:
            logger.warning(f"Could not override session service: {e}")


class MinimalTestStage(InitializationStage):
    """
    Minimal test stage that provides only essential services.

    This stage is useful for unit tests that only need basic functionality
    without the overhead of full application initialization.
    """

    @property
    def name(self) -> str:
        return "minimal_test"

    def get_dependencies(self) -> list[str]:
        return ["core_services"]

    def get_description(self) -> str:
        return "Register minimal services for lightweight testing"

    async def execute(self, services: ServiceCollection, config: AppConfig) -> None:
        """Register minimal test services."""
        logger.info("Initializing minimal test services...")

        # Register mock command service
        self._register_mock_command_service(services)

        # Register mock request processor
        self._register_mock_request_processor(services)

        logger.info("Minimal test services initialized successfully")

    def _register_mock_command_service(self, services: ServiceCollection) -> None:
        """Register a simple mock command service."""
        try:
            from src.core.interfaces.command_service_interface import ICommandService

            mock_command_service = MagicMock(spec=ICommandService)
            mock_command_service.process_command = AsyncMock(return_value=None)
            mock_command_service.is_command = MagicMock(return_value=False)

            services.add_instance(ICommandService, mock_command_service)

            logger.debug("Registered mock command service")
        except ImportError as e:
            logger.warning(f"Could not register mock command service: {e}")

    def _register_mock_request_processor(self, services: ServiceCollection) -> None:
        """Register a simple mock request processor."""
        try:
            from src.core.domain.responses import ResponseEnvelope
            from src.core.interfaces.request_processor_interface import (
                IRequestProcessor,
            )

            mock_request_processor = MagicMock(spec=IRequestProcessor)

            async def mock_process(*args: Any, **kwargs: Any) -> ResponseEnvelope:
                return ResponseEnvelope(
                    content={"message": "Mock response"},
                    headers={"content-type": "application/json"},
                    status_code=200,
                )

            mock_request_processor.process_request = AsyncMock(side_effect=mock_process)

            services.add_instance(IRequestProcessor, mock_request_processor)

            logger.debug("Registered mock request processor")
        except ImportError as e:
            logger.warning(f"Could not register mock request processor: {e}")


class RealBackendTestStage(InitializationStage):
    """
    Test stage that provides real backend services for HTTP mocking tests.

    This stage is used by tests that need to make real HTTP calls
    but want to mock the HTTP responses (e.g., using HTTPXMock).
    """

    @property
    def name(self) -> str:
        return "backends"

    def get_dependencies(self) -> list[str]:
        return ["infrastructure"]

    def get_description(self) -> str:
        return "Register real backend services for HTTP mocking tests"

    async def execute(self, services: ServiceCollection, config: AppConfig) -> None:
        """Register real backend services for HTTP mocking."""
        logger.info("Initializing real backend services for HTTP mocking tests...")

        # Import the real backend stage and use its registration methods
        from src.core.app.stages.backend import BackendStage

        # Create a real backend stage and execute it
        real_backend_stage = BackendStage()
        await real_backend_stage.execute(services, config)

        # Override session service to ensure real sessions instead of mocks
        self._override_session_service_for_test_compatibility(services)

        logger.info("Real backend services for HTTP mocking initialized successfully")

    def _override_session_service_for_test_compatibility(
        self, services: ServiceCollection
    ) -> None:
        """Override session service to ensure it returns real Session objects instead of mocks.

        This prevents the 'coroutine was never awaited' warnings that occur when
        session service methods return AsyncMock instead of real Session objects.
        """
        try:
            from typing import cast

            from src.core.interfaces.repositories_interface import ISessionRepository
            from src.core.interfaces.session_service_interface import ISessionService
            from src.core.services.session_service_impl import SessionService

            def session_service_factory(provider: IServiceProvider) -> SessionService:
                """Factory function for creating SessionService with real session repository."""
                repo: ISessionRepository = provider.get_required_service(
                    cast(type, ISessionRepository)
                )
                return SessionService(repo)

            # Override the session service registration to ensure it returns real Session objects
            services.add_singleton(
                SessionService, implementation_factory=session_service_factory
            )
            services.add_singleton(
                cast(type, ISessionService),
                implementation_factory=session_service_factory,
            )

            logger.debug("Overrode session service to ensure real Session objects")
        except ImportError as e:
            logger.warning(f"Could not override session service: {e}")


class CustomTestStage(InitializationStage):
    """
    Customizable test stage that allows injection of specific services.

    This stage is useful for tests that need to inject specific mock
    implementations or test doubles.
    """

    def __init__(
        self,
        name: str,
        services_to_register: dict,
        dependencies: list[str] | None = None,
    ):
        """
        Initialize custom test stage.

        Args:
            name: Name for this stage
            services_to_register: Dict mapping service types to instances
            dependencies: List of stage dependencies
        """
        self._stage_name = name
        self._services_to_register = services_to_register
        self._dependencies = dependencies or []

    @property
    def name(self) -> str:
        return self._stage_name

    def get_dependencies(self) -> list[str]:
        return self._dependencies

    def get_description(self) -> str:
        return f"Custom test stage: {self._stage_name}"

    async def execute(self, services: ServiceCollection, config: AppConfig) -> None:
        """Register custom services."""
        logger.info(f"Initializing custom test stage: {self._stage_name}")

        for service_type, instance in self._services_to_register.items():
            services.add_instance(service_type, instance)
            logger.debug(f"Registered custom service: {service_type.__name__}")

        logger.info(f"Custom test stage '{self._stage_name}' initialized successfully")
