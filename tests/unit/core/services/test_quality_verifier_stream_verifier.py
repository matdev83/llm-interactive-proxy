from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any, cast

import pytest
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
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


class DummyProvider:
    def __init__(self, backend_service: Any) -> None:
        self._backend_service = backend_service

    def get_required_service(self, _service_type: type[Any]) -> Any:
        return self._backend_service

    def get_service(self, _service_type: type[Any]) -> None:
        return None


class DummyAppState:
    def __init__(self) -> None:
        self._settings: dict[str, Any] = {}

    def get_setting(self, key: str, default: Any = None) -> Any:
        return self._settings.get(key, default)

    def set_setting(self, key: str, value: Any) -> None:
        self._settings[key] = value


async def _single_chunk_stream(content: str) -> AsyncIterator[ProcessedResponse]:
    yield ProcessedResponse(content=content, metadata={"is_done": True})


@pytest.mark.asyncio
async def test_stream_verifier_passes_through_and_stores_steering() -> None:
    quality_verifier_service = QualityVerifierService("openai:gpt-4o-mini")

    class DummyBackendService:
        def __init__(self) -> None:
            self.requests: list[Any] = []

        async def chat_completions(self, request, *args, **kwargs):
            self.requests.append(request)
            assert request.stream is True
            return type("R", (), {"content": "<steering>Fix result</steering>"})()

    backend_service = DummyBackendService()
    verifier = QualityVerifierStreamVerifier(
        quality_verifier_service_factory=DummyQualityVerifierFactory(
            quality_verifier_service
        ),
        provider=cast(Any, DummyProvider(backend_service)),
    )

    request = ChatRequest(
        model="openai:gpt-4o-mini",
        messages=[ChatMessage(role="user", content="question")],
    )
    streaming_context: dict[str, Any] = {
        "quality_verifier_model_spec": "openai:gpt-4o-mini",
        "quality_verifier_frequency": 1,
        "session_id": "session-1",
        "stream_id": "stream-1",
    }

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
            streaming_context,
            request_context=request_context,
        )
    ]

    assert [c.content for c in out] == ["draft output"]

    # Allow background assessment to run.
    await asyncio.sleep(0)

    assert len(backend_service.requests) == 1
    pending = app_state.get_setting(PENDING_QUALITY_VERIFIER_STEERING_SETTING_KEY, {})
    assert isinstance(pending, dict)
    assert "qv-sess-1" in pending


@pytest.mark.asyncio
async def test_stream_verifier_ignores_invalid_format_soft_fail() -> None:
    quality_verifier_service = QualityVerifierService("openai:gpt-4o-mini")

    class DummyBackendService:
        def __init__(self) -> None:
            self.requests: list[Any] = []

        async def chat_completions(self, request, *args, **kwargs):
            self.requests.append(request)
            return type("R", (), {"content": "still invalid"})()

    backend_service = DummyBackendService()
    verifier = QualityVerifierStreamVerifier(
        quality_verifier_service_factory=DummyQualityVerifierFactory(
            quality_verifier_service
        ),
        provider=cast(Any, DummyProvider(backend_service)),
    )

    request = ChatRequest(
        model="openai:gpt-4o-mini",
        messages=[ChatMessage(role="user", content="question")],
    )
    streaming_context: dict[str, Any] = {
        "quality_verifier_model_spec": "openai:gpt-4o-mini",
        "quality_verifier_frequency": 1,
        "session_id": "session-2",
        "stream_id": "stream-2",
    }

    app_state = DummyAppState()
    request_context = RequestContext(
        headers={},
        cookies={},
        state=None,
        app_state=app_state,
        session_id="session-2",
    )
    request_context.extensions["quality_verifier_effective_session_id"] = "qv-sess-2"

    out = [
        c
        async for c in verifier.verify_or_passthrough(
            request,
            _single_chunk_stream("draft output"),
            streaming_context,
            request_context=request_context,
        )
    ]

    assert [c.content for c in out] == ["draft output"]

    await asyncio.sleep(0)
    assert len(backend_service.requests) == 2
    pending = app_state.get_setting(PENDING_QUALITY_VERIFIER_STEERING_SETTING_KEY, {})
    assert pending == {}


