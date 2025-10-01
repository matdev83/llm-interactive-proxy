"""
Test-specific initialization stages.

This module provides stages that are specifically designed for testing,
replacing production services with mocks and test doubles.
"""

from __future__ import annotations

import contextlib
import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.interfaces.di_interface import IServiceProvider
from src.core.services.backend_service import BackendService as _BackendService

from .base import InitializationStage

logger = logging.getLogger(__name__)


_ORIGINAL_BACKEND_CALL_COMPLETION = _BackendService.call_completion


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
                request = (
                    kwargs.get("request")
                    or kwargs.get("request_data")
                    or (args[0] if args else None)
                )

                # Check if there's a configured mock backend that we should delegate to
                # This allows tests to inject their own mock responses
                try:
                    from typing import cast

                    from src.core.services.backend_service import BackendService

                    provider = services.build_service_provider()
                    backend_service = cast(BackendService, provider.get_required_service(IBackendService))  # type: ignore[type-abstract]

                    # Check if the backend service has test-configured backends
                    if (
                        hasattr(backend_service, "_backends")
                        and "openrouter" in backend_service._backends
                    ):
                        backend = backend_service._backends["openrouter"]

                        if hasattr(backend, "chat_completions"):
                            chat_completions = backend.chat_completions

                            if (
                                hasattr(chat_completions, "side_effect")
                                and chat_completions.side_effect is not None
                            ):
                                side_effect = chat_completions.side_effect

                                if callable(side_effect):
                                    result = await side_effect(*args, **kwargs)
                                    # Cast the result to the expected type
                                    if isinstance(
                                        result,
                                        ResponseEnvelope | StreamingResponseEnvelope,
                                    ):
                                        return result
                                    # If it's a dict, wrap it in a ResponseEnvelope
                                    if isinstance(result, dict):
                                        return ResponseEnvelope(
                                            content=result,
                                            headers={
                                                "content-type": "application/json"
                                            },
                                            status_code=200,
                                        )
                                    return result  # type: ignore[no-any-return]
                                else:
                                    # side_effect is a list/iterator of responses
                                    try:
                                        # Try to get the next response from the side_effect
                                        response = next(side_effect)

                                        # Wrap the response in a ResponseEnvelope if it's not already
                                        if isinstance(response, dict):
                                            return ResponseEnvelope(
                                                content=response,
                                                headers={
                                                    "content-type": "application/json"
                                                },
                                                status_code=200,
                                            )
                                        return response  # type: ignore[no-any-return]
                                    except StopIteration:
                                        # Iterator exhausted, fall back to default behavior
                                        pass
                            elif (
                                hasattr(chat_completions, "return_value")
                                and chat_completions.return_value is not None
                            ):
                                return_value = chat_completions.return_value

                                # Wrap the response in a ResponseEnvelope if it's not already
                                if isinstance(return_value, dict):
                                    return ResponseEnvelope(
                                        content=return_value,
                                        headers={"content-type": "application/json"},
                                        status_code=200,
                                    )
                                return return_value  # type: ignore[no-any-return]
                except Exception:
                    # If we can't get the backend or it fails, fall back to default behavior
                    pass

                # Check if tools are requested
                tools = getattr(request, "tools", None) if request else None
                tool_choice = getattr(request, "tool_choice", None) if request else None
                has_tools = bool(tools or tool_choice)

                # Create message content based on whether tools are requested
                if has_tools:
                    message_content = {
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
                    }
                    finish_reason = "tool_calls"
                else:
                    # Check if JSON schema is requested for structured output
                    json_schema = None

                    if (
                        request
                        and hasattr(request, "extra_body")
                        and request.extra_body
                    ):
                        # Handle nested extra_body structure
                        extra_body = request.extra_body
                        if isinstance(extra_body, dict) and "extra_body" in extra_body:
                            extra_body = extra_body["extra_body"]
                        response_format = (
                            extra_body.get("response_format")
                            if isinstance(extra_body, dict)
                            else None
                        )
                        if (
                            response_format
                            and response_format.get("type") == "json_schema"
                        ):
                            json_schema_info = response_format.get("json_schema", {})
                            # Handle multiple field names for schema definition
                            json_schema = (
                                json_schema_info.get("schema")
                                or json_schema_info.get("schema_dict")
                                or json_schema_info.get("json_schema_def")
                            )

                    if json_schema:
                        # Generate a simple JSON response that matches the schema
                        import json

                        def generate_mock_value(
                            schema: dict[str, Any], prop_name: str = ""
                        ) -> Any:
                            """Generate mock data based on JSON schema type."""
                            prop_type = schema.get("type", "string")

                            if prop_type == "string":
                                # Handle enum values
                                if "enum" in schema:
                                    return schema["enum"][0]  # Use first enum value
                                return (
                                    f"Mock {prop_name}" if prop_name else "Mock string"
                                )
                            elif prop_type == "number":
                                return 42.0
                            elif prop_type == "integer":
                                return 42
                            elif prop_type == "boolean":
                                return True
                            elif prop_type == "array":
                                # Generate a simple array with one mock item
                                items_schema = schema.get("items", {"type": "string"})
                                mock_item = generate_mock_value(
                                    items_schema, f"{prop_name}_item"
                                )
                                return [mock_item]
                            elif prop_type == "object":
                                # Generate a simple object
                                if "properties" in schema:
                                    mock_obj = {}
                                    for obj_prop_name, obj_prop_schema in schema[
                                        "properties"
                                    ].items():
                                        mock_obj[obj_prop_name] = generate_mock_value(
                                            obj_prop_schema, obj_prop_name
                                        )
                                    return mock_obj
                                else:
                                    return {"mock_key": "mock_value"}
                            else:
                                return (
                                    f"mock {prop_name}" if prop_name else "mock value"
                                )

                        if json_schema.get("properties"):
                            mock_content: dict[str, Any] = {}
                            for prop_name, prop_schema in json_schema.get(
                                "properties", {}
                            ).items():
                                mock_content[prop_name] = generate_mock_value(
                                    prop_schema, prop_name
                                )
                        else:
                            mock_content = {"message": "Mock response"}

                        message_content = {
                            "role": "assistant",
                            "content": json.dumps(mock_content, indent=2),
                        }
                    else:
                        message_content = {
                            "role": "assistant",
                            "content": "Mock response from test backend",
                        }
                    finish_reason = "stop"

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
                            "message": message_content,
                            "finish_reason": finish_reason,
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 15,
                        "total_tokens": 25,
                    },
                }

                # Handle streaming requests
                stream_value = getattr(request, "stream", False) if request else False
                # Also check stream parameter directly from kwargs
                if not stream_value and "stream" in kwargs:
                    stream_value = kwargs.get("stream", False)
                if stream_value:
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

                # If tests patched BackendService.call_completion, honor the patched implementation
                try:
                    patched_call = _BackendService.call_completion
                except Exception:
                    patched_call = None

                if (
                    patched_call is not None
                    and patched_call is not _ORIGINAL_BACKEND_CALL_COMPLETION
                ):
                    return await patched_call(*args, **kwargs)  # type: ignore[misc]

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

                    try:
                        client = httpx.AsyncClient(
                            http2=True,
                            timeout=httpx.Timeout(
                                connect=10.0, read=60.0, write=60.0, pool=60.0
                            ),
                            limits=httpx.Limits(
                                max_connections=100, max_keepalive_connections=20
                            ),
                            trust_env=False,
                        )
                    except ImportError:
                        client = httpx.AsyncClient(
                            http2=False,
                            timeout=httpx.Timeout(
                                connect=10.0, read=60.0, write=60.0, pool=60.0
                            ),
                            limits=httpx.Limits(
                                max_connections=100, max_keepalive_connections=20
                            ),
                            trust_env=False,
                        )
                    real_backend = AnthropicBackend(
                        client, AppConfig(), translation_service
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

                        try:
                            client = httpx.AsyncClient(
                                http2=True,
                                timeout=httpx.Timeout(
                                    connect=10.0, read=60.0, write=60.0, pool=60.0
                                ),
                                limits=httpx.Limits(
                                    max_connections=100, max_keepalive_connections=20
                                ),
                                trust_env=False,
                            )
                        except ImportError:
                            client = httpx.AsyncClient(
                                http2=False,
                                timeout=httpx.Timeout(
                                    connect=10.0, read=60.0, write=60.0, pool=60.0
                                ),
                                limits=httpx.Limits(
                                    max_connections=100, max_keepalive_connections=20
                                ),
                                trust_env=False,
                            )
                        real_backend = AnthropicBackend(
                            client, AppConfig(), translation_service
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

            try:
                httpx_client = httpx.AsyncClient(
                    http2=True,
                    timeout=httpx.Timeout(
                        connect=10.0, read=60.0, write=60.0, pool=60.0
                    ),
                    limits=httpx.Limits(
                        max_connections=100, max_keepalive_connections=20
                    ),
                    trust_env=False,
                )
            except ImportError:
                httpx_client = httpx.AsyncClient(
                    http2=False,
                    timeout=httpx.Timeout(
                        connect=10.0, read=60.0, write=60.0, pool=60.0
                    ),
                    limits=httpx.Limits(
                        max_connections=100, max_keepalive_connections=20
                    ),
                    trust_env=False,
                )
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

                # Get optional failover coordinator
                failover_coordinator: IFailoverCoordinator | None = None
                with contextlib.suppress(Exception):
                    from src.core.interfaces.failover_interface import (
                        IFailoverCoordinator,
                    )

                    failover_coordinator = provider.get_service(
                        cast(type, IFailoverCoordinator)
                    )

                # Get wire capture service
                wire_capture: IWireCapture | None = None
                with contextlib.suppress(Exception):
                    from src.core.interfaces.wire_capture_interface import IWireCapture

                    wire_capture = provider.get_service(cast(type, IWireCapture))

                return BackendService(
                    backend_factory,
                    rate_limiter,
                    app_config,
                    provider.get_required_service(SessionService),
                    app_state,
                    backend_config_provider=backend_config_provider,
                    failover_coordinator=failover_coordinator,
                    wire_capture=wire_capture,
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
