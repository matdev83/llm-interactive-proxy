from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from typing import Any, cast

import pytest
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import StreamingResponseEnvelope
from src.core.interfaces.response_parser_interface import IResponseParser
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.interfaces.streaming_response_processor_interface import IStreamNormalizer
from src.core.ports.streaming_contracts import StreamingContent
from src.core.services.quality_verifier_steering_store import (
    PENDING_QUALITY_VERIFIER_STEERING_SETTING_KEY,
)
from src.core.services.response_processor_service import ResponseProcessor


class DummyParser:
    def parse_response(self, response: Any) -> Any:
        return response

    def extract_content(self, response: Any) -> Any:
        return response.get("content")

    def extract_usage(self, response: Any) -> Any:
        return response.get("usage")

    def extract_metadata(self, response: Any) -> Any:
        return response.get("metadata")


class DummyStreamNormalizer:
    """Minimal stream normalizer that produces a single done chunk."""

    def __init__(self, content: str = "initial") -> None:
        self._content = content

    async def process_stream(
        self, stream: Any, output_format: str = "objects", cancel_callback: Any = None
    ) -> AsyncGenerator[StreamingContent, None]:
        yield StreamingContent(
            content=self._content,
            is_done=True,
            metadata={},
        )

    def reset(self) -> None:
        pass


class DummyAppState:
    def __init__(
        self, *, model: str | None = "openai:gpt-4o-mini", frequency: int = 1
    ) -> None:
        self._model = model
        self._frequency = frequency
        self._settings: dict[str, Any] = {}

    def get_setting(self, key: str, default: Any = None) -> Any:
        if key == "app_config":

            class Sess:
                quality_verifier_model = self._model
                quality_verifier_frequency = self._frequency

            class Cfg:
                session = Sess()

            return Cfg()

        return self._settings.get(key, default)

    def set_setting(self, key: str, value: Any) -> None:
        self._settings[key] = value

    def get_service(self, _t: Any) -> Any:
        return None


@pytest.mark.asyncio
async def test_response_processor_stores_steering_without_modifying_content(
    monkeypatch,
) -> None:
    proc = ResponseProcessor(
        response_parser=cast(IResponseParser, DummyParser()),
        stream_normalizer=cast(IStreamNormalizer, DummyStreamNormalizer("initial")),
    )

    app_state = DummyAppState(model="openai:gpt-4o-mini", frequency=1)
    proc._app_state = app_state

    class DummyBackendService:
        def __init__(self) -> None:
            self.requests: list[Any] = []

        async def chat_completions(
            self, request, stream=False, allow_failover=True, context=None
        ):
            self.requests.append(request)
            assert request.stream is False
            assert request.messages[-1].role == "assistant"
            assert request.messages[-1].content == "initial"
            return type("R", (), {"content": "<steering>Fix it</steering>"})()

    backend_service = DummyBackendService()

    class DummyProvider:
        def get_required_service(self, t):
            return backend_service

        def get_service(self, t):
            return None

    monkeypatch.setattr(
        "src.core.di.services.get_service_provider", lambda: DummyProvider()
    )

    original_req = ChatRequest(
        model="openai:gpt-4o-mini", messages=[ChatMessage(role="user", content="Hi")]
    )
    ctx = RequestContext(
        headers={},
        cookies={},
        state=None,
        app_state=app_state,
        original_request=original_req,
        session_id="session-1",
    )
    ctx.extensions["quality_verifier_effective_session_id"] = "qv-sess-1"

    pr = await proc.process_response(
        {"content": "initial"}, session_id="session-1", context=ctx
    )
    assert isinstance(pr, ProcessedResponse)
    assert pr.content == "initial"

    # Let background verifier run.
    await asyncio.sleep(0)

    assert len(backend_service.requests) == 1
    pending = app_state.get_setting(PENDING_QUALITY_VERIFIER_STEERING_SETTING_KEY, {})
    assert isinstance(pending, dict)
    assert "qv-sess-1" in pending


