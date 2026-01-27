from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import StreamingResponseEnvelope
from src.core.interfaces.response_processor_interface import ProcessedResponse

from tests.helpers.backend_request_manager_fixtures import (
    create_backend_request_manager,
)


def _make_context(app_state: Any) -> RequestContext:
    extensions = {}
    if app_state and hasattr(app_state, "_angel_model") and app_state._angel_model:
        extensions["angel_model"] = app_state._angel_model
    if app_state and hasattr(app_state, "_angel_frequency"):
        extensions["angel_frequency"] = app_state._angel_frequency
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


class _DummyAppState:
    def __init__(
        self, angel_model: str | None = None, angel_frequency: int = 1
    ) -> None:
        self._angel_model = angel_model
        self._angel_frequency = angel_frequency

    def get_setting(self, key: str) -> Any:
        if key == "app_config":

            class Session:
                angel_model = self._angel_model
                angel_frequency = self._angel_frequency

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
    response_processor.process_streaming_response = (
        lambda stream, _session_id, context, **kwargs: stream
    )

    class DummyBackendService:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def chat_completions(self, request, *_, **__):
            self.calls.append("angel")
            assert request.stream is False
            assert request.model == "openai:gpt-4o-mini"
            assert request.messages[-1].role == "assistant"
            assert request.messages[-1].content == "Hello world"
            return type(
                "R",
                (),
                {"content": "<angels_decision>Pass</angels_decision>"},
            )()

    backend_service = DummyBackendService()

    class DummyProvider:
        def get_required_service(self, _t):
            return backend_service

    dummy_provider = DummyProvider()

    manager = create_backend_request_manager(
        backend_processor=backend_processor,
        response_processor=response_processor,
        mock_provider=dummy_provider,
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

    # Mock backend to return the stream
    backend_processor.process_backend_request.return_value = stream_envelope

    context = _make_context(_DummyAppState("openai:gpt-4o-mini"))
    context.original_request = original_request

    # Use public API - Angel verification will run internally
    result = await manager.process_backend_request(
        original_request, "session-pass", context
    )

    assert isinstance(result, StreamingResponseEnvelope)
    forwarded: list[str] = []
    assert result.content is not None
    async for chunk in result.content:
        forwarded.append(str(chunk.content))

    # Should forward original chunks when Angel passes
    assert len(forwarded) >= 2
    assert "Hello" in "".join(forwarded)
    # Angel service should have been called
    assert backend_service.calls == ["angel"]


@pytest.mark.asyncio
async def test_streaming_angel_steer_replaces_with_correction(monkeypatch) -> None:
    backend_processor = AsyncMock()
    response_processor = MagicMock()
    response_processor.process_streaming_response = (
        lambda stream, _session_id, context, **kwargs: stream
    )
    manager = create_backend_request_manager(
        backend_processor=backend_processor,
        response_processor=response_processor,
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

    class DummyBackendService:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def chat_completions(self, request, *_, **__):
            if not self.calls:
                self.calls.append("angel")
                assert request.messages[-1].role == "assistant"
                assert request.messages[-1].content == "Bad output"
                return type(
                    "R",
                    (),
                    {
                        "content": "\n<angels_decision>Steer</angels_decision>\n<angels_steering_message>Be specific</angels_steering_message>\n"
                    },
                )()

            self.calls.append("correction")
            assert request.messages[-2].role == "assistant"
            assert request.messages[-2].content == "Bad output"
            assert request.messages[-1].role == "user"
            return type("R", (), {"content": "Corrected answer"})()

    backend_service = DummyBackendService()

    class DummyProvider:
        def get_required_service(self, _t):
            return backend_service

    dummy_provider = DummyProvider()

    manager = create_backend_request_manager(
        backend_processor=backend_processor,
        response_processor=response_processor,
        mock_provider=dummy_provider,
    )

    # Mock backend to return the stream
    backend_processor.process_backend_request.return_value = stream_envelope

    context = _make_context(_DummyAppState("openai:gpt-4o-mini"))
    context.original_request = original_request

    # Use public API - Angel verification will run internally and replace with correction
    result = await manager.process_backend_request(
        original_request, "session-steer", context
    )

    assert isinstance(result, StreamingResponseEnvelope)
    assert result.content is not None
    chunks_out: list[str] = []
    async for chunk in result.content:
        chunks_out.append(str(chunk.content))

    # Should get corrected answer when Angel steers
    assert len(chunks_out) > 0
    assert "Corrected answer" in "".join(chunks_out)
    assert backend_service.calls == ["angel", "correction"]


@pytest.mark.asyncio
async def test_streaming_angel_override_logic_removed(monkeypatch) -> None:
    backend_processor = AsyncMock()
    response_processor = MagicMock()
    response_processor.process_streaming_response = (
        lambda stream, _session_id, context, **kwargs: stream
    )
    manager = create_backend_request_manager(
        backend_processor=backend_processor,
        response_processor=response_processor,
    )

    original_request = ChatRequest(
        model="openai:gpt-4o-mini",
        messages=[ChatMessage(role="user", content="Hi")],
        stream=True,
    )

    chunks = [
        ProcessedResponse(content="Draft", metadata={}),
        ProcessedResponse(content=" reply", metadata={"is_done": True}),
    ]
    stream_envelope = StreamingResponseEnvelope(content=_build_stream(chunks))

    class DummyBackendService:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def chat_completions(self, request, *_, **__):
            if not self.calls:
                self.calls.append("angel")
                return type(
                    "R",
                    (),
                    {
                        "content": "<angels_steering_message>Check again</angels_steering_message>"
                    },
                )()

            self.calls.append("correction")
            # Return text that used to trigger override
            return type(
                "R",
                (),
                {"content": "<override_angel>True</override_angel> but I corrected it anyway"},
            )()

    backend_service = DummyBackendService()

    class DummyProvider:
        def get_required_service(self, _t):
            return backend_service

    dummy_provider = DummyProvider()

    manager = create_backend_request_manager(
        backend_processor=backend_processor,
        response_processor=response_processor,
        mock_provider=dummy_provider,
    )

    # Mock backend to return the stream
    backend_processor.process_backend_request.return_value = stream_envelope

    context = _make_context(_DummyAppState("openai:gpt-4o-mini"))
    context.original_request = original_request

    # Use public API
    result = await manager.process_backend_request(
        original_request, "session-no-override", context
    )

    assert isinstance(result, StreamingResponseEnvelope)
    assert result.content is not None
    recovered: list[str] = []
    async for chunk in result.content:
        recovered.append(str(chunk.content))

    # Should NOT return original; should return the corrected text even if it contains the (now ignored) override tag
    assert "Draft reply" not in "".join(recovered)
    assert "<override_angel>True</override_angel>" in "".join(recovered)
    assert backend_service.calls == ["angel", "correction"]


@pytest.mark.asyncio
async def test_streaming_angel_respects_frequency(monkeypatch) -> None:
    backend_processor = AsyncMock()
    response_processor = MagicMock()
    response_processor.process_streaming_response = (
        lambda stream, _session_id, context=None, **kwargs: stream
    )
    manager = create_backend_request_manager(
        backend_processor=backend_processor,
        response_processor=response_processor,
    )

    original_request = ChatRequest(
        model="openai:gpt-4o-mini",
        messages=[ChatMessage(role="user", content="Hi")],
        stream=True,
    )

    chunks = [
        ProcessedResponse(content="No Angel", metadata={}),
        ProcessedResponse(content=" needed", metadata={"is_done": True}),
    ]
    stream_envelope = StreamingResponseEnvelope(content=_build_stream(chunks))

    class DummyBackendService:
        async def chat_completions(self, *args, **kwargs):
            pytest.fail("Angel verification should not run before frequency threshold")

    class DummyProvider:
        def get_required_service(self, _t):
            return DummyBackendService()

    monkeypatch.setattr(
        "src.core.di.services.get_service_provider",
        lambda: DummyProvider(),
        raising=False,
    )

    # Mock backend to return the stream
    backend_processor.process_backend_request.return_value = stream_envelope

    context = _make_context(_DummyAppState("openai:gpt-4o-mini", angel_frequency=5))

    # Use public API - Angel verification should skip due to frequency
    result = await manager.process_backend_request(
        original_request, "session-skip", context
    )

    assert isinstance(result, StreamingResponseEnvelope)
    assert result.content is not None
    chunks_out: list[str] = []
    async for chunk in result.content:
        chunks_out.append(str(chunk.content))

    # Should pass through original when Angel frequency threshold not met
    assert len(chunks_out) >= 2
    assert "No Angel" in "".join(chunks_out)
