from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any, cast

import pytest
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.backend_request_manager_interface import IBackendRequestManager
from src.core.interfaces.backend_service_interface import IBackendService
from src.core.interfaces.quality_verifier_turn_ledger_interface import (
    IQualityVerifierTurnLedger,
)
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.backend_request_manager.quality_verifier_stream_verifier import (
    QualityVerifierStreamVerifier,
)
from src.core.services.quality_verifier_service import QualityVerifierService
from src.core.services.quality_verifier_steering_store import (
    PENDING_QUALITY_VERIFIER_STEERING_SETTING_KEY,
)


class DummyQualityVerifierFactory:
    def __init__(self, service: QualityVerifierService) -> None:
        self._service = service

    def create(self, *args: Any, **kwargs: Any) -> QualityVerifierService:
        return self._service


class DummyTurnLedger:
    def __init__(self) -> None:
        self.reset_calls: list[tuple[str, Any]] = []

    def reset_quality_verifier_eligible_turn_count(
        self, session_key: str, session: Any | None
    ) -> None:
        self.reset_calls.append((session_key, session))


class MultiServiceProvider:
    """Dispatches get_required_service by interface type."""

    def __init__(
        self,
        backend_service: Any,
        backend_request_manager: Any,
        turn_ledger: Any | None = None,
    ) -> None:
        self._backend_service = backend_service
        self._backend_request_manager = backend_request_manager
        self._turn_ledger = turn_ledger

    def get_required_service(self, service_type: type[Any]) -> Any:
        if service_type is IBackendService:
            return self._backend_service
        if service_type is IBackendRequestManager:
            return self._backend_request_manager
        if service_type is IQualityVerifierTurnLedger:
            if self._turn_ledger is None:
                raise RuntimeError("turn_ledger not configured for this provider")
            return self._turn_ledger
        raise RuntimeError(f"Unexpected service {service_type}")

    def get_service(self, _service_type: type[Any]) -> None:
        return None


async def _single_chunk_stream(content: str) -> AsyncIterator[ProcessedResponse]:
    yield ProcessedResponse(content=content, metadata={"is_done": True})


def _scheduled_context(session_id: str, stream_id: str) -> dict[str, Any]:
    return {
        "quality_verifier_model_spec": "openai:gpt-4o-mini",
        "quality_verifier_frequency": 1,
        "quality_verifier_eligible_turn_count": 1000,
        "session_id": session_id,
        "stream_id": stream_id,
    }


class DummyAppState:
    def __init__(self) -> None:
        self._settings: dict[str, Any] = {}

    def get_setting(self, key: str, default: Any = None) -> Any:
        return self._settings.get(key, default)

    def set_setting(self, key: str, value: Any) -> None:
        self._settings[key] = value


@pytest.mark.asyncio
async def test_stream_verifier_buffers_then_yields_recall_on_steer() -> None:
    qv_svc = QualityVerifierService("openai:gpt-4o-mini")

    class DummyBackendService:
        def __init__(self) -> None:
            self.requests: list[Any] = []

        async def chat_completions(self, request, *args, **kwargs):
            self.requests.append(request)
            assert request.stream is True

            async def _vstream() -> AsyncIterator[ProcessedResponse]:
                yield ProcessedResponse(
                    content="<steering>Fix result</steering>", metadata={}
                )

            return StreamingResponseEnvelope(content=_vstream())

    class DummyBRM:
        def __init__(self) -> None:
            self.calls: list[Any] = []

        async def process_backend_request(self, req, session_id, ctx):
            self.calls.append((req, session_id, ctx))
            assert req.stream is True
            assert ctx.extensions.get("quality_verifier_skip_verification") is True
            assert ctx.extensions.get("auxiliary_request") is True

            async def _r() -> AsyncIterator[ProcessedResponse]:
                yield ProcessedResponse(content="recalled", metadata={"is_done": True})

            return StreamingResponseEnvelope(content=_r())

    backend_service = DummyBackendService()
    brm = DummyBRM()
    ledger = DummyTurnLedger()
    verifier = QualityVerifierStreamVerifier(
        quality_verifier_service_factory=DummyQualityVerifierFactory(qv_svc),
        provider=cast(Any, MultiServiceProvider(backend_service, brm)),
        turn_ledger=ledger,
    )

    request = ChatRequest(
        model="openai:gpt-4o-mini",
        messages=[ChatMessage(role="user", content="question")],
    )
    app_state = DummyAppState()
    request_context = RequestContext(
        headers={},
        cookies={},
        state=None,
        app_state=app_state,
        session_id="session-1",
    )
    request_context.extensions["quality_verifier_effective_session_id"] = "qv-sess-1"

    out = [
        c
        async for c in verifier.verify_or_passthrough(
            request,
            _single_chunk_stream("draft output"),
            _scheduled_context("session-1", "stream-1"),
            request_context=request_context,
        )
    ]

    assert [c.content for c in out] == ["recalled"]
    assert len(backend_service.requests) == 1
    assert len(brm.calls) == 1
    assert ledger.reset_calls
    pending = app_state.get_setting(PENDING_QUALITY_VERIFIER_STEERING_SETTING_KEY, {})
    assert pending == {}


