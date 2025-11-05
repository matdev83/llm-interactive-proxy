from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import StreamingResponseEnvelope
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.backend_request_manager_service import BackendRequestManager


def _make_context(app_state: Any) -> RequestContext:
    return RequestContext(
        headers={},
        cookies={},
        state=None,
        app_state=app_state,
        client_host=None,
        session_id=None,
        agent=None,
        original_request=None,
        processing_context=None,
    )


class _DummyAppState:
    def __init__(self, angel_model: str | None = None) -> None:
        self._angel_model = angel_model

    def get_setting(self, key: str) -> Any:
        if key == "app_config":

            class Session:
                angel_model = self._angel_model

            class Config:
                session = Session()

            return Config()
        return None


def _build_stream(chunks: list[ProcessedResponse]) -> AsyncIterator[ProcessedResponse]:
    async def _iterator() -> AsyncIterator[ProcessedResponse]:
        for chunk in chunks:
            yield chunk

    return _iterator()


@pytest.mark.asyncio
async def test_streaming_angel_pass_forwards_original(monkeypatch) -> None:
    backend_processor = AsyncMock()
    response_processor = MagicMock()
    manager = BackendRequestManager(backend_processor, response_processor)

    original_request = ChatRequest(
        model="openai:gpt-4o-mini",
        messages=[ChatMessage(role="user", content="Hi")],
        stream=True,
    )

    chunks = [
        ProcessedResponse(content="Hello", metadata={}),
        ProcessedResponse(content=" world", metadata={"is_done": True}),
    ]
    stream_envelope = StreamingResponseEnvelope(content=_build_stream(chunks))

    class DummyBackendService:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def chat_completions(self, request, *_, **__):
            self.calls.append("angel")
            return type(
                "R",
                (),
                {"content": "<angels_decision>Pass</angels_decision>"},
            )()

    backend_service = DummyBackendService()

    class DummyProvider:
        def get_required_service(self, _t):
            return backend_service

    monkeypatch.setattr(
        "src.core.di.services.get_service_provider",
        lambda: DummyProvider(),
        raising=False,
    )

    context = _make_context(_DummyAppState("openai:gpt-4o-mini"))

    result = await manager._process_streaming_response(
        stream_envelope, original_request, "session-pass", context
    )

    assert isinstance(result, StreamingResponseEnvelope)
    forwarded: list[str] = []
    assert result.content is not None
    async for chunk in result.content:
        forwarded.append(str(chunk.content))

    assert forwarded == ["Hello", " world"]
    assert backend_service.calls == ["angel"]


@pytest.mark.asyncio
async def test_streaming_angel_steer_replaces_with_correction(monkeypatch) -> None:
    backend_processor = AsyncMock()
    response_processor = MagicMock()
    manager = BackendRequestManager(backend_processor, response_processor)

    original_request = ChatRequest(
        model="openai:gpt-4o-mini",
        messages=[ChatMessage(role="user", content="Hi")],
        stream=True,
    )

    chunks = [
        ProcessedResponse(content="Bad", metadata={}),
        ProcessedResponse(content=" output", metadata={"is_done": True}),
    ]
    stream_envelope = StreamingResponseEnvelope(content=_build_stream(chunks))

    class DummyBackendService:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def chat_completions(self, request, *_, **__):
            if any(msg.role == "assistant" for msg in request.messages):
                self.calls.append("angel")
                return type(
                    "R",
                    (),
                    {
                        "content": "\n<angels_steering_message>Be specific</angels_steering_message>\n"
                    },
                )()
            self.calls.append("correction")
            return type("R", (), {"content": "Corrected answer"})()

    backend_service = DummyBackendService()

    class DummyProvider:
        def get_required_service(self, _t):
            return backend_service

    monkeypatch.setattr(
        "src.core.di.services.get_service_provider",
        lambda: DummyProvider(),
        raising=False,
    )

    context = _make_context(_DummyAppState("openai:gpt-4o-mini"))

    result = await manager._process_streaming_response(
        stream_envelope, original_request, "session-steer", context
    )

    assert isinstance(result, StreamingResponseEnvelope)
    assert result.content is not None
    chunks_out: list[str] = []
    async for chunk in result.content:
        chunks_out.append(str(chunk.content))

    assert chunks_out == ["Corrected answer"]
    assert backend_service.calls == ["angel", "correction"]
