"""Tests covering DI fallback behavior for the Anthropic controller."""

from __future__ import annotations

import types
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import MagicMock

import pytest
from src.core.app.controllers.anthropic_controller import (
    AnthropicController,
    get_anthropic_controller,
)
from src.core.commands.models import Command
from src.core.commands.service import CommandResultWrapper
from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection
from src.core.domain.chat import ChatRequest
from src.core.domain.processed_result import ProcessedResult
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.interfaces.backend_request_manager_interface import IBackendRequestManager
from src.core.interfaces.backend_service_interface import IBackendService
from src.core.interfaces.command_service_interface import ICommandService
from src.core.interfaces.request_processor_interface import IRequestProcessor
from src.core.interfaces.response_processor_interface import (
    IResponseProcessor,
    ProcessedResponse,
)
from src.core.interfaces.session_resolver_interface import ISessionResolver
from src.core.interfaces.session_service_interface import ISessionService
from src.core.interfaces.wire_capture_interface import IWireCapture
from src.core.repositories.in_memory_session_repository import InMemorySessionRepository
from src.core.services.application_state_service import ApplicationStateService
from src.core.services.response_manager_service import AgentResponseFormatter
from src.core.services.session_resolver_service import DefaultSessionResolver
from src.core.services.session_service_impl import SessionService


class _StubCommandService(ICommandService):
    async def process_commands(
        self, messages: list[Any], session_id: str
    ) -> ProcessedResult:
        return ProcessedResult(
            modified_messages=messages,
            command_executed=False,
            command_results=[],
        )

    async def execute_command(
        self, command: Command, session_id: str
    ) -> CommandResultWrapper:
        dummy_result = types.SimpleNamespace(
            message="stub",
            success=True,
            new_state=None,
        )
        return CommandResultWrapper(command.name, dummy_result)