@pytest.mark.asyncio
async def test_stream_verifier_pass_resets_ledger_via_provider_when_ctor_none() -> None:
    qv_model = "openai:qv-stream-ledger-lazy"
    qv_svc = QualityVerifierService(qv_model)

    class DummyBackendService:
        async def chat_completions(
            self, request: Any, *args: Any, **kwargs: Any
        ) -> Any:
            async def _vstream() -> AsyncIterator[ProcessedResponse]:
                yield ProcessedResponse(
                    content="<status>NO_STEERING_NEEDED</status>",
                    metadata={},
                )

            return StreamingResponseEnvelope(content=_vstream())

    class DummyBRM:
        async def process_backend_request(self, *args: Any, **kwargs: Any) -> Any:
            raise AssertionError("recall should not run")

    ledger = DummyTurnLedger()
    streaming_ctx = _scheduled_context("s1", "t1")
    streaming_ctx["quality_verifier_model_spec"] = qv_model

    request_context = RequestContext(
        headers={},
        cookies={},
        state=None,
        app_state=DummyAppState(),
        session_id="s1",
    )
    request_context.extensions["quality_verifier_effective_session_id"] = (
        "qv-eff-stream-lazy"
    )

    verifier = QualityVerifierStreamVerifier(
        quality_verifier_service_factory=DummyQualityVerifierFactory(qv_svc),
        provider=cast(
            Any,
            MultiServiceProvider(DummyBackendService(), DummyBRM(), turn_ledger=ledger),
        ),
        turn_ledger=None,
    )
    request = ChatRequest(
        model="openai:gpt-4o-mini",
        messages=[ChatMessage(role="user", content="q")],
    )

    out = [
        c
        async for c in verifier.verify_or_passthrough(
            request,
            _single_chunk_stream("hello"),
            streaming_ctx,
            request_context=request_context,
        )
    ]

    assert [c.content for c in out] == ["hello"]
    assert ledger.reset_calls == [("qv-eff-stream-lazy", None)]


@pytest.mark.asyncio
async def test_stream_verifier_invalid_format_yields_buffer() -> None:
    qv_svc = QualityVerifierService("openai:gpt-4o-mini")

    class DummyBackendService:
        def __init__(self) -> None:
            self.requests: list[Any] = []

        async def chat_completions(self, request, *args, **kwargs):
            self.requests.append(request)

            async def _vstream() -> AsyncIterator[ProcessedResponse]:
                yield ProcessedResponse(content="not xml", metadata={})

            return StreamingResponseEnvelope(content=_vstream())

    class DummyBRM:
        async def process_backend_request(self, *args, **kwargs):
            raise AssertionError("recall should not run")

    backend_service = DummyBackendService()
    ledger = DummyTurnLedger()
    verifier = QualityVerifierStreamVerifier(
        quality_verifier_service_factory=DummyQualityVerifierFactory(qv_svc),
        provider=cast(Any, MultiServiceProvider(backend_service, DummyBRM())),
        turn_ledger=ledger,
    )

    request = ChatRequest(
        model="openai:gpt-4o-mini",
        messages=[ChatMessage(role="user", content="question")],
    )
    request_context = RequestContext(
        headers={},
        cookies={},
        state=None,
        app_state=DummyAppState(),
        session_id="session-2",
    )
    request_context.extensions["quality_verifier_effective_session_id"] = "qv-sess-2"

    out = [
        c
        async for c in verifier.verify_or_passthrough(
            request,
            _single_chunk_stream("draft output"),
            _scheduled_context("session-2", "stream-2"),
            request_context=request_context,
        )
    ]

    assert [c.content for c in out] == ["draft output"]
    assert len(backend_service.requests) == 2
    assert ledger.reset_calls