@pytest.mark.asyncio
async def test_stream_verifier_treats_backend_error_response_as_failure() -> None:
    quality_verifier_service = QualityVerifierService("openai:gpt-4o-mini")

    class DummyBackendService:
        def __init__(self) -> None:
            self.requests: list[Any] = []

        async def chat_completions(self, request, *args, **kwargs):
            self.requests.append(request)
            return ResponseEnvelope(
                content={
                    "error": {
                        "message": "No capacity available",
                        "type": "backend_error",
                    }
                },
                status_code=503,
            )

    backend_service = DummyBackendService()
    verifier = QualityVerifierStreamVerifier(
        quality_verifier_service_factory=DummyQualityVerifierFactory(
            quality_verifier_service
        ),
        provider=cast(Any, DummyProvider(backend_service)),
    )

    request = ChatRequest(
        model="openai:gpt-4o-mini",
        messages=[ChatMessage(role="user", content="question")],
    )
    streaming_context: dict[str, Any] = {
        "quality_verifier_model_spec": "openai:gpt-4o-mini",
        "quality_verifier_frequency": 1,
        "session_id": "session-3",
        "stream_id": "stream-3",
    }

    app_state = DummyAppState()
    request_context = RequestContext(
        headers={},
        cookies={},
        state=None,
        app_state=app_state,
        session_id="session-3",
    )
    request_context.extensions["quality_verifier_effective_session_id"] = "qv-sess-3"

    out = [
        c
        async for c in verifier.verify_or_passthrough(
            request,
            _single_chunk_stream("draft output"),
            streaming_context,
            request_context=request_context,
        )
    ]

    assert [c.content for c in out] == ["draft output"]
    await asyncio.sleep(0)
    pending = app_state.get_setting(PENDING_QUALITY_VERIFIER_STEERING_SETTING_KEY, {})
    assert pending == {}


@pytest.mark.asyncio
async def test_stream_verifier_ttft_timeout_fails_open() -> None:
    quality_verifier_service = QualityVerifierService("openai:gpt-4o-mini")

    class DummyBackendService:
        async def chat_completions(self, request, *args, **kwargs):
            async def _stream() -> AsyncIterator[ProcessedResponse]:
                yield ProcessedResponse(content="", metadata={"_keepalive": True})
                await asyncio.sleep(0.05)
                yield ProcessedResponse(content="late token", metadata={})

            return StreamingResponseEnvelope(content=_stream())

    verifier = QualityVerifierStreamVerifier(
        quality_verifier_service_factory=DummyQualityVerifierFactory(
            quality_verifier_service
        ),
        provider=cast(Any, DummyProvider(DummyBackendService())),
    )

    request = ChatRequest(
        model="openai:gpt-4o-mini",
        messages=[ChatMessage(role="user", content="question")],
    )
    streaming_context: dict[str, Any] = {
        "quality_verifier_model_spec": "openai:gpt-4o-mini",
        "quality_verifier_frequency": 1,
        "quality_verifier_ttft_timeout_seconds": 0.01,
        "session_id": "session-4",
        "stream_id": "stream-4",
    }

    app_state = DummyAppState()
    request_context = RequestContext(
        headers={},
        cookies={},
        state=None,
        app_state=app_state,
        session_id="session-4",
    )
    request_context.extensions["quality_verifier_effective_session_id"] = "qv-sess-4"

    out = [
        c
        async for c in verifier.verify_or_passthrough(
            request,
            _single_chunk_stream("draft output"),
            streaming_context,
            request_context=request_context,
        )
    ]

    assert [c.content for c in out] == ["draft output"]
    await asyncio.sleep(0)
    pending = app_state.get_setting(PENDING_QUALITY_VERIFIER_STEERING_SETTING_KEY, {})
    assert pending == {}
