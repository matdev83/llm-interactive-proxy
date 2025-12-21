"""Tests for the AnthropicController request handling logic."""

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI, Request, Response
from src.anthropic_models import AnthropicMessage, AnthropicMessagesRequest
from src.core.app.controllers.anthropic_controller import (
    AnthropicController,
    get_anthropic_controller,
)
from src.core.common.exceptions import ServiceResolutionError
from src.core.domain.request_context import RequestContext
from src.core.interfaces.backend_request_manager_interface import IBackendRequestManager
from src.core.interfaces.di_interface import IServiceProvider, IServiceScope


@pytest.mark.asyncio
async def test_controller_preserves_tool_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure tool call metadata survives conversion to the domain ChatRequest."""

    processor = SimpleNamespace(process_request=AsyncMock())
    processor.process_request.return_value = object()
    controller = AnthropicController(processor)

    fake_context = RequestContext(
        headers={},
        cookies={},
        state={},
        app_state={},
    )
    monkeypatch.setattr(
        "src.core.app.controllers.anthropic_controller.fastapi_to_domain_request_context",
        lambda *_args, **_kwargs: fake_context,
    )

    response_payload = {
        "id": "chatcmpl-1",
        "model": "gpt-test",
        "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }
    fastapi_response = Response(
        content=json.dumps(response_payload),
        media_type="application/json",
    )

    monkeypatch.setattr(
        "src.core.app.controllers.anthropic_controller.domain_response_to_fastapi",
        lambda _resp, **_kwargs: fastapi_response,
    )

    app = FastAPI()
    scope: dict[str, Any] = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/anthropic/v1/messages",
        "raw_path": b"/anthropic/v1/messages",
        "query_string": b"",
        "headers": [],
        "client": ("testclient", 12345),
        "server": ("testserver", 80),
        "app": app,
    }

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    request = Request(scope, receive)  # type: ignore[arg-type]

    anthropic_request = AnthropicMessagesRequest(
        model="claude-3-sonnet-20240229",
        max_tokens=128,
        messages=[
            AnthropicMessage(
                role="assistant",
                content=[
                    {
                        "type": "tool_use",
                        "id": "call_123",
                        "name": "weather",
                        "input": {"location": "San Francisco"},
                    }
                ],
            ),
            AnthropicMessage(
                role="user",
                content=[
                    {
                        "type": "tool_result",
                        "tool_use_id": "call_123",
                        "content": [{"type": "text", "text": "Result text"}],
                    }
                ],
            ),
        ],
    )

    await controller.handle_anthropic_messages(request, anthropic_request)

    assert processor.process_request.await_count == 1
    await_args = processor.process_request.await_args
    chat_request = await_args.args[1]

    assert len(chat_request.messages) == 2

    first_message = chat_request.messages[0]
    assert first_message.role == "assistant"
    assert first_message.tool_calls is not None
    assert first_message.tool_calls[0].id == "call_123"
    assert json.loads(first_message.tool_calls[0].function.arguments) == {
        "location": "San Francisco"
    }

    second_message = chat_request.messages[1]
    assert second_message.role == "tool"
    assert second_message.tool_call_id == "call_123"
    assert second_message.content == "Result text"


def test_get_anthropic_controller_uses_di_for_app_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure ApplicationStateService is resolved through the DI container."""
    from src.core.interfaces.request_processor_interface import IRequestProcessor

    # Patch the global provider function to return None so it uses local provider
    monkeypatch.setattr(
        "src.core.app.controllers.request_processor_resolver._get_from_global_provider",
        lambda local_provider: None,
    )

    # Patch the service collection to avoid building from scratch
    def mock_get_service_collection():
        from src.core.di.container import ServiceCollection

        services = ServiceCollection()

        # Add all the mock services to the service collection
        services.add_singleton(IRequestProcessor, MagicMock())
        services.add_singleton(ICommandService, MagicMock())
        services.add_singleton(IBackendService, MagicMock())
        services.add_singleton(ISessionService, MagicMock())
        services.add_singleton(IResponseProcessor, MagicMock())
        services.add_singleton(IBackendRequestManager, MagicMock())
        services.add_singleton(BackendFactory, MagicMock())
        services.add_singleton(AppConfig, MagicMock())
        services.add_singleton(BackendRegistry, MagicMock())
        services.add_singleton(httpx.AsyncClient, MagicMock())
        services.add_singleton(app_state_mock, sentinel_app_state)

        return services

    monkeypatch.setattr(
        "src.core.di.services.get_service_collection",
        mock_get_service_collection,
    )

    # Patch ApplicationStateService to fail if instantiated directly
    app_state_mock = MagicMock(
        name="ApplicationStateService",
        side_effect=AssertionError("ApplicationStateService should come from DI"),
    )
    monkeypatch.setattr(
        "src.core.services.application_state_service.ApplicationStateService",
        app_state_mock,
    )

    sentinel_app_state = object()

    class DummyScope(IServiceScope):
        @property
        def service_provider(self) -> IServiceProvider:  # pragma: no cover - unused
            raise NotImplementedError

        async def dispose(self) -> None:  # pragma: no cover - unused
            raise NotImplementedError

    class DummyProvider(IServiceProvider):
        def __init__(self) -> None:
            self._services: dict[type, object] = {}
            self.requested_types: list[type] = []

        def set_service(self, key: type, value: object) -> None:
            self._services[key] = value

        def get_service(self, service_type: type):  # type: ignore[override]
            self.requested_types.append(service_type)
            return self._services.get(service_type)

        def get_required_service(self, service_type: type):  # type: ignore[override]
            service = self.get_service(service_type)
            if service is None:
                raise ServiceResolutionError(
                    f"Service not found: {service_type}",
                    service_name=getattr(service_type, "__name__", str(service_type)),
                )
            return service

        def has_service(self, service_type: type) -> bool:
            return service_type in self._services

        def create_scope(self) -> IServiceScope:  # pragma: no cover - unused
            return DummyScope()

    provider = DummyProvider()

    # Ensure no pre-existing request processor so the fallback path executes
    import httpx
    from src.core.config.app_config import AppConfig
    from src.core.interfaces.backend_service_interface import IBackendService
    from src.core.interfaces.command_service_interface import ICommandService
    from src.core.interfaces.response_processor_interface import IResponseProcessor
    from src.core.interfaces.session_service_interface import ISessionService
    from src.core.services.backend_factory import BackendFactory
    from src.core.services.backend_registry import BackendRegistry

    provider.set_service(ICommandService, MagicMock())
    provider.set_service(IBackendService, MagicMock())
    provider.set_service(ISessionService, MagicMock())
    provider.set_service(IResponseProcessor, MagicMock())
    provider.set_service(IBackendRequestManager, MagicMock())

    # Add missing required services for BackendFactory
    provider.set_service(BackendFactory, MagicMock())
    provider.set_service(AppConfig, MagicMock())
    provider.set_service(BackendRegistry, MagicMock())
    provider.set_service(httpx.AsyncClient, MagicMock())

    # Register the DI-managed application state instance under the patched class key
    provider.set_service(app_state_mock, sentinel_app_state)

    controller = get_anthropic_controller(provider)

    assert isinstance(controller, AnthropicController)
    assert app_state_mock.call_count == 0  # No manual instantiation occurred
    # Verify that DI was used (at least IRequestProcessor was requested)
    assert IRequestProcessor in provider.requested_types
