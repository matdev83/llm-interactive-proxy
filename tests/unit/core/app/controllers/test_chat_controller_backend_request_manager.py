"""Tests for ChatController DI integration."""

from __future__ import annotations

from typing import Any

import pytest
from src.core.app.controllers.chat_controller import ChatController, get_chat_controller
from src.core.common.exceptions import ServiceResolutionError
from src.core.interfaces.agent_response_formatter_interface import (
    IAgentResponseFormatter,
)
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.interfaces.backend_service_interface import IBackendService
from src.core.interfaces.command_processor_interface import ICommandProcessor
from src.core.interfaces.command_service_interface import ICommandService
from src.core.interfaces.di_interface import IServiceProvider, IServiceScope
from src.core.interfaces.response_processor_interface import IResponseProcessor
from src.core.interfaces.session_resolver_interface import ISessionResolver
from src.core.interfaces.session_service_interface import ISessionService
from src.core.interfaces.translation_service_interface import ITranslationService
from src.core.interfaces.wire_capture_interface import IWireCapture


class _FakeScope(IServiceScope):
    """Simple test scope implementation."""

    def __init__(self, provider: IServiceProvider) -> None:
        self._provider = provider

    @property
    def service_provider(self) -> IServiceProvider:
        return self._provider

    async def dispose(self) -> None:  # pragma: no cover - unused in test
        return None


class _FakeProvider(IServiceProvider):
    """Minimal service provider for exercising controller wiring."""

    def __init__(self, services: dict[type[Any], Any]) -> None:
        self._services = services

    def get_service(self, service_type: type[Any]) -> Any | None:
        return self._services.get(service_type)

    def get_required_service(self, service_type: type[Any]) -> Any:
        service = self.get_service(service_type)
        if service is None:
            type_name = getattr(service_type, "__name__", repr(service_type))
            raise ServiceResolutionError(
                f"Missing required service: {type_name}", service_name=type_name
            )
        return service

    def has_service(self, service_type: type[Any]) -> bool:
        return service_type in self._services

    def create_scope(self) -> IServiceScope:  # pragma: no cover - unused in test
        return _FakeScope(self)


class _DummySessionManager:
    def __init__(
        self,
        session_service: Any,
        session_resolver: Any,
        fingerprint_service: Any | None = None,
        session_repository: Any | None = None,
    ) -> None:
        self.session_service = session_service
        self.session_resolver = session_resolver
        self.fingerprint_service = fingerprint_service
        self.session_repository = session_repository


class _DummyBackendRequestManager:
    def __init__(
        self,
        backend_processor: Any,
        response_processor: Any,
        wire_capture: Any | None = None,
        **_kwargs: Any,
    ) -> None:
        self.backend_processor = backend_processor
        self.response_processor = response_processor
        self.wire_capture = wire_capture


class _DummyResponseManager:
    def __init__(self, agent_response_formatter: Any) -> None:
        self.agent_response_formatter = agent_response_formatter


class _DummyRequestProcessor:
    def __init__(
        self,
        command_processor: Any,
        session_manager: Any,
        backend_request_manager: Any,
        response_manager: Any,
        app_state: Any | None = None,
    ) -> None:
        self.command_processor = command_processor
        self.session_manager = session_manager
        self.backend_request_manager = backend_request_manager
        self.response_manager = response_manager
        self.app_state = app_state

    async def process_request(
        self, *args: Any, **kwargs: Any
    ) -> Any:  # pragma: no cover - unused
        raise AssertionError("process_request should not be called in this test")


def test_get_chat_controller_uses_wire_capture_when_constructing_backend_manager(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure fallback construction uses DI-provided wire capture instances."""

    from src.core.app.controllers import chat_controller as chat_controller_module
    from src.core.services import (
        backend_request_manager_service,
        request_processor_service,
        response_manager_service,
        session_manager_service,
    )

    monkeypatch.setattr(
        session_manager_service,
        "SessionManager",
        _DummySessionManager,
    )
    monkeypatch.setattr(
        backend_request_manager_service,
        "BackendRequestManager",
        _DummyBackendRequestManager,
    )
    monkeypatch.setattr(
        response_manager_service,
        "ResponseManager",
        _DummyResponseManager,
    )
    monkeypatch.setattr(
        request_processor_service,
        "RequestProcessor",
        _DummyRequestProcessor,
    )

    sentinel_wire_capture = object()
    sentinel_command_service = object()
    sentinel_backend_service = object()
    sentinel_session_service = object()
    sentinel_response_processor = object()
    sentinel_command_processor = object()
    sentinel_backend_processor = object()
    sentinel_application_state = object()
    sentinel_session_resolver = object()
    sentinel_formatter = object()
    sentinel_translation_service = object()

    def _dummy_resolve_request_processor(_: Any) -> _DummyRequestProcessor:
        return _DummyRequestProcessor(
            command_processor=sentinel_command_processor,
            session_manager=_DummySessionManager(
                sentinel_session_service,
                sentinel_session_resolver,
                fingerprint_service=None,
                session_repository=None,
            ),
            backend_request_manager=_DummyBackendRequestManager(
                backend_processor=sentinel_backend_processor,
                response_processor=sentinel_response_processor,
                wire_capture=sentinel_wire_capture,
            ),
            response_manager=_DummyResponseManager(sentinel_formatter),
            app_state=sentinel_application_state,
        )

    monkeypatch.setattr(
        chat_controller_module,
        "resolve_request_processor",
        _dummy_resolve_request_processor,
    )

    provider = _FakeProvider(
        {
            ICommandService: sentinel_command_service,
            IBackendService: sentinel_backend_service,
            ISessionService: sentinel_session_service,
            IResponseProcessor: sentinel_response_processor,
            ICommandProcessor: sentinel_command_processor,
            IApplicationState: sentinel_application_state,
            ISessionResolver: sentinel_session_resolver,
            IAgentResponseFormatter: sentinel_formatter,
            ITranslationService: sentinel_translation_service,
            IWireCapture: sentinel_wire_capture,
        }
    )

    controller = get_chat_controller(provider)

    assert isinstance(controller, ChatController)
    processor = controller._processor
    assert isinstance(processor, _DummyRequestProcessor)
    backend_manager = processor.backend_request_manager
    assert isinstance(backend_manager, _DummyBackendRequestManager)
    assert backend_manager.wire_capture is sentinel_wire_capture