@pytest.mark.asyncio
async def test_response_processor_quality_verifier_invalid_output_soft_fails(
    monkeypatch,
) -> None:
    proc = ResponseProcessor(
        response_parser=cast(IResponseParser, DummyParser()),
        stream_normalizer=cast(IStreamNormalizer, DummyStreamNormalizer("initial")),
    )
    app_state = DummyAppState(model="openai:gpt-4o-mini", frequency=1)
    proc._app_state = app_state

    class DummyBackendService:
        async def chat_completions(self, request, *args, **kwargs):
            return type("R", (), {"content": "free form"})()

    class DummyProvider:
        def get_required_service(self, t):
            return DummyBackendService()

        def get_service(self, t):
            return None

    monkeypatch.setattr(
        "src.core.di.services.get_service_provider", lambda: DummyProvider()
    )

    original_req = ChatRequest(
        model="openai:gpt-4o-mini", messages=[ChatMessage(role="user", content="Hi")]
    )
    ctx = RequestContext(
        headers={},
        cookies={},
        state=None,
        app_state=app_state,
        original_request=original_req,
        session_id="session-2",
    )
    ctx.extensions["quality_verifier_effective_session_id"] = "qv-sess-2"

    pr = await proc.process_response(
        {"content": "initial"}, session_id="session-2", context=ctx
    )
    assert pr.content == "initial"

    await asyncio.sleep(0)
    pending = app_state.get_setting(PENDING_QUALITY_VERIFIER_STEERING_SETTING_KEY, {})
    assert pending == {}


@pytest.mark.asyncio
async def test_response_processor_quality_verifier_respects_frequency(
    monkeypatch,
) -> None:
    proc = ResponseProcessor(
        response_parser=cast(IResponseParser, DummyParser()),
        stream_normalizer=cast(IStreamNormalizer, DummyStreamNormalizer("initial")),
    )
    app_state = DummyAppState(model="openai:gpt-4o-mini", frequency=5)
    proc._app_state = app_state

    class FailingBackendService:
        async def chat_completions(self, *args, **kwargs):
            pytest.fail("Quality Verifier should not run before frequency threshold")

    class DummyProvider:
        def get_required_service(self, t):
            return FailingBackendService()

        def get_service(self, t):
            return None

    monkeypatch.setattr(
        "src.core.di.services.get_service_provider", lambda: DummyProvider()
    )

    original_req = ChatRequest(
        model="openai:gpt-4o-mini", messages=[ChatMessage(role="user", content="Hi")]
    )
    ctx = RequestContext(
        headers={},
        cookies={},
        state=None,
        app_state=app_state,
        original_request=original_req,
        session_id="session-3",
    )
    ctx.extensions["quality_verifier_effective_session_id"] = "qv-sess-3"

    pr = await proc.process_response(
        {"content": "initial"}, session_id="session-3", context=ctx
    )
    assert pr.content == "initial"

    await asyncio.sleep(0)
    pending = app_state.get_setting(PENDING_QUALITY_VERIFIER_STEERING_SETTING_KEY, {})
    assert pending == {}


@pytest.mark.asyncio
async def test_response_processor_quality_verifier_ttft_timeout_soft_fails(
    monkeypatch,
) -> None:
    proc = ResponseProcessor(
        response_parser=cast(IResponseParser, DummyParser()),
        stream_normalizer=cast(IStreamNormalizer, DummyStreamNormalizer("initial")),
    )
    app_state = DummyAppState(model="openai:gpt-4o-mini", frequency=1)
    proc._app_state = app_state

    class DummyBackendService:
        async def chat_completions(self, request, *args, **kwargs):
            async def _stream() -> AsyncGenerator[ProcessedResponse, None]:
                yield ProcessedResponse(content="", metadata={"_keepalive": True})
                await asyncio.sleep(0.05)
                yield ProcessedResponse(content="late verifier token", metadata={})

            return StreamingResponseEnvelope(content=_stream())

    class DummyProvider:
        def get_required_service(self, t):
            return DummyBackendService()

        def get_service(self, t):
            return None

    monkeypatch.setattr(
        "src.core.di.services.get_service_provider", lambda: DummyProvider()
    )

    original_req = ChatRequest(
        model="openai:gpt-4o-mini", messages=[ChatMessage(role="user", content="Hi")]
    )
    ctx = RequestContext(
        headers={},
        cookies={},
        state=None,
        app_state=app_state,
        original_request=original_req,
        session_id="session-4",
    )
    ctx.extensions["quality_verifier_effective_session_id"] = "qv-sess-4"
    ctx.extensions["quality_verifier_ttft_timeout_seconds"] = 0.01

    pr = await proc.process_response(
        {"content": "initial"}, session_id="session-4", context=ctx
    )
    assert pr.content == "initial"

    await asyncio.sleep(0)
    pending = app_state.get_setting(PENDING_QUALITY_VERIFIER_STEERING_SETTING_KEY, {})
    assert pending == {}