class _StubBackendService(IBackendService):
    async def call_completion(
        self,
        request: ChatRequest,
        stream: bool = False,
        allow_failover: bool = True,
        context: RequestContext | None = None,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        if stream:

            async def _stream() -> AsyncIterator[StreamingResponseEnvelope]:
                yield StreamingResponseEnvelope(content={}, headers={}, status_code=200)

            return _stream()

        return ResponseEnvelope(content={}, headers={}, status_code=200)

    async def validate_backend_and_model(
        self, backend: str, model: str
    ) -> BackendModelValidation:
        return BackendModelValidation.valid()

    async def chat_completions(
        self, request: ChatRequest, **kwargs: Any
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        return await self.call_completion(
            request, stream=bool(getattr(request, "stream", False))
        )

    def get_backend(self, backend_type: str):
        raise KeyError(backend_type)

    def get_active_backends(self):
        return {}


class _StubResponseProcessor(IResponseProcessor):
    async def process_response(
        self,
        response: Any,
        session_id: str,
        context: dict[str, Any] | None = None,
    ) -> ProcessedResponse:
        return ProcessedResponse(content=response)

    def process_streaming_response(
        self, response_iterator: AsyncIterator[Any], session_id: str
    ) -> AsyncIterator[ProcessedResponse]:
        async def _generator() -> AsyncIterator[ProcessedResponse]:
            async for chunk in response_iterator:
                yield ProcessedResponse(content=chunk)

        return _generator()

    async def register_middleware(self, middleware: Any, priority: int = 0) -> None:
        return None


class _StubWireCapture(IWireCapture):
    def enabled(self) -> bool:
        return False

    async def capture_inbound_request(
        self,
        *,
        context: RequestContext | None,
        session_id: str | None,
        request_payload: Any,
    ) -> None:
        return None

    async def capture_outbound_request(
        self,
        *,
        context: RequestContext | None,
        session_id: str | None,
        backend: str,
        model: str,
        key_name: str | None,
        request_payload: Any,
    ) -> None:
        return None

    async def capture_inbound_response(
        self,
        *,
        context: RequestContext | None,
        session_id: str | None,
        backend: str,
        model: str,
        key_name: str | None,
        response_content: Any,
    ) -> None:
        return None

    async def capture_outbound_response(
        self,
        *,
        context: RequestContext | None,
        session_id: str | None,
        backend: str | None,
        model: str | None,
        key_name: str | None,
        response_content: Any,
    ) -> None:
        return None

    def wrap_inbound_stream(
        self,
        *,
        context: RequestContext | None,
        session_id: str | None,
        backend: str,
        model: str,
        key_name: str | None,
        stream: AsyncIterator[bytes],
    ) -> AsyncIterator[bytes]:
        return stream

    def wrap_outbound_stream(
        self,
        *,
        context: RequestContext | None,
        session_id: str | None,
        backend: str | None,
        model: str | None,
        key_name: str | None,
        stream: AsyncIterator[bytes],
    ) -> AsyncIterator[bytes]:
        return stream

    async def capture_stream_completion(
        self,
        *,
        context: RequestContext | None,
        session_id: str | None,
        backend: str,
        model: str,
        key_name: str | None,
        canonical_usage: Any | None = None,
    ) -> None:
        return None

    async def shutdown(self) -> None:
        return None


def _build_service_provider_without_request_processor():
    """Create a service provider missing IRequestProcessor to trigger fallback."""
    services = ServiceCollection()

    app_config = AppConfig()
    services.add_instance(AppConfig, app_config)

    command_service = _StubCommandService()
    services.add_instance(_StubCommandService, command_service)
    services.add_instance(ICommandService, command_service)

    backend_service = _StubBackendService()
    services.add_instance(_StubBackendService, backend_service)
    services.add_instance(IBackendService, backend_service)

    session_service = SessionService(InMemorySessionRepository())
    services.add_instance(SessionService, session_service)
    services.add_instance(ISessionService, session_service)

    response_processor = _StubResponseProcessor()
    services.add_instance(_StubResponseProcessor, response_processor)
    services.add_instance(IResponseProcessor, response_processor)

    app_state = ApplicationStateService()
    services.add_instance(ApplicationStateService, app_state)
    services.add_instance(IApplicationState, app_state)

    session_resolver = DefaultSessionResolver(app_config)
    services.add_instance(DefaultSessionResolver, session_resolver)
    services.add_instance(ISessionResolver, session_resolver)

    agent_formatter = AgentResponseFormatter(session_service=session_service)
    services.add_instance(AgentResponseFormatter, agent_formatter)

    # Backend request manager dependency used by fallback request processor path.
    services.add_instance(IBackendRequestManager, MagicMock())

    # Provide a wire capture implementation to satisfy downstream dependencies.
    wire_capture = _StubWireCapture()
    services.add_instance(_StubWireCapture, wire_capture)
    services.add_instance(IWireCapture, wire_capture)

    return services.build_service_provider()


def test_fallback_request_processor_receives_app_state(monkeypatch: pytest.MonkeyPatch):
    """Ensure fallback construction does not drop required DI-managed state."""
    import httpx
    from src.core.config.app_config import AppConfig
    from src.core.interfaces.backend_processor_interface import IBackendProcessor
    from src.core.services.application_state_service import ApplicationStateService
    from src.core.services.backend_factory import BackendFactory
    from src.core.services.backend_registry import BackendRegistry

    # Patch the global provider function to return None so it uses local provider
    monkeypatch.setattr(
        "src.core.app.controllers.request_processor_resolver._get_from_global_provider",
        lambda local_provider: None,
    )

    # Create a sentinel app state instance
    sentinel_app_state = ApplicationStateService()

    # Patch the service collection to provide all required services
    def mock_get_service_collection():
        from unittest.mock import MagicMock

        from src.core.di.container import ServiceCollection
        from src.core.services.request_processor_service import RequestProcessor

        services = ServiceCollection()

        # DO NOT add IRequestProcessor or RequestProcessor - this forces the fallback path
        # But we need to add the factory function so the fallback path can create one

        # Add required interfaces and dependencies for RequestProcessor factory
        from src.core.interfaces.command_processor_interface import ICommandProcessor
        from src.core.interfaces.response_manager_interface import IResponseManager
        from src.core.interfaces.session_manager_interface import ISessionManager

        services.add_singleton(ICommandService, MagicMock())
        services.add_singleton(IBackendService, MagicMock())
        services.add_singleton(ISessionService, MagicMock())
        services.add_singleton(IResponseProcessor, MagicMock())
        services.add_singleton(IBackendRequestManager, MagicMock())
        services.add_singleton(IBackendProcessor, MagicMock())
        services.add_singleton(BackendFactory, MagicMock())
        services.add_singleton(AppConfig, MagicMock())
        services.add_singleton(BackendRegistry, MagicMock())
        services.add_singleton(httpx.AsyncClient, MagicMock())
        services.add_singleton(IWireCapture, _StubWireCapture())

        # Add mocks for RequestProcessor dependencies
        services.add_singleton(ICommandProcessor, MagicMock())
        services.add_singleton(ISessionManager, MagicMock())
        services.add_singleton(IResponseManager, MagicMock())

        # Add the real ApplicationStateService instance
        services.add_instance(ApplicationStateService, sentinel_app_state)
        services.add_instance(IApplicationState, sentinel_app_state)

        # Register internal request processor interfaces that the factory needs
        from src.core.interfaces.request_processor_internal import (
            IBackendExecutor,
            IBackendPreparer,
            ICommandHandler,
            IRequestSideEffects,
            IRequestTransformPipeline,
            ISessionEnricher,
        )

        # Register internal services as singletons
        services.add_singleton(ISessionEnricher, MagicMock(spec=ISessionEnricher))
        services.add_singleton(IRequestSideEffects, MagicMock(spec=IRequestSideEffects))
        services.add_singleton(ICommandHandler, MagicMock(spec=ICommandHandler))
        services.add_singleton(IBackendPreparer, MagicMock(spec=IBackendPreparer))
        services.add_singleton(
            IRequestTransformPipeline, MagicMock(spec=IRequestTransformPipeline)
        )
        services.add_singleton(IBackendExecutor, MagicMock(spec=IBackendExecutor))

        # Add the RequestProcessor factory that will use the real ApplicationStateService
        def _request_processor_factory(provider):
            from typing import cast

            from src.core.interfaces.request_processor_internal import (
                IBackendExecutor,
                IBackendPreparer,
                ICommandHandler,
                IRequestSideEffects,
                IRequestTransformPipeline,
                ISessionEnricher,
            )
            from src.core.services.request_processor_service import RequestProcessor

            command_processor = provider.get_required_service(ICommandProcessor)
            session_manager = provider.get_required_service(ISessionManager)
            backend_request_manager = provider.get_required_service(
                IBackendRequestManager
            )
            response_manager = provider.get_required_service(IResponseManager)
            app_state = provider.get_service(IApplicationState)

            # Get decomposed services
            session_enricher = provider.get_required_service(
                cast(type, ISessionEnricher)
            )
            request_side_effects = provider.get_required_service(
                cast(type, IRequestSideEffects)
            )
            command_handler = provider.get_required_service(cast(type, ICommandHandler))
            backend_preparer = provider.get_required_service(
                cast(type, IBackendPreparer)
            )
            transform_pipeline = provider.get_required_service(
                cast(type, IRequestTransformPipeline)
            )
            backend_executor = provider.get_required_service(
                cast(type, IBackendExecutor)
            )

            return RequestProcessor(
                command_processor,
                session_manager,
                backend_request_manager,
                response_manager,
                session_enricher=session_enricher,
                request_side_effects=request_side_effects,
                command_handler=command_handler,
                backend_preparer=backend_preparer,
                transform_pipeline=transform_pipeline,
                backend_executor=backend_executor,
                app_state=app_state,
            )

        services.add_singleton(
            IRequestProcessor, implementation_factory=_request_processor_factory
        )
        services.add_singleton(
            RequestProcessor, implementation_factory=_request_processor_factory
        )

        return services

    monkeypatch.setattr(
        "src.core.di.services.get_service_collection",
        mock_get_service_collection,
    )

    provider = _build_service_provider_without_request_processor()

    # Sanity check: DI resolution path is indeed missing the request processor.
    assert provider.get_service(IRequestProcessor) is None

    controller = get_anthropic_controller(provider)
    assert isinstance(controller, AnthropicController)

    # The fallback-constructed request processor must receive application state.
    assert controller._processor._app_state is sentinel_app_state
