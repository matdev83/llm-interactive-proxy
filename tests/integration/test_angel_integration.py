from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from types import SimpleNamespace
from typing import Any, cast

import pytest
from src.core.config.app_config import AppConfig, SessionConfig
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.backend_processor_interface import IBackendProcessor
from src.core.interfaces.response_parser_interface import IResponseParser
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.angel_service import get_prompt_loader
from src.core.services.backend_request_manager_service import BackendRequestManager
from src.core.services.response_processor_service import ResponseProcessor
from src.core.services.streaming.content_accumulation_processor import (
    ContentAccumulationProcessor,
)
from src.core.services.streaming.stream_normalizer import StreamNormalizer

from tests.helpers.angel_factory_stub import AngelFactoryStub


class _DummyParser:
    def parse_response(self, response: Any) -> Any:
        return response

    def extract_content(self, response: Any) -> Any:
        return response.get("content")

    def extract_usage(self, response: Any) -> Any:
        return response.get("usage")

    def extract_metadata(self, response: Any) -> Any:
        return response.get("metadata")


class _StubBackendProcessor:
    def __init__(
        self, factory: Callable[[], ResponseEnvelope | StreamingResponseEnvelope]
    ):
        self._factory = factory
        self.calls: list[ChatRequest] = []

    async def process_backend_request(
        self,
        request: ChatRequest,
        session_id: str,
        context: RequestContext | None = None,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        self.calls.append(request)
        return self._factory()


class _FakeBackendService:
    def __init__(
        self,
        *,
        corrected_text: str,
        steering_message: str = "Re-evaluate your answer",
        decision: str = "steer",
        override: bool = False,
    ) -> None:
        self.corrected_text = corrected_text
        self.steering_message = steering_message
        self.decision = decision
        self.override = override
        self.requests: list[ChatRequest] = []

    async def chat_completions(
        self,
        request: ChatRequest,
        stream: bool = False,
        allow_failover: bool = True,
        context: Any | None = None,
    ) -> SimpleNamespace:
        self.requests.append(request)
        first_message = request.messages[0]
        if (
            first_message.role == "system"
            and first_message.content == get_prompt_loader().angel_prompt
        ):
            if self.decision.lower() == "pass":
                content = "<angels_decision>Pass</angels_decision>"
            else:
                content = f"\n<angels_steering_message>{self.steering_message}</angels_steering_message>\n"
            return SimpleNamespace(content=content)

        if self.override:
            return SimpleNamespace(content="<override_angel>True</override_angel>")
        return SimpleNamespace(content=self.corrected_text)


class _DummyAppState:
    def __init__(self, config: AppConfig) -> None:
        self._config = config

    def get_setting(self, key: str) -> Any:
        if key == "app_config":
            return self._config
        raise KeyError(key)


def _make_response_processor(config: AppConfig) -> ResponseProcessor:
    """Create a ResponseProcessor using the unified pipeline architecture."""
    stream_normalizer = StreamNormalizer([ContentAccumulationProcessor()])
    processor = ResponseProcessor(
        response_parser=cast(IResponseParser, _DummyParser()),
        stream_normalizer=stream_normalizer,
    )
    processor._app_state = _DummyAppState(config)  # type: ignore[attr-defined]
    return processor


def _make_context(config: AppConfig) -> RequestContext:
    return RequestContext(
        headers={},
        cookies={},
        state={},
        app_state=_DummyAppState(config),
        client_host=None,
        session_id=None,
        agent=None,
        original_request=None,
    )


def _patch_provider(
    monkeypatch: pytest.MonkeyPatch, backend_service: _FakeBackendService
) -> None:
    class _Provider:
        def get_required_service(self, _type: Any) -> _FakeBackendService:
            return backend_service

    monkeypatch.setattr(
        "src.core.di.services.get_service_provider",
        lambda: _Provider(),
        raising=False,
    )


@pytest.mark.asyncio
async def test_angel_integration_non_streaming_correction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = AppConfig(session=SessionConfig(angel_model="fake_backend:guardian"))

    def _response_factory() -> ResponseEnvelope:
        return ResponseEnvelope(content={"content": "initial output"})

    response_processor = _make_response_processor(config)
    backend_service = _FakeBackendService(corrected_text="Corrected response")
    _patch_provider(monkeypatch, backend_service)

    manager = BackendRequestManager(
        cast(IBackendProcessor, _StubBackendProcessor(_response_factory)),
        response_processor,
        AngelFactoryStub(),
    )

    original_request = ChatRequest(
        model="fake_backend:primary",
        messages=[ChatMessage(role="user", content="Hi")],
    )

    context = _make_context(config)

    result = await manager.process_backend_request(
        backend_request=original_request,
        session_id="session-non-stream",
        context=context,
    )

    assert isinstance(result, ResponseEnvelope)
    assert result.content == "Corrected response"
    assert [req.model for req in backend_service.requests] == [
        "fake_backend:guardian",
        "fake_backend:primary",
    ]


@pytest.mark.asyncio
async def test_angel_integration_streaming_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = AppConfig(session=SessionConfig(angel_model="fake_backend:guardian"))

    async def _stream() -> AsyncIterator[ProcessedResponse]:
        yield ProcessedResponse(content="Draft", metadata={})
        yield ProcessedResponse(content=" reply", metadata={"is_done": True})

    def _response_factory() -> StreamingResponseEnvelope:
        return StreamingResponseEnvelope(content=_stream())

    response_processor = _make_response_processor(config)
    backend_service = _FakeBackendService(
        corrected_text="unused",
        steering_message="Check your math",
        override=True,
    )
    _patch_provider(monkeypatch, backend_service)

    manager = BackendRequestManager(
        cast(IBackendProcessor, _StubBackendProcessor(_response_factory)),
        response_processor,
        AngelFactoryStub(),
    )

    original_request = ChatRequest(
        model="fake_backend:primary",
        messages=[ChatMessage(role="user", content="Hi")],
        stream=True,
    )

    context = _make_context(config)

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

    assert gathered == ["Draft reply"]
    assert [req.model for req in backend_service.requests] == [
        "fake_backend:guardian",
        "fake_backend:primary",
    ]
