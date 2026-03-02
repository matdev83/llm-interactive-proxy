from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import StreamingResponseEnvelope
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.quality_verifier_steering_store import (
    PENDING_QUALITY_VERIFIER_STEERING_SETTING_KEY,
)

from tests.helpers.backend_request_manager_fixtures import (
    create_backend_request_manager,
)


class _DummyAppState:
    def __init__(
        self,
        quality_verifier_model: str | None = None,
        quality_verifier_frequency: int = 1,
    ) -> None:
        self._quality_verifier_model = quality_verifier_model
        self._quality_verifier_frequency = quality_verifier_frequency
        self._settings: dict[str, Any] = {}

    def get_setting(self, key: str, default: Any = None) -> Any:
        if key == "app_config":

            class Session:
                quality_verifier_model = self._quality_verifier_model
                quality_verifier_frequency = self._quality_verifier_frequency

            class Config:
                session = Session()

            return Config()
        return self._settings.get(key, default)

    def set_setting(self, key: str, value: Any) -> None:
        self._settings[key] = value

    def get_service(self, _t: Any) -> Any:
        return None


def _make_context(app_state: Any) -> RequestContext:
    extensions: dict[str, Any] = {}
    if app_state and getattr(app_state, "_quality_verifier_model", None):
        extensions["quality_verifier_model"] = app_state._quality_verifier_model
    if (
        app_state
        and getattr(app_state, "_quality_verifier_frequency", None) is not None
    ):
        extensions["quality_verifier_frequency"] = app_state._quality_verifier_frequency
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
        extensions=extensions,
    )


def _build_stream(chunks: list[ProcessedResponse]) -> AsyncIterator[ProcessedResponse]:
    async def _iterator() -> AsyncIterator[ProcessedResponse]:
        for chunk in chunks:
            yield chunk

    return _iterator()


@pytest.mark.asyncio
async def test_streaming_quality_verifier_no_steering_forwards_original() -> None:
    backend_processor = AsyncMock()
    response_processor = MagicMock()
    response_processor.process_streaming_response = (
        lambda stream, _session_id, context=None, **kwargs: stream
    )

    class DummyBackendService:
        def __init__(self) -> None:
            self.calls: int = 0

        async def chat_completions(self, request, *_, **__):
            self.calls += 1
            return type(
                "R",
                (),
                {"content": "<status>NO_STEERING_NEEDED</status>"},
            )()

    backend_service = DummyBackendService()

    class DummyProvider:
        def get_required_service(self, _t):
            return backend_service

        def get_service(self, _t):
            return None

    manager = create_backend_request_manager(
        backend_processor=backend_processor,
        response_processor=response_processor,
        mock_provider=DummyProvider(),
    )

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
    backend_processor.process_backend_request.return_value = stream_envelope

    app_state = _DummyAppState("openai:gpt-4o-mini", quality_verifier_frequency=1)
    context = _make_context(app_state)
    context.original_request = original_request

    result = await manager.process_backend_request(
        original_request, "session-pass", context
    )
    assert isinstance(result, StreamingResponseEnvelope)
    assert result.content is not None
    forwarded: list[str] = []
    async for chunk in result.content:
        forwarded.append(str(chunk.content))
    assert "Hello world" in "".join(forwarded)

    await asyncio.sleep(0)
    assert backend_service.calls == 1
    pending = app_state.get_setting(PENDING_QUALITY_VERIFIER_STEERING_SETTING_KEY, {})
    assert pending == {}


@pytest.mark.asyncio
async def test_streaming_quality_verifier_steering_forwards_original_and_stores() -> (
    None
):
    backend_processor = AsyncMock()
    response_processor = MagicMock()
    response_processor.process_streaming_response = (
        lambda stream, _session_id, context=None, **kwargs: stream
    )

    class DummyBackendService:
        def __init__(self) -> None:
            self.calls: int = 0

        async def chat_completions(self, request, *_, **__):
            self.calls += 1
            return type(
                "R",
                (),
                {"content": "<steering>Be specific</steering>"},
            )()

    backend_service = DummyBackendService()

    class DummyProvider:
        def get_required_service(self, _t):
            return backend_service

        def get_service(self, _t):
            return None

    manager = create_backend_request_manager(
        backend_processor=backend_processor,
        response_processor=response_processor,
        mock_provider=DummyProvider(),
    )

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
    backend_processor.process_backend_request.return_value = stream_envelope

    app_state = _DummyAppState("openai:gpt-4o-mini", quality_verifier_frequency=1)
    context = _make_context(app_state)
    context.original_request = original_request

    result = await manager.process_backend_request(
        original_request, "session-steer", context
    )
    assert isinstance(result, StreamingResponseEnvelope)
    assert result.content is not None
    out: list[str] = []
    async for chunk in result.content:
        out.append(str(chunk.content))
    assert "Bad output" in "".join(out)

    await asyncio.sleep(0)
    assert backend_service.calls == 1
    pending = app_state.get_setting(PENDING_QUALITY_VERIFIER_STEERING_SETTING_KEY, {})
    assert isinstance(pending, dict)
    assert "session-steer" in pending


@pytest.mark.asyncio
async def test_streaming_quality_verifier_respects_frequency() -> None:
    backend_processor = AsyncMock()
    response_processor = MagicMock()
    response_processor.process_streaming_response = (
        lambda stream, _session_id, context=None, **kwargs: stream
    )

    class DummyBackendService:
        async def chat_completions(self, *args, **kwargs):
            pytest.fail("Quality Verifier should not run before frequency threshold")

    class DummyProvider:
        def get_required_service(self, _t):
            return DummyBackendService()

        def get_service(self, _t):
            return None

    manager = create_backend_request_manager(
        backend_processor=backend_processor,
        response_processor=response_processor,
        mock_provider=DummyProvider(),
    )

    original_request = ChatRequest(
        model="openai:gpt-4o-mini",
        messages=[ChatMessage(role="user", content="Hi")],
        stream=True,
    )

    chunks = [
        ProcessedResponse(content="No verifier", metadata={}),
        ProcessedResponse(content=" needed", metadata={"is_done": True}),
    ]
    stream_envelope = StreamingResponseEnvelope(content=_build_stream(chunks))
    backend_processor.process_backend_request.return_value = stream_envelope

    app_state = _DummyAppState("openai:gpt-4o-mini", quality_verifier_frequency=5)
    context = _make_context(app_state)
    context.original_request = original_request

    result = await manager.process_backend_request(
        original_request, "session-skip", context
    )
    assert isinstance(result, StreamingResponseEnvelope)
    assert result.content is not None
    out: list[str] = []
    async for chunk in result.content:
        out.append(str(chunk.content))
    assert "No verifier needed" in "".join(out)

    await asyncio.sleep(0)
    pending = app_state.get_setting(PENDING_QUALITY_VERIFIER_STEERING_SETTING_KEY, {})
    assert pending == {}