@pytest.mark.asyncio
async def test_stream_verifier_backend_error_yields_buffer() -> None:
    qv_svc = QualityVerifierService("openai:gpt-4o-mini")

    class DummyBackendService:
        async def chat_completions(self, request, *args, **kwargs):
            return ResponseEnvelope(
                content={
                    "error": {
                        "message": "No capacity available",
                        "type": "backend_error",
                    }
                },
                status_code=503,
            )

    class DummyBRM:
        async def process_backend_request(self, *args, **kwargs):
            raise AssertionError("recall should not run")

    ledger = DummyTurnLedger()
    verifier = QualityVerifierStreamVerifier(
        quality_verifier_service_factory=DummyQualityVerifierFactory(qv_svc),
        provider=cast(Any, MultiServiceProvider(DummyBackendService(), DummyBRM())),
        turn_ledger=ledger,
    )

    request = ChatRequest(
        model="openai:gpt-4o-mini",
        messages=[ChatMessage(role="user", content="question")],
    )
    request_context = RequestContext(
        headers={},
        cookies={},
        state=None,
        app_state=DummyAppState(),
        session_id="session-3",
    )
    request_context.extensions["quality_verifier_effective_session_id"] = "qv-sess-3"

    out = [
        c
        async for c in verifier.verify_or_passthrough(
            request,
            _single_chunk_stream("draft output"),
            _scheduled_context("session-3", "stream-3"),
            request_context=request_context,
        )
    ]

    assert [c.content for c in out] == ["draft output"]
    assert ledger.reset_calls


@pytest.mark.asyncio
async def test_stream_verifier_ttft_timeout_yields_buffer() -> None:
    qv_svc = QualityVerifierService("openai:gpt-4o-mini")

    class DummyBackendService:
        async def chat_completions(self, request, *args, **kwargs):
            async def _stream() -> AsyncIterator[ProcessedResponse]:
                yield ProcessedResponse(content="", metadata={"_keepalive": True})
                await asyncio.sleep(0.05)
                yield ProcessedResponse(content="late token", metadata={})

            return StreamingResponseEnvelope(content=_stream())

    class DummyBRM:
        async def process_backend_request(self, *args, **kwargs):
            raise AssertionError("recall should not run")

    ledger = DummyTurnLedger()
    verifier = QualityVerifierStreamVerifier(
        quality_verifier_service_factory=DummyQualityVerifierFactory(qv_svc),
        provider=cast(Any, MultiServiceProvider(DummyBackendService(), DummyBRM())),
        turn_ledger=ledger,
    )

    request = ChatRequest(
        model="openai:gpt-4o-mini",
        messages=[ChatMessage(role="user", content="question")],
    )
    ctx = _scheduled_context("session-4", "stream-4")
    ctx["quality_verifier_ttft_timeout_seconds"] = 0.01

    request_context = RequestContext(
        headers={},
        cookies={},
        state=None,
        app_state=DummyAppState(),
        session_id="session-4",
    )
    request_context.extensions["quality_verifier_effective_session_id"] = "qv-sess-4"

    out = [
        c
        async for c in verifier.verify_or_passthrough(
            request,
            _single_chunk_stream("draft output"),
            ctx,
            request_context=request_context,
        )
    ]

    assert [c.content for c in out] == ["draft output"]
    assert ledger.reset_calls


@pytest.mark.asyncio
async def test_stream_verifier_passthrough_when_not_scheduled() -> None:
    qv_svc = QualityVerifierService("openai:gpt-4o-mini")

    class DummyBackendService:
        async def chat_completions(self, *args, **kwargs):
            raise AssertionError("verifier should not run")

    class DummyBRM:
        async def process_backend_request(self, *args, **kwargs):
            raise AssertionError("recall should not run")

    ledger = DummyTurnLedger()
    verifier = QualityVerifierStreamVerifier(
        quality_verifier_service_factory=DummyQualityVerifierFactory(qv_svc),
        provider=cast(Any, MultiServiceProvider(DummyBackendService(), DummyBRM())),
        turn_ledger=ledger,
    )

    request = ChatRequest(
        model="openai:gpt-4o-mini",
        messages=[ChatMessage(role="user", content="question")],
    )
    # eligible floor 2 with frequency 2 -> 2 % 2 == 0 but need floor > 0; use 2000 scaled
    streaming_context: dict[str, Any] = {
        "quality_verifier_model_spec": "openai:gpt-4o-mini",
        "quality_verifier_frequency": 3,
        "quality_verifier_eligible_turn_count": 2000,
        "session_id": "s",
        "stream_id": "t",
    }

    out = [
        c
        async for c in verifier.verify_or_passthrough(
            request,
            _single_chunk_stream("x"),
            streaming_context,
            request_context=None,
        )
    ]

    assert [c.content for c in out] == ["x"]
    assert not ledger.reset_calls
