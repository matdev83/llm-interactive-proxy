from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest
from src.core.config.app_config import AppConfig, SessionConfig
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.interfaces.response_parser_interface import IResponseParser
from src.core.services.response_processor_service import ResponseProcessor
from src.core.services.streaming.content_accumulation_processor import (
    ContentAccumulationProcessor,
)
from src.core.services.streaming.stream_normalizer import StreamNormalizer


class _DummyParser:
    def parse_response(self, response: Any) -> Any:
        return response

    def extract_content(self, response: Any) -> Any:
        return response.get("content")

    def extract_usage(self, response: Any) -> Any:
        return response.get("usage")

    def extract_metadata(self, response: Any) -> Any:
        return response.get("metadata")


class _DummyAppState:
    def __init__(self, config: AppConfig) -> None:
        self._config = config

    def get_setting(self, key: str) -> Any:
        if key == "app_config":
            return self._config
        raise KeyError(key)


def _make_processor(config: AppConfig) -> ResponseProcessor:
    """Create a ResponseProcessor with the unified pipeline architecture."""
    stream_normalizer = StreamNormalizer([ContentAccumulationProcessor()])
    processor = ResponseProcessor(
        response_parser=cast(IResponseParser, _DummyParser()),
        stream_normalizer=stream_normalizer,
    )
    processor._app_state = _DummyAppState(config)  # type: ignore[attr-defined]
    return processor


@pytest.mark.asyncio
async def test_angel_disabled_does_not_call_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = AppConfig(session=SessionConfig(angel_model=None))
    processor = _make_processor(config)

    provider_called = False

    def _provider() -> None:
        nonlocal provider_called
        provider_called = True
        pytest.fail("Backend service should not have been requested")

    monkeypatch.setattr("src.core.di.services.get_service_provider", _provider)

    original_request = ChatRequest(
        model="any",
        messages=[ChatMessage(role="user", content="Hello")],
    )
    context = RequestContext(
        headers={},
        cookies={},
        state=None,
        app_state=None,
        original_request=original_request,
    )
    result = await processor.process_response(
        {"content": "World"},
        session_id="s1",
        context=context,
    )
    assert result.content == "World"
    assert provider_called is False


@pytest.mark.asyncio
async def test_override_marker_never_reaches_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = AppConfig(session=SessionConfig(angel_model="demo"))
    processor = _make_processor(config)

    class DummyBackendService:
        calls = 0

        async def chat_completions(self, req: Any, *args: Any, **kwargs: Any) -> Any:
            self.calls += 1
            if self.calls == 1:
                return SimpleNamespace(
                    content="<angels_steering_message>Something</angels_steering_message>"
                )
            return SimpleNamespace(content="<override_angel>True</override_angel>")

    service = DummyBackendService()

    class DummyProvider:
        def get_required_service(self, t: Any) -> Any:
            return service

    monkeypatch.setattr(
        "src.core.di.services.get_service_provider", lambda: DummyProvider()
    )

    original_request = ChatRequest(
        model="any",
        messages=[ChatMessage(role="user", content="Hello")],
    )
    context = RequestContext(
        headers={},
        cookies={},
        state=None,
        app_state=None,
        original_request=original_request,
    )
    result = await processor.process_response(
        {"content": "Initial"},
        session_id="s2",
        context=context,
    )

    assert "<override_angel>" not in (result.content or "")
    assert result.content == "Initial"
    assert service.calls == 2


@pytest.mark.asyncio
async def test_client_never_sees_angel_xml(monkeypatch: pytest.MonkeyPatch) -> None:
    config = AppConfig(session=SessionConfig(angel_model="demo"))
    processor = _make_processor(config)

    class DummyBackendService:
        calls = 0

        async def chat_completions(self, req: Any, *args: Any, **kwargs: Any) -> Any:
            self.calls += 1
            if self.calls == 1:
                return SimpleNamespace(
                    content="<angels_steering_message>Fix</angels_steering_message>"
                )
            return SimpleNamespace(content="Final answer")

    service = DummyBackendService()

    class DummyProvider:
        def get_required_service(self, t: Any) -> Any:
            return service

    monkeypatch.setattr(
        "src.core.di.services.get_service_provider", lambda: DummyProvider()
    )

    original_request = ChatRequest(
        model="any",
        messages=[ChatMessage(role="user", content="Hello")],
    )
    context = RequestContext(
        headers={},
        cookies={},
        state=None,
        app_state=None,
        original_request=original_request,
    )
    result = await processor.process_response(
        {"content": "Initial"},
        session_id="s3",
        context=context,
    )

    assert "<angels_steering_message>" not in (result.content or "")
    assert "<angels_decision>" not in (result.content or "")
    assert result.content == "Final answer"


@pytest.mark.asyncio
async def test_angel_frequency_can_skip_turns(monkeypatch: pytest.MonkeyPatch) -> None:
    config = AppConfig(session=SessionConfig(angel_model="demo", angel_frequency=10))
    processor = _make_processor(config)

    class DummyBackendService:
        async def chat_completions(self, req: Any, *args: Any, **kwargs: Any) -> Any:
            pytest.fail("Backend should not be called due to frequency check")

    class DummyProvider:
        def get_required_service(self, t: Any) -> Any:
            return DummyBackendService()

    monkeypatch.setattr(
        "src.core.di.services.get_service_provider", lambda: DummyProvider()
    )

    original_request = ChatRequest(
        model="any",
        messages=[ChatMessage(role="user", content="Hello")],
    )
    context = RequestContext(
        headers={},
        cookies={},
        state=None,
        app_state=None,
        original_request=original_request,
    )
    result = await processor.process_response(
        {"content": "First turn"},
        session_id="s4",
        context=context,
    )
    assert result.content == "First turn"
