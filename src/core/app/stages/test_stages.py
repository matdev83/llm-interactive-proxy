"""
Test-specific initialization stages.

This module provides stages that are specifically designed for testing,
replacing production services with mocks and test doubles.
"""

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock

from src.core.app.stages.base import InitializationStage
from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.interfaces.backend_factory_interface import IBackendFactory
from src.core.interfaces.di_interface import IServiceProvider
from src.core.interfaces.translation_service_interface import ITranslationService
from src.core.services.backend_factory import BackendFactory
from src.core.services.backend_service import BackendService as _BackendService
from src.core.services.translation_service import TranslationService

logger = logging.getLogger(__name__)


_ORIGINAL_BACKEND_CALL_COMPLETION = _BackendService.call_completion


if TYPE_CHECKING:
    import httpx


class BaseTestBackendStage(InitializationStage):
    """Base class for test stages that provide backend services."""

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

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Overrode session service to ensure real Session objects")
        except ImportError as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning("Could not override session service: %s", e)


class MockBackendStage(BaseTestBackendStage):
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
        if logger.isEnabledFor(logging.INFO):
            logger.info("Initializing mock backend services...")

        # Register backend services (including TranslationService) via backend registrar
        # This ensures TranslationService is available before we try to use it
        from src.core.di.registrations import backend

        backend.register(services, config)

        # Register mock backend config provider first
        self._register_backend_config_provider(services)

        # Get translation service (now registered by backend registrar)
        provider = services.build_service_provider()
        translation_service: TranslationService = provider.get_required_service(
            TranslationService
        )

        # Register mock backend factory first before trying to resolve it
        self._register_mock_backend_factory(services, translation_service)
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Registered mock backend factory")

        # Rebuild the provider to include the newly registered mock factory
        provider = services.build_service_provider()
        backend_factory: BackendFactory = provider.get_required_service(BackendFactory)

        self._register_mock_backend_service(
            services, config, backend_factory, translation_service
        )
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Registered mock backend service")

        # Override session service to ensure real sessions instead of mocks
        self._override_session_service_for_test_compatibility(services)

        # Skip real backend service registration in test environment
        # The mock backend service should be sufficient for testing

        if logger.isEnabledFor(logging.INFO):
            logger.info("Mock backend services initialized successfully")

    def _resolve_httpx_client(
        self, services: ServiceCollection
    ) -> httpx.AsyncClient | None:
        """Try to resolve a shared httpx.AsyncClient from the DI container."""
        try:
            import httpx
        except ImportError:
            return None

        with contextlib.suppress(Exception):
            provider = services.build_service_provider()
            client = provider.get_service(httpx.AsyncClient)
            if client is not None:
                return client
        return None

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

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Registered mock backend config provider")
        except ImportError as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning("Could not register mock backend config provider: %s", e)

    def _register_mock_backend_service(
        self,
        services: ServiceCollection,
        config: AppConfig,
        backend_factory: IBackendFactory,
        translation_service: ITranslationService,
    ) -> None:
        """Register a comprehensive mock backend service."""
        try:
            from src.connectors.base import LLMBackend
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

                # Check if we should delegate to a real (but patched) backend
                try:
                    backend_type = None
                    effective_model = None
                    if (
                        request
                        and hasattr(request, "model")
                        and isinstance(request.model, str)
                        and ":" in request.model
                    ):
                        parts = request.model.split(":", 1)
                        backend_type = parts[0]
                        effective_model = parts[1]

                    # If the backend type is one for which we create a "real" instance
                    # in mock_get_or_create_backend, we can delegate the call to it.
                    # This allows tests that patch connector classes to work correctly.
                    if backend_type in ("openai-codex", "anthropic"):
                        backend: LLMBackend = (
                            await mock_backend_service._get_or_create_backend(
                                backend_type
                            )
                        )

                        # The real chat_completions method needs specific arguments.
                        # The RequestProcessorService should have already translated the messages.
                        processed_messages = kwargs.get("processed_messages", [])

                        # The connector's method is what's patched by the test.
                        if request and effective_model:
                            return await backend.chat_completions(
                                request_data=request,
                                processed_messages=processed_messages,
                                effective_model=effective_model,
                            )
                        # Fallback to the generic mock response if request or effective_model is None
                        logger.warning(
                            "Delegation in mock_chat_completions falling back: request or effective_model is None"
                        )
                        return await mock_chat_completions(*args, **kwargs)
                except Exception as e:
                    # Log delegation failure but fall through to the generic mock response
                    logger.warning(
                        f"Delegation to patched backend in mock_chat_completions failed: {e}"
                    )

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
                    if logger.isEnabledFor(logging.INFO):
                        logger.info(
                            "Mock backend returning streaming response for model: %s",
                            response_data["model"],
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
                    if logger.isEnabledFor(logging.INFO):
                        logger.info(
                            "Created streaming envelope: %s", streaming_envelope
                        )
                    return streaming_envelope
                else:
                    if logger.isEnabledFor(logging.INFO):
                        logger.info(
                            "Mock backend returning JSON response for model: %s",
                            response_data["model"],
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
                    # Attempt to delegate to a real backend instance to honor test patches
                    # on connector methods. This requires performing translation manually
                    # as call_completion bypasses the RequestProcessorService.

                    backend_type = None
                    effective_model = None
                    if (
                        request
                        and hasattr(request, "model")
                        and isinstance(request.model, str)
                        and ":" in request.model
                    ):
                        backend_type, effective_model = request.model.split(":", 1)

                    if backend_type in ("anthropic", "openai-codex"):
                        # Get the "real" backend instance, which might have patched methods
                        real_backend = (
                            await mock_backend_service._get_or_create_backend(
                                backend_type
                            )
                        )

                        # Manually translate messages, as this is normally done by RequestProcessorService.
                        # Use the injected translation service.

                        processed_messages = []
                        if (
                            request
                            and hasattr(request, "messages")
                            and request.messages
                        ):
                            domain_request = translation_service.to_domain_request(
                                request, backend_type
                            )
                            processed_messages = domain_request.messages

                        # Call the (potentially patched) chat_completions method
                        return await real_backend.chat_completions(
                            request_data=request,
                            processed_messages=processed_messages,
                            effective_model=effective_model,
                        )
                    else:
                        # If backend type is not supported for delegation, fall back to mock
                        return await mock_chat_completions(*args, **kwargs)

                except Exception as e:
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning(
                            "Delegation in _call_completion_delegate failed: %s. "
                            "Falling back to generic mock response.",
                            str(e),
                            exc_info=True,
                        )
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
                    real_backend: LLMBackend
                    # Use the injected BackendFactory and TranslationService to create real backends
                    httpx_client = self._resolve_httpx_client(services)

                    if httpx_client is None:
                        if logger.isEnabledFor(logging.DEBUG):
                            logger.debug(
                                "No shared HTTP client available for backend; "
                                "falling back to mock"
                            )
                        mock_backend = MagicMock()
                        mock_backend.chat_completions = AsyncMock(
                            side_effect=mock_chat_completions
                        )
                        return mock_backend

                    if backend_type == "anthropic" or backend_type == "openai-codex":
                        real_backend = backend_factory.create_backend(
                            backend_type,
                            config=config,
                        )
                        await real_backend.initialize()
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
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Registered mock backend service with full method coverage"
                )
        except ImportError as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning("Could not register mock backend service: %s", e)

    def _register_mock_backend_factory(
        self, services: ServiceCollection, translation_service: ITranslationService
    ) -> None:
        """Register a mock backend factory."""
        try:
            from src.connectors.base import LLMBackend
            from src.core.services.backend_factory import BackendFactory

            # Create mock backend factory
            mock_factory = MagicMock(spec=BackendFactory)
            mock_factory.translation_service = translation_service

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
            httpx_client = self._resolve_httpx_client(services)
            if httpx_client is not None:
                mock_factory._client = httpx_client
            else:
                try:
                    import httpx
                except ImportError:
                    mock_factory._client = MagicMock(name="httpx_async_client")
                else:
                    mock_factory._client = MagicMock(spec=httpx.AsyncClient)

            # Always register the mock factory instance to ensure it overrides any
            # previously registered real factory.
            services.add_instance(BackendFactory, mock_factory)
            # Register the interface to resolve to the same mock factory instance
            services.add_instance(IBackendFactory, mock_factory)
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Registered mock backend factory")
        except ImportError as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning("Could not register mock backend factory: %s", e)

    def _register_backend_service(self, services: ServiceCollection) -> None:
        """Register BackendService with the proper dependencies."""
        try:
            from typing import cast

            from src.core.interfaces.backend_config_provider_interface import (
                IBackendConfigProvider,
            )
            from src.core.interfaces.backend_service_interface import IBackendService
            from src.core.services.backend_service import BackendService
            from src.core.services.rate_limiter import RateLimiter

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

                # Get required Phase 3 extracted services
                from src.core.interfaces.backend_completion_flow_interface import (
                    IBackendCompletionFlow,
                )
                from src.core.interfaces.backend_lifecycle_manager_interface import (
                    IBackendLifecycleManager,
                )
                from src.core.interfaces.backend_model_resolver_interface import (
                    IBackendModelResolver,
                )
                from src.core.interfaces.exception_normalizer_interface import (
                    IExceptionNormalizer,
                )
                from src.core.interfaces.failover_planner_interface import (
                    IFailoverPlanner,
                )
                from src.core.interfaces.model_alias_resolver_interface import (
                    IModelAliasResolver,
                )
                from src.core.interfaces.planning_phase_manager_interface import (
                    IPlanningPhaseManager,
                )
                from src.core.interfaces.reasoning_config_applicator_interface import (
                    IReasoningConfigApplicator,
                )
                from src.core.interfaces.stream_formatting_interface import (
                    IStreamFormattingService,
                )
                from src.core.interfaces.stream_session_id_resolver_interface import (
                    IStreamSessionIdResolver,
                )
                from src.core.interfaces.uri_parameter_applicator_interface import (
                    IURIParameterApplicator,
                )
                from src.core.interfaces.usage_tracking_wrapper_interface import (
                    IUsageTrackingWrapper,
                )

                stream_formatting_service: IStreamFormattingService = (
                    provider.get_required_service(cast(type, IStreamFormattingService))
                )
                usage_tracking_wrapper: IUsageTrackingWrapper = (
                    provider.get_required_service(cast(type, IUsageTrackingWrapper))
                )
                model_alias_resolver: IModelAliasResolver = (
                    provider.get_required_service(cast(type, IModelAliasResolver))
                )
                exception_normalizer: IExceptionNormalizer = (
                    provider.get_required_service(cast(type, IExceptionNormalizer))
                )
                backend_lifecycle_manager: IBackendLifecycleManager = (
                    provider.get_required_service(cast(type, IBackendLifecycleManager))
                )
                planning_phase_manager: IPlanningPhaseManager = (
                    provider.get_required_service(cast(type, IPlanningPhaseManager))
                )
                reasoning_config_applicator: IReasoningConfigApplicator = (
                    provider.get_required_service(
                        cast(type, IReasoningConfigApplicator)
                    )
                )
                uri_parameter_applicator: IURIParameterApplicator = (
                    provider.get_required_service(cast(type, IURIParameterApplicator))
                )
                stream_session_id_resolver: IStreamSessionIdResolver = (
                    provider.get_required_service(cast(type, IStreamSessionIdResolver))
                )
                backend_model_resolver: IBackendModelResolver = (
                    provider.get_required_service(cast(type, IBackendModelResolver))
                )
                failover_planner: IFailoverPlanner = provider.get_required_service(
                    cast(type, IFailoverPlanner)
                )
                backend_completion_flow: IBackendCompletionFlow = (
                    provider.get_required_service(cast(type, IBackendCompletionFlow))
                )

                return BackendService(
                    backend_factory,
                    rate_limiter,
                    app_config,
                    provider.get_required_service(SessionService),
                    app_state,
                    backend_config_provider=backend_config_provider,
                    failover_coordinator=failover_coordinator,
                    wire_capture=wire_capture,
                    stream_formatting_service=stream_formatting_service,
                    usage_tracking_wrapper=usage_tracking_wrapper,
                    model_alias_resolver=model_alias_resolver,
                    exception_normalizer=exception_normalizer,
                    backend_lifecycle_manager=backend_lifecycle_manager,
                    planning_phase_manager=planning_phase_manager,
                    reasoning_config_applicator=reasoning_config_applicator,
                    uri_parameter_applicator=uri_parameter_applicator,
                    stream_session_id_resolver=stream_session_id_resolver,
                    backend_model_resolver=backend_model_resolver,
                    failover_planner=failover_planner,
                    backend_completion_flow=backend_completion_flow,
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

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Registered BackendService with all dependencies")
        except ImportError as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning("Could not register mock backend factory: %s", e)


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
        if logger.isEnabledFor(logging.INFO):
            logger.info("Initializing minimal test services...")

        # Register mock command service
        self._register_mock_command_service(services)

        # Register mock request processor
        self._register_mock_request_processor(services)

        if logger.isEnabledFor(logging.INFO):
            logger.info("Minimal test services initialized successfully")

    def _register_mock_command_service(self, services: ServiceCollection) -> None:
        """Register a simple mock command service."""
        try:
            from src.core.interfaces.command_service_interface import ICommandService

            mock_command_service = MagicMock(spec=ICommandService)
            mock_command_service.process_command = AsyncMock(return_value=None)
            mock_command_service.is_command = MagicMock(return_value=False)

            services.add_instance(ICommandService, mock_command_service)

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Registered mock command service")
        except ImportError as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning("Could not register mock command service: %s", e)

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

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Registered mock request processor")
        except ImportError as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning("Could not register mock request processor: %s", e)


class RealBackendTestStage(BaseTestBackendStage):
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

        if logger.isEnabledFor(logging.INFO):
            logger.info(
                "Real backend services for HTTP mocking initialized successfully"
            )


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
        if logger.isEnabledFor(logging.INFO):
            logger.info("Initializing custom test stage: %s", self._stage_name)

        for service_type, instance in self._services_to_register.items():
            services.add_instance(service_type, instance)
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Registered custom service: %s", service_type.__name__)

        if logger.isEnabledFor(logging.INFO):
            logger.info(
                "Custom test stage '%s' initialized successfully", self._stage_name
            )
