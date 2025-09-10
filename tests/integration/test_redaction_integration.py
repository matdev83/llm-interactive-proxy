from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = pytest.mark.no_global_mock
from src.connectors.base import LLMBackend
from src.core.config.app_config import AppConfig, BackendConfig
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.services.backend_factory import BackendFactory
from src.core.services.backend_processor import BackendProcessor
from src.core.services.backend_registry import backend_registry
from src.core.services.backend_request_manager_service import BackendRequestManager
from src.core.services.backend_service import BackendService
from src.core.services.middleware_application_manager import (
    MiddlewareApplicationManager,
)
from src.core.services.rate_limiter_service import InMemoryRateLimiter
from src.core.services.response_parser_service import ResponseParser
from src.core.services.response_processor_service import ResponseProcessor

from tests.unit.core.test_doubles import MockSessionService
from tests.utils.failover_stub import StubFailoverCoordinator

FAKE_INSTANCES: list[_FakeBackend] = []


class _FakeBackend(LLMBackend):
    """A fake backend that captures the last request passed to chat_completions."""

    backend_type = "fake"

    def __init__(self, client: Any, config: AppConfig) -> None:  # signature per factory
        super().__init__(config)
        self.client = client
        self.last_request: ChatRequest | None = None
        self.last_processed_messages: list[Any] | None = None
        self._stream: bool = False

    async def initialize(self, **kwargs: Any) -> None:  # pragma: no cover - trivial
        return None

    async def chat_completions(
        self,
        request_data: Any,
        processed_messages: list[Any],
        effective_model: str,
        identity: Any | None = None,
        **kwargs: Any,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        # Normalize request_data is already ChatRequest in our factory path
        self.last_request = request_data
        self.last_processed_messages = processed_messages
        self._stream = bool(getattr(request_data, "stream", False))

        if self._stream:

            from src.core.interfaces.response_processor_interface import (
                ProcessedResponse,
            )

            async def gen() -> AsyncIterator[ProcessedResponse]:
                yield ProcessedResponse(
                    content='data: {"choices":[{"delta":{"content":"ok"}}]}\n\n'
                )
                yield ProcessedResponse(content="data: [DONE]\n\n")

            return StreamingResponseEnvelope(
                content=gen(), media_type="text/event-stream", headers={}
            )
        else:
            content = {
                "id": "fake-1",
                "object": "chat.completion",
                "created": 0,
                "model": effective_model,
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "ok",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": None,
            }
            return ResponseEnvelope(
                content=content, headers={"content-type": "application/json"}
            )


def _register_fake_backend_once() -> None:
    if "fake" not in backend_registry._factories:

        def _factory(client, config, translation_service=None):
            inst = _FakeBackend(client, config)
            FAKE_INSTANCES.append(inst)
            return inst

        backend_registry.register_backend("fake", _factory)


async def _build_services_with_fake_backend(
    app_config: AppConfig,
) -> tuple[
    BackendRequestManager, type[_FakeBackend], MockSessionService, ResponseProcessor
]:
    # Ensure our backend is registered before creating configs/services
    _register_fake_backend_once()

    # Build BackendService using real classes but with a fake backend
    import httpx

    http_client = httpx.AsyncClient()
    from src.core.services.translation_service import TranslationService

    factory = BackendFactory(
        http_client, backend_registry, app_config, TranslationService()
    )
    rate_limiter = InMemoryRateLimiter()
    session_service = MockSessionService()

    # We need a session whose backend_config points to our fake backend
    sess = await session_service.get_session("sess")
    # Patch backend config to our fake backend so resolution uses it
    from src.core.domain.configuration.backend_config import BackendConfiguration

    assert isinstance(sess.state.backend_config, BackendConfiguration)
    backend_config = cast(BackendConfiguration, sess.state.backend_config)
    sess.state = sess.state.with_backend_config(
        backend_config.with_backend_and_model("fake", "fakemodel")
    )

    # Minimal app_state mock
    app_state = MagicMock(spec=IApplicationState)
    app_state.get_use_failover_strategy.return_value = False

    # Provide a stub failover coordinator to adhere to DIP and avoid warnings

    backend_service = BackendService(
        factory,
        rate_limiter,
        app_config,
        session_service=session_service,
        app_state=app_state,
        backend_config_provider=None,
        failover_routes=None,
        failover_strategy=None,
        failover_coordinator=StubFailoverCoordinator(),
        wire_capture=None,
    )

    backend_processor = BackendProcessor(backend_service, session_service, app_state)
    response_parser = ResponseParser()
    middleware_manager = MiddlewareApplicationManager(middleware=[])
    response_processor = ResponseProcessor(
        response_parser=response_parser,
        middleware_application_manager=middleware_manager,
    )
    backend_request_manager = BackendRequestManager(
        backend_processor, response_processor
    )

    # Create and return the live BackendRequestManager and a backend instance placeholder
    # We fetch the created backend instance by forcing one call in a setup coroutine

    # Prime creation by making a trivial call (it won't reach HTTP)
    req = ChatRequest(
        model="fakemodel", messages=[ChatMessage(role="user", content="hi")]
    )
    from src.core.domain.request_context import RequestContext

    await backend_request_manager.process_backend_request(
        req,
        session_id="sess",
        context=RequestContext(
            headers={}, cookies={}, state={}, app_state={}, original_request=None
        ),
    )
    # We return the manager and rely on _FakeBackend to capture last_request during the actual test call
    return (
        backend_request_manager,
        _FakeBackend,
        session_service,
        response_processor,
    )


def _make_app_config_with_fake_backend_and_keys() -> AppConfig:
    FAKE_INSTANCES.clear()
    _register_fake_backend_once()
    cfg = AppConfig()
    cfg.backends.default_backend = "fake"
    # Provide a dummy api key for the fake backend to look functional
    cfg.backends["fake"] = BackendConfig(api_key=["TEST_FAKE_API_KEY"])
    # Enable request redaction and provide an explicit secret for discovery
    cfg.auth.redact_api_keys_in_prompts = True
    cfg.auth.api_keys = ["RED_SECRET_ABC"]
    return cfg


@pytest.mark.asyncio
async def test_end_to_end_non_streaming_redaction() -> None:
    cfg = _make_app_config_with_fake_backend_and_keys()

    # Build dependencies
    (
        backend_request_manager,
        _,
        session_manager,
        response_manager,
    ) = await _build_services_with_fake_backend(cfg)

    # Prepare RequestProcessor with real backend path
    from src.core.interfaces.command_processor_interface import ICommandProcessor
    from src.core.services.request_processor_service import RequestProcessor

    command_processor = AsyncMock(spec=ICommandProcessor)

    # Minimal app_state exposing app_config to RequestProcessor redaction
    app_state = MagicMock(spec=IApplicationState)
    app_state.get_setting.return_value = cfg

    from src.core.interfaces.response_manager_interface import IResponseManager
    from src.core.interfaces.session_resolver_interface import ISessionResolver
    from src.core.services.session_manager_service import SessionManager

    mock_session_resolver = AsyncMock(spec=ISessionResolver)
    mock_response_manager = AsyncMock(spec=IResponseManager)

    processor = RequestProcessor(
        command_processor,
        SessionManager(session_manager, mock_session_resolver),
        backend_request_manager,
        mock_response_manager,
        app_state=app_state,
    )

    # Command processor yields no changes
    from src.core.domain.processed_result import ProcessedResult

    async def _cp(messages, session_id, context):  # type: ignore[no-redef]
        return ProcessedResult(
            modified_messages=messages, command_executed=False, command_results=[]
        )

    command_processor.process_messages.side_effect = _cp

    # Send request containing a secret and a proxy command
    secret = cfg.auth.api_keys[0]
    req = ChatRequest(
        model="fakemodel",
        messages=[ChatMessage(role="user", content=f"Use {secret} and !/hello")],
    )
    context = AsyncMock()

    resp = await processor.process_request(context, req)
    assert isinstance(resp, ResponseEnvelope)

    # The fake backend instance should have captured the request; assert redacted content
    assert FAKE_INSTANCES, "Fake backend instance not created"
    redacted_request = FAKE_INSTANCES[-1].last_request
    assert redacted_request is not None
    text = next((m.content for m in redacted_request.messages if m.role == "user"), "")
    assert isinstance(text, str)
    assert "(API_KEY_HAS_BEEN_REDACTED)" in text
    assert secret not in text
    assert "!/hello" not in text


@pytest.mark.asyncio
async def test_end_to_end_streaming_redaction() -> None:
    cfg = _make_app_config_with_fake_backend_and_keys()
    (
        backend_request_manager,
        _,
        session_manager,
        response_manager,
    ) = await _build_services_with_fake_backend(cfg)

    from src.core.interfaces.command_processor_interface import ICommandProcessor
    from src.core.services.request_processor_service import RequestProcessor

    command_processor = AsyncMock(spec=ICommandProcessor)

    app_state = MagicMock(spec=IApplicationState)
    app_state.get_setting.return_value = cfg

    from src.core.interfaces.response_manager_interface import IResponseManager
    from src.core.interfaces.session_resolver_interface import ISessionResolver
    from src.core.services.session_manager_service import SessionManager

    mock_session_resolver = AsyncMock(spec=ISessionResolver)
    mock_response_manager = AsyncMock(spec=IResponseManager)

    processor = RequestProcessor(
        command_processor,
        SessionManager(session_manager, mock_session_resolver),
        backend_request_manager,
        mock_response_manager,
        app_state=app_state,
    )

    from src.core.domain.processed_result import ProcessedResult

    async def _cp(messages, session_id, context):  # type: ignore[no-redef]
        return ProcessedResult(
            modified_messages=messages, command_executed=False, command_results=[]
        )

    command_processor.process_messages.side_effect = _cp

    secret = cfg.auth.api_keys[0]
    req = ChatRequest(
        model="fakemodel",
        messages=[ChatMessage(role="user", content=f"Stream {secret} and !/help")],
        stream=True,
    )
    context = AsyncMock()

    resp = await processor.process_request(context, req)
    assert isinstance(resp, StreamingResponseEnvelope)

    assert FAKE_INSTANCES, "Fake backend instance not created"
    redacted_request = FAKE_INSTANCES[-1].last_request
    assert redacted_request is not None
    text = next((m.content for m in redacted_request.messages if m.role == "user"), "")
    assert isinstance(text, str)
    assert "(API_KEY_HAS_BEEN_REDACTED)" in text
    assert secret not in text
    assert "!/help" not in text
