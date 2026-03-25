from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from typing import Any, cast

import pytest
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.backend_service_interface import IBackendService
from src.core.interfaces.quality_verifier_turn_ledger_interface import (
    IQualityVerifierTurnLedger,
)
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


class DummyTurnLedger:
    def __init__(self) -> None:
        self.reset_calls: list[tuple[str, Any]] = []

    def reset_quality_verifier_eligible_turn_count(
        self, session_key: str, session: Any | None
    ) -> None:
        self.reset_calls.append((session_key, session))


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
async def test_response_processor_inline_steering_recall_no_pending_store(
    monkeypatch,
) -> None:
    ledger = DummyTurnLedger()

    class DummyBRM:
        def __init__(self) -> None:
            self.calls: list[Any] = []

        async def process_backend_request(self, steered, session_id, recall_ctx):
            self.calls.append((steered, session_id, recall_ctx))
            assert steered.stream is False
            assert recall_ctx.extensions.get("quality_verifier_skip_verification")
            return ResponseEnvelope(
                content={"content": "recalled", "usage": {}, "metadata": {}}
            )

    brm = DummyBRM()
    proc = ResponseProcessor(
        response_parser=cast(IResponseParser, DummyParser()),
        stream_normalizer=cast(IStreamNormalizer, DummyStreamNormalizer("initial")),
        turn_ledger=ledger,
        backend_request_manager=brm,
    )

    qv_model = "openai:qv-steer-isolated"
    app_state = DummyAppState(model=qv_model, frequency=1)
    proc._app_state = app_state

    class DummyBackendService:
        def __init__(self) -> None:
            self.requests: list[Any] = []

        async def chat_completions(
            self, request, stream=False, allow_failover=True, context=None
        ):
            self.requests.append(request)
            assert request.stream is True
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
    ctx.extensions["quality_verifier_model"] = qv_model
    ctx.extensions["quality_verifier_frequency"] = 1

    pr = await proc.process_response(
        {"content": "initial"}, session_id="session-1", context=ctx
    )
    assert isinstance(pr, ProcessedResponse)
    assert pr.content == "recalled"

    assert len(backend_service.requests) == 1
    assert len(brm.calls) == 1
    assert ledger.reset_calls == [("qv-sess-1", None)]
    pending = app_state.get_setting(PENDING_QUALITY_VERIFIER_STEERING_SETTING_KEY, {})
    assert pending == {}


@pytest.mark.asyncio
async def test_response_processor_quality_verifier_invalid_output_soft_fails(
    monkeypatch,
) -> None:
    proc = ResponseProcessor(
        response_parser=cast(IResponseParser, DummyParser()),
        stream_normalizer=cast(IStreamNormalizer, DummyStreamNormalizer("initial")),
    )
    qv_model = "openai:qv-invalid-isolated"
    app_state = DummyAppState(model=qv_model, frequency=1)
    proc._app_state = app_state

    class DummyBackendService:
        def __init__(self) -> None:
            self.call_count = 0

        async def chat_completions(self, request, *args, **kwargs):
            self.call_count += 1
            return type("R", (), {"content": "free form"})()

    backend = DummyBackendService()

    class DummyProvider:
        def get_required_service(self, t):
            return backend

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
    ctx.extensions["quality_verifier_model"] = qv_model
    ctx.extensions["quality_verifier_frequency"] = 1

    pr = await proc.process_response(
        {"content": "initial"}, session_id="session-2", context=ctx
    )
    assert pr.content == "initial"

    assert backend.call_count == 2
    pending = app_state.get_setting(PENDING_QUALITY_VERIFIER_STEERING_SETTING_KEY, {})
    assert pending == {}


@pytest.mark.asyncio
async def test_non_streaming_qv_pass_resets_ledger_via_provider_when_ctor_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If ``turn_ledger`` was not injected, reset still runs via ``get_service_provider``."""
    ledger = DummyTurnLedger()
    qv_model = "openai:qv-ledger-lazy-pass"

    class DummyBackendService:
        async def chat_completions(
            self, request: Any, *args: Any, **kwargs: Any
        ) -> Any:
            return type("R", (), {"content": "<status>NO_STEERING_NEEDED</status>"})()

    backend_service = DummyBackendService()

    class DummyProvider:
        def get_required_service(self, t: Any) -> Any:
            if t is IQualityVerifierTurnLedger:
                return ledger
            if t is IBackendService:
                return backend_service
            return backend_service

        def get_service(self, _t: Any) -> None:
            return None

    monkeypatch.setattr(
        "src.core.di.services.get_service_provider", lambda: DummyProvider()
    )

    proc = ResponseProcessor(
        response_parser=cast(IResponseParser, DummyParser()),
        stream_normalizer=cast(IStreamNormalizer, DummyStreamNormalizer("out")),
        turn_ledger=None,
        backend_request_manager=None,
    )
    app_state = DummyAppState(model=qv_model, frequency=1)
    proc._app_state = app_state

    ctx = RequestContext(
        headers={},
        cookies={},
        state=None,
        app_state=app_state,
        original_request=ChatRequest(
            model="m",
            messages=[ChatMessage(role="user", content="Hi")],
        ),
        session_id="sess-ledger-lazy",
        extensions={
            "quality_verifier_model": qv_model,
            "quality_verifier_frequency": 1,
            "quality_verifier_effective_session_id": "qv-eff-lazy",
        },
    )

    pr = await proc.process_response(
        {"content": "out"}, session_id="sess-ledger-lazy", context=ctx
    )
    assert pr.content == "out"
    assert ledger.reset_calls == [("qv-eff-lazy", None)]


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
    qv_model = "openai:qv-ttft-isolated"
    app_state = DummyAppState(model=qv_model, frequency=1)
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
    ctx.extensions["quality_verifier_model"] = qv_model
    ctx.extensions["quality_verifier_frequency"] = 1
    ctx.extensions["quality_verifier_ttft_timeout_seconds"] = 0.01

    pr = await proc.process_response(
        {"content": "initial"}, session_id="session-4", context=ctx
    )
    assert pr.content == "initial"

    await asyncio.sleep(0)
    pending = app_state.get_setting(PENDING_QUALITY_VERIFIER_STEERING_SETTING_KEY, {})
    assert pending == {}
