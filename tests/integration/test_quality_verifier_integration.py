from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from src.core.config.app_config import AppConfig, SessionConfig
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.backend_processor_interface import IBackendProcessor
from src.core.interfaces.backend_request_manager_interface import IBackendRequestManager
from src.core.interfaces.backend_service_interface import IBackendService
from src.core.interfaces.response_parser_interface import IResponseParser
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.quality_verifier_steering_store import (
    PENDING_QUALITY_VERIFIER_STEERING_SETTING_KEY,
)
from src.core.services.response_processor_service import ResponseProcessor
from src.core.services.streaming.content_accumulation_processor import (
    ContentAccumulationProcessor,
)
from src.core.services.streaming.stream_normalizer import StreamNormalizer


class _DummyParser:
    def parse_response(self, response: Any) -> Any:
        return response

    def extract_content(self, response: Any) -> Any:
        if isinstance(response, dict):
            return response.get("content")
        return response

    def extract_usage(self, response: Any) -> Any:
        if isinstance(response, dict):
            return response.get("usage")
        return None

    def extract_metadata(self, response: Any) -> Any:
        if isinstance(response, dict):
            return response.get("metadata")
        return {}


class _StubBackendProcessor:
    def __init__(
        self,
        factories: list[Callable[[], ResponseEnvelope | StreamingResponseEnvelope]],
    ):
        self._factories = factories
        self.calls: list[ChatRequest] = []
        self._next = 0

    async def process_backend_request(
        self,
        request: ChatRequest,
        session_id: str,
        context: RequestContext | None = None,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        self.calls.append(request)
        fac = self._factories[self._next]
        self._next += 1
        return fac()


class _AppState:
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._settings: dict[str, Any] = {}

    def get_setting(self, key: str, default: Any = None) -> Any:
        if key == "app_config":
            return self._config
        return self._settings.get(key, default)

    def set_setting(self, key: str, value: Any) -> None:
        self._settings[key] = value

    def get_service(self, _t: Any) -> Any:
        return None


class _FakeBackendService:
    def __init__(self, *, steering_xml: str) -> None:
        self.steering_xml = steering_xml
        self.requests: list[ChatRequest] = []

    async def chat_completions(
        self,
        request: ChatRequest,
        stream: bool = False,
        allow_failover: bool = True,
        context: Any | None = None,
    ) -> SimpleNamespace:
        self.requests.append(request)
        # This is always the verifier call in the integration tests.
        return SimpleNamespace(content=self.steering_xml)


def _make_response_processor(app_state: _AppState) -> ResponseProcessor:
    stream_normalizer = StreamNormalizer([ContentAccumulationProcessor()])
    processor = ResponseProcessor(
        response_parser=cast(IResponseParser, _DummyParser()),
        stream_normalizer=stream_normalizer,
        turn_ledger=MagicMock(),
    )
    processor._app_state = app_state  # type: ignore[attr-defined]
    return processor


def _make_context(app_state: _AppState, config: AppConfig) -> RequestContext:
    extensions: dict[str, Any] = {}
    if config.session and config.session.quality_verifier_model:
        extensions["quality_verifier_model"] = config.session.quality_verifier_model
    if config.session:
        extensions["quality_verifier_frequency"] = (
            config.session.quality_verifier_frequency
        )
    return RequestContext(
        headers={},
        cookies={},
        state=None,
        app_state=app_state,
        session_id=None,
        original_request=None,
        extensions=extensions,
    )


def _make_mock_provider(
    backend_service: _FakeBackendService,
    manager_holder: list[Any],
) -> Any:
    class _Provider:
        def get_required_service(self, service_type: Any) -> Any:
            if service_type is IBackendRequestManager:
                return manager_holder[0]
            if service_type is IBackendService:
                return backend_service
            return backend_service

        def get_service(self, _type: Any) -> None:
            return None

    return _Provider()


@pytest.mark.asyncio
async def test_quality_verifier_integration_non_streaming_inline_recall(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = AppConfig(
        session=SessionConfig(
            quality_verifier_model="fake_backend:guardian",
            quality_verifier_frequency=1,
        )
    )
    app_state = _AppState(config)

    def _initial() -> ResponseEnvelope:
        return ResponseEnvelope(content={"content": "initial output"})

    def _after_steer() -> ResponseEnvelope:
        return ResponseEnvelope(content={"content": "after verification recall"})

    response_processor = _make_response_processor(app_state)
    backend_service = _FakeBackendService(
        steering_xml="<steering>Consider doing X</steering>"
    )
    manager_holder: list[Any] = []
    mock_provider = _make_mock_provider(backend_service, manager_holder)

    monkeypatch.setattr(
        "src.core.di.services.get_service_provider",
        lambda: mock_provider,
    )

    from tests.helpers.backend_request_manager_fixtures import (
        create_backend_request_manager,
    )

    manager = create_backend_request_manager(
        backend_processor=cast(
            IBackendProcessor,
            _StubBackendProcessor([_initial, _after_steer]),
        ),
        response_processor=response_processor,
        mock_provider=mock_provider,
        config=config,
    )
    manager_holder.append(manager)

    original_request = ChatRequest(
        model="fake_backend:primary",
        messages=[ChatMessage(role="user", content="Hi")],
    )

    context = _make_context(app_state, config)
    context.original_request = original_request

    result = await manager.process_backend_request(
        backend_request=original_request,
        session_id="session-non-stream",
        context=context,
    )

    assert isinstance(result, ResponseEnvelope)
    assert result.content == "after verification recall"

    pending = app_state.get_setting(PENDING_QUALITY_VERIFIER_STEERING_SETTING_KEY, {})
    assert pending == {}


@pytest.mark.asyncio
async def test_quality_verifier_integration_streaming_inline_recall(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = AppConfig(
        session=SessionConfig(
            quality_verifier_model="fake_backend:guardian",
            quality_verifier_frequency=1,
        )
    )
    app_state = _AppState(config)

    async def _stream_main() -> AsyncIterator[ProcessedResponse]:
        yield ProcessedResponse(content="Draft", metadata={})
        yield ProcessedResponse(content=" reply", metadata={"is_done": True})

    async def _stream_recall() -> AsyncIterator[ProcessedResponse]:
        yield ProcessedResponse(content="Recalled", metadata={"is_done": True})

    def _main_env() -> StreamingResponseEnvelope:
        return StreamingResponseEnvelope(content=_stream_main())

    def _recall_env() -> StreamingResponseEnvelope:
        return StreamingResponseEnvelope(content=_stream_recall())

    response_processor = _make_response_processor(app_state)
    backend_service = _FakeBackendService(
        steering_xml="<steering>Check your math</steering>"
    )
    manager_holder: list[Any] = []
    mock_provider = _make_mock_provider(backend_service, manager_holder)

    monkeypatch.setattr(
        "src.core.di.services.get_service_provider",
        lambda: mock_provider,
        raising=False,
    )

    from tests.helpers.backend_request_manager_fixtures import (
        create_backend_request_manager,
    )

    manager = create_backend_request_manager(
        backend_processor=cast(
            IBackendProcessor,
            _StubBackendProcessor([_main_env, _recall_env]),
        ),
        response_processor=response_processor,
        mock_provider=mock_provider,
        config=config,
    )
    manager_holder.append(manager)

    original_request = ChatRequest(
        model="fake_backend:primary",
        messages=[ChatMessage(role="user", content="Hi")],
        stream=True,
    )

    context = _make_context(app_state, config)
    context.original_request = original_request

    stream_envelope = await manager.process_backend_request(
        backend_request=original_request,
        session_id="session-stream",
        context=context,
    )

    assert isinstance(stream_envelope, StreamingResponseEnvelope)
    assert stream_envelope.content is not None

    gathered: list[str] = []
    async for chunk in stream_envelope.content:
        gathered.append(str(chunk.content))
    assert gathered == ["Recalled"]

    pending = app_state.get_setting(PENDING_QUALITY_VERIFIER_STEERING_SETTING_KEY, {})
    assert pending == {}
